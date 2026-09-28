"""PDF background inspection and immutable layout contracts."""

from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject

from certificate_automation.pdf_template import (
    PdfFieldLayout,
    PdfPageGeometry,
    PdfTemplateError,
    PdfTemplateInspection,
    PdfTemplateLayout,
    TemplateMode,
    inspect_pdf_template,
)


def _pdf(tmp_path, *, crop=(10, 20, 190, 270), rotation=90, pages=2):
    path = tmp_path / "background.pdf"
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=200, height=300)
        page.cropbox = RectangleObject(crop)
        page.rotate(rotation)
    with path.open("wb") as output:
        writer.write(output)
    return path


def _field(**changes):
    values = dict(name="FULL_NAME", page_index=0, rect=(12, 18, 80, 20),
                  font_family="noto_sans", font_size=12, color="#112233",
                  alignment="center", line_mode="single")
    values.update(changes)
    return PdfFieldLayout(**values)


def test_inspection_records_page_boxes_rotation_and_original_hash(tmp_path):
    path = _pdf(tmp_path)
    original = path.read_bytes()

    inspection = inspect_pdf_template(path)

    assert inspection.sha256 == sha256(original).hexdigest()
    assert inspection.page_count == 2
    assert inspection.pages[0].media_box == (0, 0, 200, 300)
    assert inspection.pages[0].crop_box == (10, 20, 190, 270)
    assert inspection.pages[0].rotation == 90
    assert inspection.pages[0].display_size == (250, 180)
    assert path.read_bytes() == original


def test_crop_relative_display_rect_normalizes_rotated_page():
    page = PdfPageGeometry(0, (0, 0, 200, 300), (10, 20, 190, 270), 90)

    assert page.display_to_pdf_rect((20, 30, 40, 50)) == (40, 40, 90, 80)
    assert PdfPageGeometry(0, (0, 0, 200, 300), (10, 20, 190, 270), 0).display_to_pdf_rect(
        (20, 30, 40, 50)
    ) == (30, 190, 70, 240)
    assert PdfPageGeometry(0, (0, 0, 200, 300), (10, 20, 190, 270), 180).display_to_pdf_rect(
        (20, 30, 40, 50)
    ) == (130, 50, 170, 100)
    assert PdfPageGeometry(0, (0, 0, 200, 300), (10, 20, 190, 270), 270).display_to_pdf_rect(
        (20, 30, 40, 50)
    ) == (110, 210, 160, 250)


def test_inspection_freezes_page_collection(tmp_path):
    path = _pdf(tmp_path)
    page = PdfPageGeometry(0, (0, 0, 200, 300), (10, 20, 190, 270), 90)
    pages = [page]
    inspection = PdfTemplateInspection(path, "a" * 64, pages)

    pages.clear()

    assert inspection.page_count == 1


def test_layout_json_digest_and_immutability(tmp_path):
    inspection = inspect_pdf_template(_pdf(tmp_path))
    layout = PdfTemplateLayout(inspection.sha256, inspection.pages, (_field(),))

    assert PdfTemplateLayout.from_json(layout.to_json()) == layout
    assert layout.digest() == PdfTemplateLayout.from_json(layout.to_json()).digest()
    assert len(layout.digest()) == 64
    with pytest.raises(FrozenInstanceError):
        layout.fields = ()
    assert TemplateMode.PDF_OVERLAY.value == "pdf_overlay"


@pytest.mark.parametrize("name", ["", "   ", "{{NAME}}", "X}Y", "{X"])
def test_invalid_field_names_are_rejected(name):
    with pytest.raises(PdfTemplateError, match="pdf.invalid_field_name"):
        _field(name=name)


@pytest.mark.parametrize("name", ["bad name", "a-b", "9NAME", "奖项 / Награда"])
def test_pdf_field_names_follow_docx_placeholder_names(name):
    assert _field(name=name).name == name


def test_duplicate_names_and_outside_crop_are_rejected(tmp_path):
    inspection = inspect_pdf_template(_pdf(tmp_path))
    with pytest.raises(PdfTemplateError, match="pdf.duplicate_field_name"):
        PdfTemplateLayout(inspection.sha256, inspection.pages, (_field(), _field()))
    with pytest.raises(PdfTemplateError, match="pdf.field_outside_page"):
        PdfTemplateLayout(inspection.sha256, inspection.pages, (_field(rect=(240, 0, 20, 10)),))


def test_encrypted_unreadable_and_zero_page_pdfs_are_rejected(tmp_path):
    path = _pdf(tmp_path)
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(path))
    writer.encrypt("secret")
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(PdfTemplateError, match="pdf.encrypted"):
        inspect_pdf_template(path)

    path.write_bytes(b"not a PDF")
    with pytest.raises(PdfTemplateError, match="pdf.unreadable"):
        inspect_pdf_template(path)

    writer = PdfWriter()
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(PdfTemplateError, match="pdf.zero_pages"):
        inspect_pdf_template(path)


def test_pdf_features_are_classified_and_signatures_block(tmp_path):
    path = tmp_path / "features.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(DictionaryObject())])
    page[NameObject("/Group")] = DictionaryObject({NameObject("/S"): NameObject("/Transparency")})
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([writer._add_object(DictionaryObject({
            NameObject("/FT"): NameObject("/Sig")
        }))])
    })
    writer._root_object[NameObject("/Names")] = DictionaryObject({
        NameObject("/EmbeddedFiles"): DictionaryObject()
    })
    with path.open("wb") as output:
        writer.write(output)

    inspection = inspect_pdf_template(path)
    issues = {issue.code: issue.severity for issue in inspection.issues}

    assert issues == {
        "pdf.interactive_form": "warning",
        "pdf.existing_signature": "blocking",
        "pdf.annotations": "warning",
        "pdf.transparency": "warning",
        "pdf.embedded_files": "warning",
    }
