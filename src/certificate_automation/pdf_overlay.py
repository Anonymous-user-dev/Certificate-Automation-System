"""Offline, deterministic PDF text overlays for approved templates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import Mapping

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMarginsF, QPointF, QSizeF
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage,
    QPageLayout, QPageSize, QPainter, QPdfWriter, QRawFont, QTextLayout, QTextOption,
)
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

from certificate_automation.pdf_template import (
    PdfFieldLayout, PdfTemplateError, PdfTemplateLayout, inspect_pdf_template,
)
from certificate_automation.verification import ArtifactVerificationError, verify_pdf


@dataclass(frozen=True, slots=True)
class PdfOverlayIssue:
    code: str
    field_name: str | None = None


class PdfOverlayError(ValueError):
    """A staged overlay could not be safely produced or published."""

    def __init__(self, code: str, field_name: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.field_name = field_name


class FontRegistry:
    """The exact redistributable fonts allowed in PDF overlays."""

    _qt_families: dict[tuple[int, str], str] = {}
    _verified_material: dict[tuple[str, str], tuple[tuple[int, int, int, int, int], bytes]] = {}
    _FONTS = {
        "noto_sans": (
            "NotoSans-Regular.ttf",
            "b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5",
        ),
        "noto_sans_cjk_sc": (
            "NotoSansCJKsc-Regular.otf",
            "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b",
        ),
    }

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else Path(__file__).parent / "assets" / "fonts"

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(self._FONTS)

    def sha256(self, family: str) -> str:
        try:
            return self._FONTS[family][1]
        except KeyError as error:
            raise ValueError("pdf.invalid_font") from error

    def path(self, family: str) -> Path:
        path, _ = self._font_bytes(family)
        return path

    def _font_bytes(self, family: str) -> tuple[Path, bytes]:
        try:
            filename, expected_hash = self._FONTS[family]
        except KeyError as error:
            raise ValueError("pdf.invalid_font") from error
        path = self._root / filename
        try:
            status = path.stat()
        except OSError as error:
            raise ValueError("pdf.font_unavailable") from error
        fingerprint = (status.st_dev, status.st_ino, status.st_size,
                       status.st_mtime_ns, status.st_ctime_ns)
        cache_key = (str(path.resolve()), expected_hash)
        cached = self._verified_material.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return path, cached[1]
        try:
            material = path.read_bytes()
        except OSError as error:
            raise ValueError("pdf.font_unavailable") from error
        actual_hash = sha256(material).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError("pdf.font_integrity")
        self._verified_material[cache_key] = (fingerprint, material)
        return path, material

    def supports_character(self, family: str, character: str) -> bool:
        if len(character) != 1:
            raise ValueError("pdf.invalid_character")
        if QGuiApplication.instance() is None:
            raise ValueError("pdf.qt_application_required")
        _, material = self._font_bytes(family)
        font = QRawFont(QByteArray(material), 12)
        if not font.isValid():
            raise ValueError("pdf.font_unavailable")
        return font.supportsCharacter(ord(character))

    def qt_font(self, family: str, size: float) -> QFont:
        app = QGuiApplication.instance()
        if app is None:
            raise ValueError("pdf.qt_application_required")
        path, material = self._font_bytes(family)
        path = str(path)
        key = (id(app), path)
        if key not in self._qt_families:
            font_id = QFontDatabase.addApplicationFontFromData(QByteArray(material))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if font_id < 0 or len(families) != 1:
                raise ValueError("pdf.font_unavailable")
            self._qt_families[key] = families[0]
        font = QFont(self._qt_families[key])
        font.setPointSizeF(size)
        font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        return font


def _text_layouts(value: str, font: QFont, width: float, multi: bool) -> tuple[list[QTextLayout], float, float, int]:
    """Shape once with Qt; the same lines are measured and later drawn."""

    if not value:
        return [], 0.0, 0.0, 0
    image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDotsPerMeterX(round(72 / 0.0254))
    image.setDotsPerMeterY(round(72 / 0.0254))
    metrics = QFontMetricsF(font, image)
    line_height = metrics.lineSpacing()
    y = 0.0
    largest_width = 0.0
    line_count = 0
    layouts: list[QTextLayout] = []
    for paragraph in value.split("\n") if multi else (value,):
        if not paragraph:
            y += line_height
            line_count += 1
            continue
        layout = QTextLayout(paragraph, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if multi
                           else QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width if multi else 1_000_000)
            line.setPosition(QPointF(0, y))
            largest_width = max(largest_width, line.naturalTextWidth())
            y += max(line_height, line.height())
            line_count += 1
        layout.endLayout()
        layouts.append(layout)
    return layouts, largest_width, y, line_count


class PdfOverlayRenderer:
    """Fit all mapped text, overlay original pages, then publish atomically."""

    VERSION = "1"

    def __init__(self, fonts: FontRegistry | None = None) -> None:
        self.fonts = fonts if fonts is not None else FontRegistry()

    def inspect_fit(self, layout: PdfTemplateLayout,
                    values: Mapping[str, str]) -> tuple[PdfOverlayIssue, ...]:
        if QGuiApplication.instance() is None:
            raise PdfOverlayError("pdf.qt_application_required")
        issues: list[PdfOverlayIssue] = []
        for field in layout.fields:
            if field.name not in values or not isinstance(values[field.name], str):
                issues.append(PdfOverlayIssue("pdf.unmapped_field", field.name))
                continue
            value = values[field.name]
            try:
                _, material = self.fonts._font_bytes(field.font_family)
                raw_font = QRawFont(QByteArray(material), field.font_size)
                font = self.fonts.qt_font(field.font_family, field.font_size)
            except ValueError as error:
                issues.append(PdfOverlayIssue(str(error), field.name))
                continue
            if not raw_font.isValid():
                issues.append(PdfOverlayIssue("pdf.font_unavailable", field.name))
                continue
            if any(character != "\n" and not raw_font.supportsCharacter(ord(character))
                   for character in value):
                issues.append(PdfOverlayIssue("pdf.missing_glyph", field.name))
                continue
            if "\n" in value and field.line_mode == "single":
                issues.append(PdfOverlayIssue("pdf.text_does_not_fit", field.name))
                continue
            _, text_width, text_height, line_count = _text_layouts(
                value, font, field.rect[2], field.line_mode == "multi"
            )
            if (text_width > field.rect[2] + 0.01 or text_height > field.rect[3] + 0.01
                    or field.max_lines is not None and line_count > field.max_lines):
                issues.append(PdfOverlayIssue("pdf.text_does_not_fit", field.name))
        return tuple(issues)

    def render(self, template_path: Path, destination: Path, layout: PdfTemplateLayout,
               values: Mapping[str, str]) -> None:
        template_path = Path(template_path)
        destination = Path(destination)
        if destination.exists():
            raise PdfOverlayError("pdf.destination_exists")
        try:
            inspection = inspect_pdf_template(template_path)
        except PdfTemplateError as error:
            raise PdfOverlayError(error.code) from error
        if inspection.sha256 != layout.template_sha256:
            raise PdfOverlayError("pdf.template_changed")
        if inspection.pages != layout.pages:
            raise PdfOverlayError("pdf.template_geometry_changed")
        if inspection.blocking_issues:
            raise PdfOverlayError(inspection.blocking_issues[0].code)
        issues = self.inspect_fit(layout, values)
        if issues:
            raise PdfOverlayError(issues[0].code, issues[0].field_name)

        source_bytes = template_path.read_bytes()
        if sha256(source_bytes).hexdigest() != layout.template_sha256:
            raise PdfOverlayError("pdf.template_changed")
        writer = PdfWriter(clone_from=BytesIO(source_bytes))
        for geometry, output_page in zip(layout.pages, writer.pages, strict=True):
            page_fields = [field for field in layout.fields if field.page_index == geometry.index]
            if page_fields:
                overlay = self._overlay_page(geometry, page_fields, values)
                self._verify_overlay_fonts(overlay, any(values[field.name] for field in page_fields))
                overlay_writer = PdfWriter(clone_from=BytesIO(overlay))
                overlay_page = overlay_writer.pages[0]
                overlay_page.add_transformation(
                    Transformation().translate(geometry.media_box[0], geometry.media_box[1])
                )
                overlay_page.mediabox = RectangleObject(geometry.media_box)
                overlay_page.cropbox = RectangleObject(geometry.media_box)
                output_page.merge_page(overlay_page)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{destination.name}.", suffix=".tmp",
                dir=destination.parent, delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                writer.write(temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
            verify_pdf(temporary_path)
            result = PdfReader(BytesIO(temporary_path.read_bytes()), strict=True)
            if len(result.pages) != len(layout.pages) or any(
                tuple(float(number) for number in page.mediabox) != geometry.media_box
                or tuple(float(number) for number in page.cropbox) != geometry.crop_box
                or page.rotation != geometry.rotation
                for page, geometry in zip(result.pages, layout.pages, strict=True)
            ):
                raise PdfOverlayError("pdf.output_geometry_changed")
            try:
                os.link(temporary_path, destination)
            except FileExistsError as error:
                raise PdfOverlayError("pdf.destination_exists") from error
            except OSError as error:
                raise PdfOverlayError("pdf.publish_failed") from error
        except ArtifactVerificationError as error:
            raise PdfOverlayError("pdf.output_unreadable") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _overlay_page(self, geometry, fields: list[PdfFieldLayout],
                      values: Mapping[str, str]) -> bytes:
        media_left, media_bottom, media_right, media_top = geometry.media_box
        width, height = media_right - media_left, media_top - media_bottom
        output = QByteArray()
        buffer = QBuffer(output)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pdf = QPdfWriter(buffer)
        pdf.setResolution(72)
        pdf.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Unit.Point))
        pdf.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        painter = QPainter(pdf)
        left, bottom, right, top = geometry.crop_box
        origins = {
            0: (left - media_left, media_top - top),
            90: (left - media_left, media_top - bottom),
            180: (right - media_left, media_top - bottom),
            270: (right - media_left, media_top - top),
        }
        origin_x, origin_y = origins[geometry.rotation]
        painter.translate(origin_x, origin_y)
        painter.rotate(-geometry.rotation)
        for field in fields:
            painter.save()
            painter.setPen(QColor(field.color))
            font = self.fonts.qt_font(field.font_family, field.font_size)
            painter.setFont(font)
            x, y, box_width, _ = field.rect
            layouts, _, _, _ = _text_layouts(values[field.name], font, box_width,
                                             field.line_mode == "multi")
            for text_layout in layouts:
                for line_index in range(text_layout.lineCount()):
                    line = text_layout.lineAt(line_index)
                    natural_width = line.naturalTextWidth()
                    alignment_offset = (box_width - natural_width) * {
                        "left": 0.0, "center": 0.5, "right": 1.0,
                    }[field.alignment]
                    line.setPosition(QPointF(alignment_offset, line.position().y()))
                text_layout.draw(painter, QPointF(x, y))
            painter.restore()
        painter.end()
        buffer.close()
        return bytes(output)

    @staticmethod
    def _verify_overlay_fonts(overlay: bytes, has_text: bool) -> None:
        """Reject a PDF engine result that cannot carry its selected fonts."""

        try:
            page = PdfReader(BytesIO(overlay), strict=True).pages[0]
            fonts = page["/Resources"].get("/Font", {}).get_object()
            if has_text and not fonts:
                raise ValueError("no font resource")
            for font_ref in fonts.values():
                font = font_ref.get_object()
                descendants = font.get("/DescendantFonts", (font,))
                for descendant_ref in descendants:
                    descendant = descendant_ref.get_object()
                    descriptor = descendant["/FontDescriptor"].get_object()
                    if not any(
                        key in descriptor and descriptor[key].get_object().get_data()
                        for key in ("/FontFile", "/FontFile2", "/FontFile3")
                    ):
                        raise ValueError("font stream absent")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
            raise PdfOverlayError("pdf.font_unembeddable") from error
