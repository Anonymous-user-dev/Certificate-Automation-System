"""Immutable, versioned PDF template geometry and read-only inspection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Mapping

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import DictionaryObject


class TemplateMode(str, Enum):
    DOCX = "docx"
    PDF_OVERLAY = "pdf_overlay"


class PdfTemplateError(ValueError):
    """A PDF background or layout cannot safely be used."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PdfTemplateError("pdf.invalid_geometry")
    return float(value)


def _box(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise PdfTemplateError("pdf.invalid_geometry")
    left, bottom, right, top = (_number(item) for item in value)
    if left >= right or bottom >= top:
        raise PdfTemplateError("pdf.invalid_geometry")
    return left, bottom, right, top


@dataclass(frozen=True, slots=True)
class PdfPageGeometry:
    index: int
    media_box: tuple[float, float, float, float]
    crop_box: tuple[float, float, float, float]
    rotation: int = 0

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise PdfTemplateError("pdf.invalid_geometry")
        media = _box(self.media_box)
        crop = _box(self.crop_box)
        if crop[0] < media[0] or crop[1] < media[1] or crop[2] > media[2] or crop[3] > media[3]:
            raise PdfTemplateError("pdf.invalid_geometry")
        if type(self.rotation) is not int or self.rotation % 90:
            raise PdfTemplateError("pdf.invalid_geometry")
        object.__setattr__(self, "media_box", media)
        object.__setattr__(self, "crop_box", crop)
        object.__setattr__(self, "rotation", self.rotation % 360)

    @property
    def display_size(self) -> tuple[float, float]:
        left, bottom, right, top = self.crop_box
        width, height = right - left, top - bottom
        return (height, width) if self.rotation in (90, 270) else (width, height)

    def display_to_pdf_rect(self, rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """Map top-left, crop-relative display points to absolute PDF box points."""

        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise PdfTemplateError("pdf.invalid_geometry")
        x, y, width, height = (_number(value) for value in rect)
        display_width, display_height = self.display_size
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > display_width or y + height > display_height:
            raise PdfTemplateError("pdf.field_outside_page")
        left, bottom, right, top = self.crop_box
        crop_width, crop_height = right - left, top - bottom
        if self.rotation == 0:
            return left + x, bottom + crop_height - y - height, left + x + width, bottom + crop_height - y
        if self.rotation == 90:
            return left + y, bottom + x, left + y + height, bottom + x + width
        if self.rotation == 180:
            return left + crop_width - x - width, bottom + y, left + crop_width - x, bottom + y + height
        return left + crop_width - y - height, bottom + crop_height - x - width, left + crop_width - y, bottom + crop_height - x

    def to_json(self) -> dict[str, object]:
        return {"index": self.index, "media_box": list(self.media_box),
                "crop_box": list(self.crop_box), "rotation": self.rotation}

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "PdfPageGeometry":
        if not isinstance(data, Mapping):
            raise PdfTemplateError("pdf.invalid_geometry")
        try:
            return cls(data["index"], data["media_box"], data["crop_box"], data["rotation"])
        except KeyError as error:
            raise PdfTemplateError("pdf.invalid_geometry") from error


@dataclass(frozen=True, slots=True)
class PdfFieldLayout:
    name: str
    page_index: int
    rect: tuple[float, float, float, float]
    font_family: str
    font_size: float
    color: str = "#000000"
    alignment: str = "left"
    line_mode: str = "single"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or "{" in self.name or "}" in self.name:
            raise PdfTemplateError("pdf.invalid_field_name")
        object.__setattr__(self, "name", self.name.strip())
        if type(self.page_index) is not int or self.page_index < 0:
            raise PdfTemplateError("pdf.invalid_field_page")
        if not isinstance(self.rect, (list, tuple)) or len(self.rect) != 4:
            raise PdfTemplateError("pdf.invalid_geometry")
        x, y, width, height = (_number(item) for item in self.rect)
        if width <= 0 or height <= 0:
            raise PdfTemplateError("pdf.invalid_geometry")
        object.__setattr__(self, "rect", (x, y, width, height))
        if not isinstance(self.font_family, str) or not self.font_family:
            raise PdfTemplateError("pdf.invalid_font")
        if _number(self.font_size) <= 0:
            raise PdfTemplateError("pdf.invalid_font")
        if not isinstance(self.color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.color):
            raise PdfTemplateError("pdf.invalid_color")
        if self.alignment not in ("left", "center", "right") or self.line_mode not in ("single", "multi"):
            raise PdfTemplateError("pdf.invalid_field_style")

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "page_index": self.page_index, "rect": list(self.rect),
                "font_family": self.font_family, "font_size": self.font_size,
                "color": self.color, "alignment": self.alignment, "line_mode": self.line_mode}

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "PdfFieldLayout":
        if not isinstance(data, Mapping):
            raise PdfTemplateError("pdf.invalid_field")
        try:
            return cls(**data)
        except (TypeError, KeyError) as error:
            raise PdfTemplateError("pdf.invalid_field") from error


@dataclass(frozen=True, slots=True)
class PdfTemplateLayout:
    template_sha256: str
    pages: tuple[PdfPageGeometry, ...]
    fields: tuple[PdfFieldLayout, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.template_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.template_sha256):
            raise PdfTemplateError("pdf.invalid_template_hash")
        if self.schema_version != 1:
            raise PdfTemplateError("pdf.unsupported_layout_schema")
        pages = tuple(self.pages)
        fields = tuple(self.fields)
        if not pages or any(not isinstance(page, PdfPageGeometry) or page.index != index for index, page in enumerate(pages)):
            raise PdfTemplateError("pdf.invalid_geometry")
        if len({field.name for field in fields}) != len(fields):
            raise PdfTemplateError("pdf.duplicate_field_name")
        for field in fields:
            if not isinstance(field, PdfFieldLayout) or field.page_index >= len(pages):
                raise PdfTemplateError("pdf.invalid_field_page")
            pages[field.page_index].display_to_pdf_rect(field.rect)
        object.__setattr__(self, "pages", pages)
        object.__setattr__(self, "fields", fields)

    def to_json(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "template_sha256": self.template_sha256,
                "pages": [page.to_json() for page in self.pages],
                "fields": [field.to_json() for field in self.fields]}

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "PdfTemplateLayout":
        if not isinstance(data, Mapping):
            raise PdfTemplateError("pdf.invalid_layout")
        try:
            return cls(data["template_sha256"],
                       tuple(PdfPageGeometry.from_json(item) for item in data["pages"]),
                       tuple(PdfFieldLayout.from_json(item) for item in data["fields"]),
                       data["schema_version"])
        except (KeyError, TypeError) as error:
            raise PdfTemplateError("pdf.invalid_layout") from error

    def digest(self) -> str:
        encoded = json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PdfTemplateIssue:
    code: str
    severity: str

    def __post_init__(self) -> None:
        if self.severity not in ("warning", "blocking"):
            raise PdfTemplateError("pdf.invalid_issue")

    def to_json(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity}

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "PdfTemplateIssue":
        try:
            return cls(str(data["code"]), str(data["severity"]))
        except (KeyError, TypeError) as error:
            raise PdfTemplateError("pdf.invalid_issue") from error


@dataclass(frozen=True, slots=True)
class PdfTemplateInspection:
    path: Path
    sha256: str
    pages: tuple[PdfPageGeometry, ...]
    issues: tuple[PdfTemplateIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise PdfTemplateError("pdf.invalid_inspection")
        pages = tuple(self.pages)
        issues = tuple(self.issues)
        if not pages or any(not isinstance(page, PdfPageGeometry) or page.index != index for index, page in enumerate(pages)):
            raise PdfTemplateError("pdf.invalid_inspection")
        if any(not isinstance(issue, PdfTemplateIssue) for issue in issues):
            raise PdfTemplateError("pdf.invalid_inspection")
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "pages", pages)
        object.__setattr__(self, "issues", issues)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def blocking_issues(self) -> tuple[PdfTemplateIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "blocking")

    def to_json(self) -> dict[str, object]:
        return {"path": str(self.path), "sha256": self.sha256,
                "pages": [page.to_json() for page in self.pages],
                "issues": [issue.to_json() for issue in self.issues]}

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "PdfTemplateInspection":
        try:
            return cls(Path(data["path"]), str(data["sha256"]),
                       tuple(PdfPageGeometry.from_json(item) for item in data["pages"]),
                       tuple(PdfTemplateIssue.from_json(item) for item in data.get("issues", ())))
        except (KeyError, TypeError) as error:
            raise PdfTemplateError("pdf.invalid_inspection") from error


def _dictionary(value: object) -> DictionaryObject | dict:
    if hasattr(value, "get_object"):
        value = value.get_object()
    return value if isinstance(value, (DictionaryObject, dict)) else {}


def _has_signatures(fields: object) -> bool:
    for field in fields or ():
        entry = _dictionary(field)
        if str(entry.get("/FT", "")) == "/Sig" or _has_signatures(entry.get("/Kids")):
            return True
    return False


def inspect_pdf_template(path: Path) -> PdfTemplateInspection:
    """Read geometry and risk indicators without changing the source PDF."""

    path = Path(path)
    if path.suffix.casefold() != ".pdf":
        raise PdfTemplateError("pdf.unsupported_type")
    try:
        digest = sha256(path.read_bytes()).hexdigest()
        with path.open("rb") as source:
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted:
                raise PdfTemplateError("pdf.encrypted")
            pages = tuple(
                PdfPageGeometry(index, tuple(float(v) for v in page.mediabox),
                                tuple(float(v) for v in page.cropbox), int(page.get("/Rotate", 0)))
                for index, page in enumerate(reader.pages)
            )
            if not pages:
                raise PdfTemplateError("pdf.zero_pages")
            root = _dictionary(reader.trailer.get("/Root"))
            form = _dictionary(root.get("/AcroForm"))
            names = _dictionary(root.get("/Names"))
            issues: list[PdfTemplateIssue] = []
            if form:
                issues.append(PdfTemplateIssue("pdf.interactive_form", "warning"))
            if _has_signatures(form.get("/Fields")) or root.get("/Perms"):
                issues.append(PdfTemplateIssue("pdf.existing_signature", "blocking"))
            if any(page.get("/Annots") for page in reader.pages):
                issues.append(PdfTemplateIssue("pdf.annotations", "warning"))
            if any(
                str(_dictionary(page.get("/Group")).get("/S", "")) == "/Transparency"
                or "/ExtGState" in _dictionary(page.get("/Resources"))
                for page in reader.pages
            ):
                issues.append(PdfTemplateIssue("pdf.transparency", "warning"))
            if "/EmbeddedFiles" in names or root.get("/AF"):
                issues.append(PdfTemplateIssue("pdf.embedded_files", "warning"))
            if any(page.rotation for page in pages):
                issues.append(PdfTemplateIssue("pdf.rotation", "warning"))
        return PdfTemplateInspection(path, digest, pages, tuple(issues))
    except PdfTemplateError:
        raise
    except (OSError, PdfReadError, ValueError, TypeError, KeyError, IndexError) as error:
        raise PdfTemplateError("pdf.unreadable") from error
