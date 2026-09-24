"""Verify a published revision for manual printing and export a checked copy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import errno
import json
import os
from pathlib import Path
import shutil
from typing import Literal, Mapping
from uuid import uuid4

from pypdf import PdfReader

from certificate_automation.audit import pdf_page_fingerprints, sha256_file
from certificate_automation.domain import Issue, Severity
from certificate_automation.integrity import IntegrityService


_TOLERANCE_POINTS = Decimal("1")


@dataclass(frozen=True, slots=True)
class PrintSettings:
    expected_width_points: Decimal
    expected_height_points: Decimal
    orientation: Literal["portrait", "landscape"]
    separator_every: int | None = None

    def __post_init__(self) -> None:
        try:
            width = Decimal(str(self.expected_width_points))
            height = Decimal(str(self.expected_height_points))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("print.settings_invalid") from error
        if (
            not width.is_finite() or not height.is_finite() or width <= 0 or height <= 0
            or self.orientation not in {"portrait", "landscape"}
            or (self.separator_every is not None and
                (type(self.separator_every) is not int or self.separator_every < 1))
        ):
            raise ValueError("print.settings_invalid")
        object.__setattr__(self, "expected_width_points", width)
        object.__setattr__(self, "expected_height_points", height)

    def to_json(self) -> dict[str, object]:
        return {
            "expected_width_points": str(self.expected_width_points),
            "expected_height_points": str(self.expected_height_points),
            "orientation": self.orientation,
            "separator_every": self.separator_every,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "PrintSettings":
        if not isinstance(payload, Mapping):
            raise ValueError("print.settings_invalid")
        return cls(
            Decimal(str(payload["expected_width_points"])),
            Decimal(str(payload["expected_height_points"])),
            str(payload["orientation"]),
            payload.get("separator_every"),
        )


@dataclass(frozen=True, slots=True)
class PrintReadinessReport:
    ready: bool
    recipient_count: int
    individual_page_count: int
    combined_page_count: int
    issues: tuple[Issue, ...]


def _issue(code: str) -> Issue:
    return Issue(Severity.ERROR, "print", code)


def _unique_issues(issues: list[Issue]) -> tuple[Issue, ...]:
    seen: set[str] = set()
    unique: list[Issue] = []
    for issue in issues:
        if issue.code not in seen:
            seen.add(issue.code)
            unique.append(issue)
    return tuple(unique)


def _effective_dimensions(page, box) -> tuple[Decimal, Decimal]:
    width = Decimal(str(float(box.width)))
    height = Decimal(str(float(box.height)))
    rotation = int(page.get("/Rotate", 0)) % 360
    return (height, width) if rotation in (90, 270) else (width, height)


def _page_matches(page, settings: PrintSettings) -> bool:
    for box in (page.mediabox, page.cropbox):
        width, height = _effective_dimensions(page, box)
        if (
            abs(width - settings.expected_width_points) > _TOLERANCE_POINTS
            or abs(height - settings.expected_height_points) > _TOLERANCE_POINTS
        ):
            return False
        orientation = "landscape" if width > height else "portrait"
        if orientation != settings.orientation:
            return False
    return True


class PrintReadinessService:
    def __init__(self, integrity: IntegrityService | None = None) -> None:
        self._integrity = integrity or IntegrityService()

    def verify(
        self, revision: Path, settings: PrintSettings | None = None, *, allow_ready: bool = False,
    ) -> PrintReadinessReport:
        revision = Path(revision)
        integrity = self._integrity.verify_revision(revision, allow_ready=allow_ready)
        issues = [_issue(code) for code in integrity.issues]
        if not integrity.valid:
            return PrintReadinessReport(False, 0, 0, 0, tuple(issues))
        try:
            manifest = json.loads((revision / "manifest.json").read_text("utf-8"))
            stored = PrintSettings.from_json(manifest["selected_outputs"]["print_settings"])
            if settings is not None and settings != stored:
                issues.append(_issue("print.settings_mismatch"))
            settings = stored
            outputs = manifest["outputs"]
            order = manifest["ordered_row_ids"]
            combined = manifest["combined_pdf"]
            recipients = len(outputs)
            if (
                not isinstance(combined, dict) or recipients < 1
                or len(order) != recipients or len(set(order)) != recipients
                or [item["row_id"] for item in outputs] != order
                or combined["source_order"] != order
                or manifest["counts"]["recipients"] != recipients
            ):
                issues.append(_issue("print.order_mismatch"))
                return PrintReadinessReport(False, recipients, 0, 0, tuple(issues))
            source_pages = combined.get("source_page_counts")
            if source_pages is None:
                source_pages = [item.get("pdf_pages") for item in outputs]
            if (
                not isinstance(source_pages, list) or len(source_pages) != recipients
                or any(type(count) is not int or count < 1 for count in source_pages)
            ):
                issues.append(_issue("print.source_pages_missing"))
                return PrintReadinessReport(False, recipients, 0, 0, tuple(issues))
            positions = []
            page_cursor = 0
            for index, count in enumerate(source_pages, start=1):
                page_cursor += count
                if settings.separator_every and index < recipients and index % settings.separator_every == 0:
                    page_cursor += 1
                    positions.append(page_cursor)
            if combined.get("separator_positions", []) != positions:
                issues.append(_issue("print.separator_mismatch"))
            if combined.get("page_count") != page_cursor:
                issues.append(_issue("print.page_count_mismatch"))
            approval_counts = manifest["workflow"]["snapshot"]["output_counts"]
            if approval_counts.get("separator", 0) != len(positions):
                issues.append(_issue("print.separator_mismatch"))
            individual_pages = 0
            source_fingerprints: list[str] = []
            all_individual_present = True
            for index, item in enumerate(outputs):
                pdf_name = item.get("pdf_filename")
                if pdf_name is None:
                    all_individual_present = False
                    continue
                reader = PdfReader(revision / pdf_name, strict=True)
                source_fingerprints.extend(pdf_page_fingerprints(revision / pdf_name))
                if len(reader.pages) != source_pages[index]:
                    issues.append(_issue("print.page_count_mismatch"))
                individual_pages += len(reader.pages)
                if any(not _page_matches(page, settings) for page in reader.pages):
                    issues.append(_issue("print.page_geometry_mismatch"))
            combined_reader = PdfReader(revision / combined["filename"], strict=True)
            if len(combined_reader.pages) != page_cursor:
                issues.append(_issue("print.page_count_mismatch"))
            if any(not _page_matches(page, settings) for page in combined_reader.pages):
                issues.append(_issue("print.page_geometry_mismatch"))
            combined_fingerprints = pdf_page_fingerprints(revision / combined["filename"])
            separator_set = set(positions)
            actual_sources = []
            for position, page in enumerate(combined_reader.pages, start=1):
                if position in separator_set:
                    contents = page.get_contents()
                    if (
                        contents is not None and contents.get_data().strip()
                    ) or page.get("/Annots"):
                        issues.append(_issue("print.separator_mismatch"))
                else:
                    actual_sources.append(combined_fingerprints[position - 1])
            if all_individual_present and tuple(actual_sources) != tuple(source_fingerprints):
                issues.append(_issue("print.order_mismatch"))
            if individual_pages and individual_pages != sum(source_pages):
                issues.append(_issue("print.page_count_mismatch"))
            return PrintReadinessReport(
                not issues, recipients, individual_pages, len(combined_reader.pages),
                _unique_issues(issues),
            )
        except (OSError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation) as error:
            issues.append(_issue("print.verification_failed"))
            return PrintReadinessReport(False, 0, 0, 0, _unique_issues(issues))


class ExportError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExportResult:
    local_authoritative: Path
    exported_copy: Path


def _fsync_directory(path: Path) -> None:
    """Flush staging directory entries where the OS supports directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Publish a verified copy atomically, refusing a concurrently created target."""
    if os.name == "nt":
        os.rename(source, destination)  # Windows rename refuses an existing destination.
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise ExportError("export.atomic_unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise ExportError("export.atomic_unavailable")
        raise OSError(error_number, os.strerror(error_number), str(destination))


class ExportService:
    def __init__(self, integrity: IntegrityService | None = None) -> None:
        self._integrity = integrity or IntegrityService()

    def export_revision(self, source: Path, destination: Path) -> ExportResult:
        source = Path(source)
        destination = Path(destination)
        if not self._integrity.verify_revision(source).valid:
            raise ExportError("export.source_invalid")
        temporary: Path | None = None
        try:
            local = source.resolve(strict=True)
            destination_root = destination.resolve()
            if destination_root == local or local in destination_root.parents:
                raise ExportError("export.destination_inside_source")
            target = destination / source.name
            if target.exists() or target.is_symlink():
                raise ExportError("export.destination_exists")
            originals = {
                item.name: sha256_file(item) for item in source.iterdir() if item.is_file() and not item.is_symlink()
            }
            destination.mkdir(parents=True, exist_ok=True)
            candidate = destination / f".certificate-export-{uuid4().hex[:16]}"
            candidate.mkdir(mode=0o700, exist_ok=False)
            temporary = candidate
            for name, digest in originals.items():
                with (source / name).open("rb") as original, (temporary / name).open("xb") as copied:
                    shutil.copyfileobj(original, copied, length=1024 * 1024)
                    copied.flush()
                    os.fsync(copied.fileno())
                if sha256_file(temporary / name) != digest or sha256_file(source / name) != digest:
                    raise ExportError("export.copy_changed")
            if not self._integrity.verify_revision(source).valid or not self._integrity.verify_revision(
                temporary, allow_ready=True,
            ).valid:
                raise ExportError("export.copy_changed")
            if {item.name: sha256_file(item) for item in temporary.iterdir()} != originals:
                raise ExportError("export.copy_changed")
            _fsync_directory(temporary)
            _fsync_directory(destination)
            _rename_no_replace(temporary, target)
            temporary = None
            return ExportResult(local, target)
        except ExportError:
            raise
        except (OSError, ValueError) as error:
            if isinstance(error, FileExistsError):
                raise ExportError("export.destination_exists") from error
            raise ExportError("export.copy_failed") from error
        finally:
            if temporary is not None and temporary.is_dir() and not temporary.is_symlink():
                if temporary.parent.resolve() == destination.resolve():
                    shutil.rmtree(temporary)
