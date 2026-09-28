"""PDF background inspection and immutable layout contracts."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
from io import BytesIO
from pathlib import Path

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


def test_explicit_line_limit_is_validated_serialized_and_binds_digest(tmp_path):
    inspection = inspect_pdf_template(_pdf(tmp_path))
    two = PdfTemplateLayout(inspection.sha256, inspection.pages,
                            (_field(line_mode="multi", max_lines=2),))
    three = PdfTemplateLayout(inspection.sha256, inspection.pages,
                              (_field(line_mode="multi", max_lines=3),))

    assert two.fields[0].max_lines == 2
    assert two.to_json()["fields"][0]["max_lines"] == 2
    assert PdfTemplateLayout.from_json(two.to_json()) == two
    assert two.digest() != three.digest()


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_invalid_explicit_line_limits_are_rejected(limit):
    with pytest.raises(PdfTemplateError, match="pdf.invalid_max_lines"):
        _field(line_mode="multi", max_lines=limit)


def test_legacy_layout_without_line_limit_keeps_json_and_digest(tmp_path):
    inspection = inspect_pdf_template(_pdf(tmp_path))
    legacy = PdfTemplateLayout(inspection.sha256, inspection.pages,
                               (_field(line_mode="multi"),))
    old_json = legacy.to_json()
    old_digest = legacy.digest()

    assert "max_lines" not in old_json["fields"][0]
    restored = PdfTemplateLayout.from_json(old_json)
    assert restored.fields[0].max_lines is None
    assert restored.to_json() == old_json
    assert restored.digest() == old_digest


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


def test_transparency_in_nested_indirect_form_xobject_is_reported(tmp_path):
    path = tmp_path / "form-transparency.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    nested_form = DictionaryObject({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): RectangleObject((0, 0, 40, 40)),
        NameObject("/Resources"): DictionaryObject(),
        NameObject("/Group"): DictionaryObject({NameObject("/S"): NameObject("/Transparency")}),
    })
    nested_reference = writer._add_object(nested_form)
    outer_form = DictionaryObject({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): RectangleObject((0, 0, 80, 80)),
        NameObject("/Resources"): writer._add_object(DictionaryObject({
            NameObject("/XObject"): writer._add_object(DictionaryObject({
                NameObject("/Nested"): nested_reference,
            })),
        })),
    })
    outer_reference = writer._add_object(outer_form)
    page[NameObject("/Resources")] = writer._add_object(DictionaryObject({
        NameObject("/XObject"): writer._add_object(DictionaryObject({
            NameObject("/Outer"): outer_reference,
        })),
    }))
    with path.open("wb") as output:
        writer.write(output)

    issues = {issue.code: issue.severity for issue in inspect_pdf_template(path).issues}

    assert issues["pdf.transparency"] == "warning"


def test_transparency_scan_handles_deep_form_chains_and_cycles(tmp_path):
    path = tmp_path / "deep-form-transparency.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    next_reference = None
    for index in reversed(range(80)):
        resources = DictionaryObject()
        if next_reference is not None:
            resources[NameObject("/XObject")] = writer._add_object(DictionaryObject({
                NameObject("/Next"): next_reference,
            }))
        form = DictionaryObject({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): RectangleObject((0, 0, 40, 40)),
            NameObject("/Resources"): writer._add_object(resources),
        })
        if index == 0:
            form[NameObject("/Group")] = DictionaryObject({NameObject("/S"): NameObject("/Transparency")})
        next_reference = writer._add_object(form)
    page[NameObject("/Resources")] = writer._add_object(DictionaryObject({
        NameObject("/XObject"): writer._add_object(DictionaryObject({NameObject("/Start"): next_reference})),
    }))
    with path.open("wb") as output:
        writer.write(output)

    issues = {issue.code: issue.severity for issue in inspect_pdf_template(path).issues}

    assert issues["pdf.transparency"] == "warning"

    cycle_path = tmp_path / "cyclic-form.pdf"
    cycle_writer = PdfWriter()
    cycle_page = cycle_writer.add_blank_page(width=200, height=300)
    cyclic_form = DictionaryObject()
    cyclic_reference = cycle_writer._add_object(cyclic_form)
    cyclic_form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): RectangleObject((0, 0, 40, 40)),
        NameObject("/Resources"): cycle_writer._add_object(DictionaryObject({
            NameObject("/XObject"): cycle_writer._add_object(DictionaryObject({
                NameObject("/Self"): cyclic_reference,
            })),
        })),
    })
    cycle_page[NameObject("/Resources")] = cycle_writer._add_object(DictionaryObject({
        NameObject("/XObject"): cycle_writer._add_object(DictionaryObject({
            NameObject("/Cycle"): cyclic_reference,
        })),
    }))
    with cycle_path.open("wb") as output:
        cycle_writer.write(output)

    cycle_issues = {issue.code: issue.severity for issue in inspect_pdf_template(cycle_path).issues}

    assert "pdf.transparency" not in cycle_issues


def test_inspection_hash_and_geometry_come_from_same_byte_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "changing.pdf"
    original_writer = PdfWriter()
    original_writer.add_blank_page(width=200, height=300)
    original = BytesIO()
    original_writer.write(original)
    original_bytes = original.getvalue()

    replacement_writer = PdfWriter()
    replacement_writer.add_blank_page(width=700, height=900)
    replacement = BytesIO()
    replacement_writer.write(replacement)
    replacement_bytes = replacement.getvalue()
    path.write_bytes(original_bytes)

    open_calls = 0
    real_open = Path.open

    def changing_open(self, *args, **kwargs):
        nonlocal open_calls
        if self == path:
            open_calls += 1
            snapshot = original_bytes if open_calls == 1 else replacement_bytes
            return BytesIO(snapshot)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changing_open)

    inspection = inspect_pdf_template(path)

    assert inspection.sha256 == sha256(original_bytes).hexdigest()
    assert inspection.pages[0].media_box == (0, 0, 200, 300)
    assert open_calls == 1
