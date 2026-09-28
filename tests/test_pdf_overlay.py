"""Behavioral checks for the offline PDF overlay renderer."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import shutil

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject
from PySide6.QtCore import QSize
from PySide6.QtPdf import QPdfDocument
from PySide6.QtGui import QFontDatabase, QTextLayout

from certificate_automation.pdf_overlay import FontRegistry, PdfOverlayError, PdfOverlayRenderer
from certificate_automation.pdf_template import (
    PdfFieldLayout, PdfPageGeometry, PdfTemplateLayout, inspect_pdf_template,
)


def test_font_registry_loads_only_the_pinned_packaged_font(qapp):
    registry = FontRegistry()

    assert registry.families == ("noto_sans", "noto_sans_cjk_sc")
    assert registry.sha256("noto_sans") == "b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5"
    assert registry.sha256("noto_sans_cjk_sc") == "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b"
    for family in registry.families:
        assert sha256(registry.path(family).read_bytes()).hexdigest() == registry.sha256(family)
    with pytest.raises(ValueError, match="pdf.invalid_font"):
        registry.path("Arial")


@pytest.mark.parametrize("family,character", [
    ("noto_sans", "A"), ("noto_sans", "Ж"),
    ("noto_sans_cjk_sc", "A"), ("noto_sans_cjk_sc", "Ж"),
    ("noto_sans_cjk_sc", "中"), ("noto_sans_cjk_sc", "奖"),
])
def test_font_registry_supports_required_scripts(qapp, family, character):
    assert FontRegistry().supports_character(family, character)


def test_font_registry_rejects_unsupported_emoji(qapp):
    assert not FontRegistry().supports_character("noto_sans_cjk_sc", "😀")


def test_font_registry_refuses_tampered_bundle_without_fallback(qapp, tmp_path):
    original = FontRegistry().path("noto_sans")
    copied = tmp_path / original.name
    shutil.copyfile(original, copied)
    copied.write_bytes(copied.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="pdf.font_integrity"):
        FontRegistry(tmp_path).qt_font("noto_sans", 12)


def test_reusing_packaged_font_does_not_register_duplicate_qt_copies(qapp, tmp_path, monkeypatch):
    original = FontRegistry().path("noto_sans")
    shutil.copyfile(original, tmp_path / original.name)
    registry = FontRegistry(tmp_path)
    real_add = QFontDatabase.addApplicationFont
    additions = []

    def recording_add(path):
        additions.append(path)
        return real_add(path)

    monkeypatch.setattr(QFontDatabase, "addApplicationFont", staticmethod(recording_add))
    assert registry.qt_font("noto_sans", 12).family() == "Noto Sans"
    assert registry.qt_font("noto_sans", 18).family() == "Noto Sans"
    assert FontRegistry(tmp_path).qt_font("noto_sans", 24).family() == "Noto Sans"
    assert additions == [str(tmp_path / original.name)]


def _template(tmp_path: Path, pages=((200, 300, (0, 0, 200, 300), 0),)) -> Path:
    path = tmp_path / "background.pdf"
    writer = PdfWriter()
    for width, height, crop, rotation in pages:
        page = writer.add_blank_page(width=width, height=height)
        page.cropbox = RectangleObject(crop)
        if rotation:
            page.rotate(rotation)
    with path.open("wb") as output:
        writer.write(output)
    return path


def _layout(path: Path, *, rect=(20, 30, 150, 30), text_mode="single", page_index=0,
            family="noto_sans_cjk_sc", font_size=12) -> PdfTemplateLayout:
    inspection = inspect_pdf_template(path)
    field = PdfFieldLayout("FULL_NAME", page_index, rect, family, font_size,
                           line_mode=text_mode)
    return PdfTemplateLayout(inspection.sha256, inspection.pages, (field,))


def test_single_line_fit_accepts_boundary_and_rejects_horizontal_overflow(qapp, tmp_path):
    path = _template(tmp_path)
    renderer = PdfOverlayRenderer()
    assert renderer.inspect_fit(_layout(path), {"FULL_NAME": "Ada Lovelace"}) == ()
    issues = renderer.inspect_fit(_layout(path, rect=(20, 30, 35, 30)),
                                  {"FULL_NAME": "Ada Lovelace"})
    assert [(issue.code, issue.field_name) for issue in issues] == [
        ("pdf.text_does_not_fit", "FULL_NAME")]


def test_fit_rejects_vertical_overflow_without_shrinking(qapp, tmp_path):
    path = _template(tmp_path)
    issues = PdfOverlayRenderer().inspect_fit(_layout(path, rect=(20, 30, 150, 4)),
                                              {"FULL_NAME": "Ada"})
    assert [issue.code for issue in issues] == ["pdf.text_does_not_fit"]


def test_single_line_accepts_exact_measured_width_but_rejects_less(qapp, tmp_path):
    path = _template(tmp_path)
    font = FontRegistry().qt_font("noto_sans", 12)
    text = QTextLayout("AAAA", font)
    text.beginLayout()
    line = text.createLine()
    line.setLineWidth(1000)
    measured_width = line.naturalTextWidth()
    text.endLayout()
    renderer = PdfOverlayRenderer()

    assert renderer.inspect_fit(_layout(path, rect=(20, 30, measured_width, 40),
                                        family="noto_sans"), {"FULL_NAME": "AAAA"}) == ()
    assert [issue.code for issue in renderer.inspect_fit(
        _layout(path, rect=(20, 30, measured_width - 1, 40), family="noto_sans"),
        {"FULL_NAME": "AAAA"})] == ["pdf.text_does_not_fit"]


def test_multi_line_wrap_is_explicit_and_bounded_by_height(qapp, tmp_path):
    path = _template(tmp_path)
    text = "Ada Lovelace Charles Babbage"
    renderer = PdfOverlayRenderer()
    single = renderer.inspect_fit(_layout(path, rect=(20, 30, 70, 100)), {"FULL_NAME": text})
    multi = renderer.inspect_fit(_layout(path, rect=(20, 30, 70, 100), text_mode="multi"),
                                 {"FULL_NAME": text})
    too_short = renderer.inspect_fit(_layout(path, rect=(20, 30, 70, 16), text_mode="multi"),
                                     {"FULL_NAME": text})
    assert [issue.code for issue in single] == ["pdf.text_does_not_fit"]
    assert multi == ()
    assert [issue.code for issue in too_short] == ["pdf.text_does_not_fit"]


def test_missing_glyph_and_unmapped_value_are_explicit(qapp, tmp_path):
    path = _template(tmp_path)
    renderer = PdfOverlayRenderer()
    assert [issue.code for issue in renderer.inspect_fit(_layout(path), {"FULL_NAME": "Ada 😀"})] == [
        "pdf.missing_glyph"]
    assert [issue.code for issue in renderer.inspect_fit(_layout(path), {})] == [
        "pdf.unmapped_field"]


def test_combining_mark_is_measured_and_rendered_without_substitution(qapp, tmp_path):
    path = _template(tmp_path)
    layout = _layout(path, family="noto_sans")
    value = "Cafe\u0301"
    assert PdfOverlayRenderer().inspect_fit(layout, {"FULL_NAME": value}) == ()
    destination = tmp_path / "combined.pdf"
    PdfOverlayRenderer().render(path, destination, layout, {"FULL_NAME": value})
    assert "Café" in PdfReader(destination).pages[0].extract_text()


@pytest.mark.parametrize("pages", [
    ((200, 300, (0, 0, 200, 300), 0),),
    ((300, 200, (0, 0, 300, 200), 0),),
    ((200, 300, (10, 20, 190, 270), 90),),
    ((200, 300, (10, 20, 190, 270), 180),),
    ((200, 300, (10, 20, 190, 270), 270),),
    ((200, 300, (0, 0, 200, 300), 0), (300, 200, (10, 10, 290, 190), 0)),
])
def test_render_preserves_background_geometry_and_embeds_text_font(qapp, tmp_path, pages):
    path = _template(tmp_path, pages)
    original = path.read_bytes()
    inspection = inspect_pdf_template(path)
    display_width, _ = inspection.pages[-1].display_size
    layout = _layout(path, rect=(10, 10, min(150, display_width - 20), 30),
                     page_index=len(pages) - 1)
    destination = tmp_path / "rendered.pdf"

    PdfOverlayRenderer().render(path, destination, layout, {"FULL_NAME": "Ada Ж中"})

    result = PdfReader(destination, strict=True)
    source = PdfReader(BytesIO(original), strict=True)
    assert path.read_bytes() == original
    assert len(result.pages) == len(source.pages)
    for actual, expected in zip(result.pages, source.pages):
        assert list(actual.mediabox) == list(expected.mediabox)
        assert list(actual.cropbox) == list(expected.cropbox)
        assert actual.rotation == expected.rotation
    page = result.pages[-1]
    extracted = "".join(page.extract_text().split())
    assert "AdaЖ中" in extracted
    fonts = page["/Resources"]["/Font"].get_object().values()
    assert any(
        any(key in descendant["/FontDescriptor"].get_object()
            for key in ("/FontFile", "/FontFile2", "/FontFile3"))
        for font_ref in fonts
        for descendant_ref in font_ref.get_object().get("/DescendantFonts", ())
        for descendant in (descendant_ref.get_object(),)
    )


def test_render_rejects_stale_destination_without_touching_it(qapp, tmp_path):
    path = _template(tmp_path)
    destination = tmp_path / "stale.pdf"
    destination.write_bytes(b"existing")
    with pytest.raises(PdfOverlayError, match="pdf.destination_exists"):
        PdfOverlayRenderer().render(path, destination, _layout(path), {"FULL_NAME": "Ada"})
    assert destination.read_bytes() == b"existing"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["background.pdf", "stale.pdf"]


def test_render_rejects_changed_template_and_overflow_before_publication(qapp, tmp_path):
    path = _template(tmp_path)
    layout = _layout(path, rect=(20, 30, 30, 30))
    destination = tmp_path / "out.pdf"
    with pytest.raises(PdfOverlayError, match="pdf.text_does_not_fit"):
        PdfOverlayRenderer().render(path, destination, layout, {"FULL_NAME": "Long certificate name"})
    assert not destination.exists()

    path.write_bytes(path.read_bytes() + b"\n% changed\n")
    with pytest.raises(PdfOverlayError, match="pdf.template_changed"):
        PdfOverlayRenderer().render(path, destination, layout, {"FULL_NAME": "Ada"})
    assert not destination.exists()


def test_render_refuses_overlay_whose_font_cannot_be_embedded(qapp, tmp_path, monkeypatch):
    path = _template(tmp_path)
    destination = tmp_path / "unembedded.pdf"
    renderer = PdfOverlayRenderer()
    original_overlay = renderer._overlay_page

    def unembedded_overlay(*args):
        source = PdfReader(BytesIO(original_overlay(*args)))
        writer = PdfWriter()
        page = writer.add_page(source.pages[0])
        for font_ref in page["/Resources"]["/Font"].get_object().values():
            for descendant_ref in font_ref.get_object().get("/DescendantFonts", ()):
                descriptor = descendant_ref.get_object()["/FontDescriptor"].get_object()
                for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                    descriptor.pop(NameObject(key), None)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    monkeypatch.setattr(renderer, "_overlay_page", unembedded_overlay)
    with pytest.raises(PdfOverlayError, match="pdf.font_unembeddable"):
        renderer.render(path, destination, _layout(path), {"FULL_NAME": "Ada"})
    assert not destination.exists()


@pytest.mark.parametrize("bad_pdf,expected", [
    ("encrypted", "pdf.encrypted"),
    ("malformed", "pdf.unreadable"),
])
def test_render_reports_unusable_background_as_stable_overlay_error(qapp, tmp_path, bad_pdf, expected):
    path = tmp_path / "unsafe.pdf"
    if bad_pdf == "encrypted":
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.encrypt("secret")
        with path.open("wb") as output:
            writer.write(output)
    else:
        path.write_bytes(b"not a PDF")
    field = PdfFieldLayout("FULL_NAME", 0, (20, 30, 100, 30), "noto_sans", 12)
    layout = PdfTemplateLayout(sha256(path.read_bytes()).hexdigest(),
                               (PdfPageGeometry(0, (0, 0, 200, 300), (0, 0, 200, 300)),),
                               (field,))
    with pytest.raises(PdfOverlayError, match=expected):
        PdfOverlayRenderer().render(path, tmp_path / "out.pdf", layout, {"FULL_NAME": "Ada"})
    assert not (tmp_path / "out.pdf").exists()


def test_signed_template_is_never_overlaid(qapp, tmp_path):
    path = tmp_path / "signed.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    signature = writer._add_object(DictionaryObject({NameObject("/FT"): NameObject("/Sig")}))
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([signature])
    })
    with path.open("wb") as output:
        writer.write(output)

    destination = tmp_path / "out.pdf"
    with pytest.raises(PdfOverlayError, match="pdf.existing_signature"):
        PdfOverlayRenderer().render(path, destination, _layout(path), {"FULL_NAME": "Ada"})
    assert not destination.exists()


def test_render_closes_handles_after_publish(qapp, tmp_path):
    path = _template(tmp_path)
    destination = tmp_path / "out.pdf"
    PdfOverlayRenderer().render(path, destination, _layout(path), {"FULL_NAME": "Ada"})
    path.rename(tmp_path / "moved-template.pdf")
    destination.rename(tmp_path / "moved-output.pdf")


@pytest.mark.parametrize("filename", ["portrait.pdf", "landscape.pdf", "cropped-rotated.pdf", "multi-page.pdf"])
def test_static_geometry_fixture_preserves_existing_artwork(qapp, tmp_path, filename):
    template = Path(__file__).parent / "fixtures" / "pdf_templates" / filename
    source = PdfReader(template)
    layout = _layout(template, page_index=len(source.pages) - 1,
                     rect=(30, 50, 100, 30), family="noto_sans")
    destination = tmp_path / "fixture-result.pdf"
    PdfOverlayRenderer().render(template, destination, layout, {"FULL_NAME": "Ada"})
    result = PdfReader(destination)

    assert len(result.pages) == len(source.pages)
    for old, new in zip(source.pages, result.pages):
        assert old.get_contents().get_data() in new.get_contents().get_data()
    assert "Ada" in result.pages[-1].extract_text()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rasterized_text_stays_inside_crop_relative_field_at_every_rotation(qapp, tmp_path, rotation):
    path = _template(tmp_path, ((200, 300, (10, 20, 190, 270), rotation),))
    layout = _layout(path, rect=(20, 30, 90, 30), family="noto_sans")
    destination = tmp_path / "positioned.pdf"
    PdfOverlayRenderer().render(path, destination, layout, {"FULL_NAME": "Ada"})

    pdf = QPdfDocument(qapp)
    assert pdf.load(str(destination)) == QPdfDocument.Error.None_
    size = pdf.pagePointSize(0)
    expected_size = layout.pages[0].display_size
    assert abs(size.width() - expected_size[0]) <= 1
    assert abs(size.height() - expected_size[1]) <= 1
    image = pdf.render(0, QSize(round(size.width()), round(size.height())))
    dark = [(x, y) for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 30
            and image.pixelColor(x, y).lightness() < 160]
    pdf.close()

    assert dark
    left, top, right, bottom = (min(x for x, _ in dark), min(y for _, y in dark),
                                max(x for x, _ in dark), max(y for _, y in dark))
    # The rasterizer rounds point coordinates; allow one pixel at each edge.
    assert 19 <= left <= 30
    assert 29 <= top <= 40
    assert right <= 111
    assert bottom <= 61
