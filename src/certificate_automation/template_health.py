"""Read-only OOXML health checks and conservative Word layout reviews."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import time
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from lxml import etree
from pypdf import PdfReader

from certificate_automation.dataset import TabularDataset
from certificate_automation.domain import Issue, Severity
from certificate_automation.mapping import MappingPlan, evaluate_plan
from certificate_automation.template import (
    PLACEHOLDER_PATTERN,
    WORD_NAMESPACE,
    WORD_PARAGRAPH,
    TemplateInputError,
    TemplateInspection,
    _paragraph_text_nodes,
    _parse_xml,
    _read_package,
    _sha256_file,
    _story_parts,
    render_template,
)
from certificate_automation.verification import verify_docx, verify_pdf


W = f"{{{WORD_NAMESPACE}}}"
RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass(frozen=True, slots=True)
class TemplateLocation:
    part: str
    paragraph_index: int
    table_path: tuple[int, ...] = ()

    @property
    def display(self) -> str:
        table = " / " + ".".join(map(str, self.table_path)) if self.table_path else ""
        return f"{self.part}: paragraph {self.paragraph_index + 1}{table}"


@dataclass(frozen=True, slots=True)
class PageGeometry:
    width_points: float
    height_points: float
    orientation: str


@dataclass(frozen=True, slots=True)
class TemplateHealthReport:
    template_sha256: str
    issues: tuple[Issue, ...]
    placeholders: Mapping[str, tuple[TemplateLocation, ...]]
    section_geometries: tuple[PageGeometry, ...]
    representative_rows: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "placeholders", MappingProxyType(dict(self.placeholders)))

    def locations(self, name: str) -> tuple[TemplateLocation, ...]:
        return self.placeholders.get(name, ())

    @property
    def blocking(self) -> bool:
        return any(issue.blocking for issue in self.issues)


@dataclass(frozen=True, slots=True)
class RepresentativeRecord:
    row_id: str
    reasons: tuple[str, ...]
    risk_score: int


@dataclass(frozen=True, slots=True)
class RepresentativePreview:
    row_id: str
    pdf_path: Path
    pdf_sha256: str
    page_count: int


@dataclass(frozen=True, slots=True)
class LayoutReviewResult:
    revision_key: str
    representatives: tuple[RepresentativeRecord, ...]
    previews: tuple[RepresentativePreview, ...]
    issues: tuple[Issue, ...]

    @property
    def ready(self) -> bool:
        return bool(self.previews) and len(self.previews) == len(self.representatives) and not any(
            issue.blocking for issue in self.issues
        )


def _issue(severity: Severity, code: str, **parameters: str | int) -> Issue:
    return Issue(severity, "template", code, parameters)


def _table_path(paragraph: etree._Element) -> tuple[int, ...]:
    parts: list[int] = []
    node = paragraph.getparent()
    while node is not None:
        if node.tag in {W + "tbl", W + "tr", W + "tc"}:
            parts.append(sum(1 for sibling in node.itersiblings(preceding=True) if sibling.tag == node.tag))
        node = node.getparent()
    return tuple(reversed(parts))


class TemplateHealthService:
    def __init__(self, converter=None, root: Path | None = None) -> None:
        self._converter = converter
        base = Path(root or Path(tempfile.gettempdir()) / "certificate-automation-layout-reviews")
        self._root = base / uuid4().hex

    def clear(self) -> None:
        """Discard this session's temporary PDFs after viewers release them."""

        try:
            if self._root.is_dir():
                shutil.rmtree(self._root)
        except OSError:
            # A Windows PDF viewer may briefly retain a file handle.
            pass

    def inspect_structure(self, path: Path) -> TemplateHealthReport:
        """Report risky structure without altering template replacement policy."""

        path = Path(path)
        try:
            members = _read_package(path)
            digest = _sha256_file(path)
        except (TemplateInputError, OSError) as error:
            code = getattr(error, "code", "template.invalid")
            return TemplateHealthReport("", (_issue(Severity.ERROR, code),), {}, ())
        names = {member.filename for member, _ in members}
        issues: list[Issue] = []
        locations: dict[str, list[TemplateLocation]] = {}
        geometries: list[PageGeometry] = []

        if any(name.casefold().endswith("vbaproject.bin") for name in names):
            issues.append(_issue(Severity.ERROR, "template.macros_present"))
        if "word/comments.xml" in names:
            issues.append(_issue(Severity.WARNING, "template.comments"))

        for member, data in members:
            part_name = member.filename
            if part_name.endswith(".rels"):
                try:
                    root = _parse_xml(data, path)
                    if any(element.get("TargetMode", "").casefold() == "external" for element in root.iter()):
                        issues.append(_issue(Severity.WARNING, "template.linked_content", part=part_name))
                except TemplateInputError:
                    issues.append(_issue(Severity.ERROR, "template.inaccessible_part", part=part_name))
            if part_name == "word/settings.xml":
                try:
                    root = _parse_xml(data, path)
                    if root.find(f".//{W}documentProtection") is not None:
                        issues.append(_issue(Severity.ERROR, "template.protected"))
                except TemplateInputError:
                    issues.append(_issue(Severity.ERROR, "template.inaccessible_part", part=part_name))

        for part_name, data in _story_parts(members):
            try:
                root = _parse_xml(data, path)
            except TemplateInputError:
                issues.append(_issue(Severity.ERROR, "template.inaccessible_part", part=part_name))
                continue
            if any(node.tag in {W + "ins", W + "del", W + "moveFrom", W + "moveTo"} for node in root.iter()):
                issues.append(_issue(Severity.WARNING, "template.tracked_changes", part=part_name))
            if any(node.tag in {W + "fldChar", W + "fldSimple", W + "instrText"} for node in root.iter()):
                issues.append(_issue(Severity.WARNING, "template.fields", part=part_name))
            if any(node.tag in {W + "altChunk", W + "object"} for node in root.iter()):
                issues.append(_issue(Severity.ERROR, "template.unsupported_content", part=part_name))
            for index, paragraph in enumerate(root.iter(WORD_PARAGRAPH)):
                text = "".join(node.text or "" for node in _paragraph_text_nodes(paragraph))
                location = TemplateLocation(part_name, index, _table_path(paragraph))
                matches = list(PLACEHOLDER_PATTERN.finditer(text))
                remainder = PLACEHOLDER_PATTERN.sub("", text)
                if "{{" in remainder or "}}" in remainder or any(not match.group(1).strip() for match in matches):
                    issues.append(_issue(Severity.ERROR, "template.malformed_placeholder", location=location.display))
                for match in matches:
                    name = match.group(1).strip()
                    if name:
                        locations.setdefault(name, []).append(location)
            if part_name == "word/document.xml":
                for section in root.iter(W + "sectPr"):
                    page_size = section.find(W + "pgSz")
                    if page_size is None:
                        issues.append(_issue(Severity.WARNING, "template.page_size_unknown"))
                        continue
                    try:
                        width = int(page_size.get(W + "w", "0")) / 20
                        height = int(page_size.get(W + "h", "0")) / 20
                    except ValueError:
                        width = height = 0
                    if width <= 0 or height <= 0:
                        issues.append(_issue(Severity.ERROR, "template.page_size_invalid"))
                        continue
                    orientation = "landscape" if width > height else "portrait"
                    geometries.append(PageGeometry(width, height, orientation))

        for name, entries in locations.items():
            if len(entries) > 1:
                issues.append(_issue(
                    Severity.INFO, "template.duplicate_placeholder",
                    placeholder=name, count=len(entries),
                    locations="; ".join(item.display for item in entries),
                ))
        if len(geometries) > 1:
            issues.append(_issue(Severity.WARNING, "template.multiple_sections", count=len(geometries)))
        if len({(item.width_points, item.height_points) for item in geometries}) > 1:
            issues.append(_issue(Severity.WARNING, "template.mixed_geometry"))
        if not locations:
            issues.append(_issue(Severity.ERROR, "validation.no_placeholders"))
        return TemplateHealthReport(
            digest, tuple(issues), {name: tuple(entries) for name, entries in locations.items()},
            tuple(geometries),
        )

    @staticmethod
    def revision_key(dataset: TabularDataset, template: TemplateInspection, plan: MappingPlan) -> str:
        encoded = json.dumps(
            {"dataset": dataset.to_json(), "template": template.sha256, "mapping": plan.to_json()},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def select_representatives(
        self, dataset: TabularDataset, plan: MappingPlan, *, limit: int = 8
    ) -> tuple[RepresentativeRecord, ...]:
        if limit < 1 or not dataset.order:
            return ()
        values = {row_id: evaluate_plan(plan, dataset, row_id) for row_id in dataset.order}
        scores = {row_id: sum(len(value) for value in values[row_id].values()) for row_id in dataset.order}
        selected: dict[str, set[str]] = {}
        selected.setdefault(dataset.order[0], set()).add("first")
        selected.setdefault(dataset.order[-1], set()).add("last")
        for field in plan.sources:
            longest = max(dataset.order, key=lambda row_id: (len(values[row_id][field]), -dataset.order.index(row_id)))
            selected.setdefault(longest, set()).add(f"longest:{field}")
        highest = max(dataset.order, key=lambda row_id: (scores[row_id], -dataset.order.index(row_id)))
        selected.setdefault(highest, set()).add("highest-risk")
        if len(selected) > limit:
            anchors = {dataset.order[0], dataset.order[-1], highest}
            chosen = [row_id for row_id in dataset.order if row_id in anchors][:limit]
            remaining = sorted(
                (row_id for row_id in selected if row_id not in chosen),
                key=lambda row_id: (-len(selected[row_id]), -scores[row_id], dataset.order.index(row_id)),
            )
            chosen.extend(remaining[: max(0, limit - len(chosen))])
            selected = {row_id: selected[row_id] for row_id in chosen}
        return tuple(
            RepresentativeRecord(row_id, tuple(sorted(selected[row_id])), scores[row_id])
            for row_id in dataset.order if row_id in selected
        )

    def render_representatives(
        self, dataset: TabularDataset, template: TemplateInspection, plan: MappingPlan,
        *, expected_pages: int, limit: int = 8,
    ) -> LayoutReviewResult:
        records = self.select_representatives(dataset, plan, limit=limit)
        key = self.revision_key(dataset, template, plan)
        issues: list[Issue] = []
        previews: list[RepresentativePreview] = []
        if self._converter is None:
            return LayoutReviewResult(key, records, (), (_issue(Severity.ERROR, "preview.word_unavailable"),))
        if expected_pages < 1:
            return LayoutReviewResult(key, records, (), (_issue(Severity.ERROR, "preview.page_count_unknown"),))
        health = self.inspect_structure(template.path)
        if health.template_sha256 != template.sha256 or health.blocking:
            return LayoutReviewResult(key, records, (), (_issue(Severity.ERROR, "validation.template_changed"),))
        run_dir = self._root / uuid4().hex
        run_dir.mkdir(parents=True, exist_ok=False)
        for index, record in enumerate(records, start=1):
            docx_path = run_dir / f"sample-{index:02d}.docx"
            pdf_path = run_dir / f"sample-{index:02d}.pdf"
            try:
                render_template(template.path, docx_path, evaluate_plan(plan, dataset, record.row_id))
                verify_docx(docx_path, set(template.names))
                before = time.time_ns()
                self._converter.convert(docx_path, pdf_path)
                if not pdf_path.is_file() or pdf_path.stat().st_mtime_ns + 2_000_000_000 < before:
                    issues.append(_issue(Severity.ERROR, "preview.stale_output", row=record.row_id))
                    continue
                first_size = pdf_path.stat().st_size
                time.sleep(0.05)
                second_size = pdf_path.stat().st_size
                if first_size == 0 or first_size != second_size:
                    issues.append(_issue(Severity.ERROR, "preview.partial_output", row=record.row_id))
                    continue
                verify_pdf(pdf_path)
                reader = PdfReader(pdf_path, strict=True)
                pages = len(reader.pages)
                if pages != expected_pages:
                    issues.append(_issue(Severity.ERROR, "preview.page_count_mismatch", row=record.row_id, expected=expected_pages, actual=pages))
                    continue
                for page in reader.pages:
                    width = float(page.mediabox.width)
                    height = float(page.mediabox.height)
                    if health.section_geometries and not any(
                        abs(width - geometry.width_points) <= 2 and abs(height - geometry.height_points) <= 2
                        for geometry in health.section_geometries
                    ):
                        issues.append(_issue(Severity.ERROR, "preview.geometry_mismatch", row=record.row_id))
                        break
                else:
                    previews.append(RepresentativePreview(record.row_id, pdf_path, _sha256_file(pdf_path), pages))
            except Exception:
                issues.append(_issue(Severity.ERROR, "preview.render_failed", row=record.row_id))
        try:
            if _sha256_file(template.path) != template.sha256:
                issues.append(_issue(Severity.ERROR, "validation.template_changed"))
        except OSError:
            issues.append(_issue(Severity.ERROR, "validation.template_changed"))
        if previews:
            issues.append(_issue(Severity.WARNING, "template.layout_review_required"))
        return LayoutReviewResult(key, records, tuple(previews), tuple(issues))
