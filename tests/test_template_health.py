from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from pypdf import PdfWriter

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.domain import Severity
from certificate_automation.mapping import ColumnValue, MappingPlan
from certificate_automation.template import inspect_template
from certificate_automation.template_health import TemplateHealthService
from fixtures import docx_factory, ooxml_docx_factory


def _codes(report):
    return {issue.code for issue in report.issues}


def _dataset():
    return TabularDataset(
        (Column("name", "Name"), Column("award", "Award")),
        (
            DataRow("first", 2, {"name": "Ana", "award": "Gold"}),
            DataRow("long-name", 3, {"name": "Anastasia Petrovna Kuznetsova", "award": "Bronze"}),
            DataRow("long-award", 4, {"name": "Li", "award": "International Academic Excellence"}),
            DataRow("last", 5, {"name": "Bo", "award": "Silver"}),
        ),
        SourceSnapshot("manual", "Manual", None, "a" * 64, datetime.now(timezone.utc)),
    )


def _plan():
    return MappingPlan({"FULL_NAME": ColumnValue("name"), "AWARD": ColumnValue("award")})


def test_health_reports_malformed_and_duplicate_locations(docx_factory):
    path = docx_factory(paragraph_runs=[["{{FULL_NAME} {{AWARD}}"]], header_text="{{AWARD}}")

    report = TemplateHealthService().inspect_structure(path)

    assert {"template.malformed_placeholder", "template.duplicate_placeholder"} <= _codes(report)
    assert any(location.part == "word/header1.xml" for location in report.locations("AWARD"))
    duplicate = next(issue for issue in report.issues if issue.code == "template.duplicate_placeholder")
    assert duplicate.severity is Severity.INFO
    assert "word/header1.xml" in duplicate.parameters["locations"]


def test_health_reports_table_and_textbox_locations(docx_factory, ooxml_docx_factory):
    table = docx_factory(table_text="{{AWARD}}")
    table_report = TemplateHealthService().inspect_structure(table)
    assert table_report.locations("AWARD")[0].table_path

    textbox = ooxml_docx_factory(text_box="{{CERTIFICATE_ID}}")
    box_report = TemplateHealthService().inspect_structure(textbox)
    assert box_report.locations("CERTIFICATE_ID")[0].part == "word/document.xml"


def test_health_reports_protection_links_comments_tracking_and_geometry(docx_factory, tmp_path):
    source = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    changed = tmp_path / "risky.docx"
    with ZipFile(source) as package, ZipFile(changed, "w", ZIP_DEFLATED) as out:
        for member in package.infolist():
            payload = package.read(member.filename)
            if member.filename == "word/settings.xml":
                payload = payload.replace(
                    b"</w:settings>",
                    b'<w:documentProtection w:edit="readOnly" w:enforcement="1"/></w:settings>',
                )
            if member.filename == "word/document.xml":
                payload = payload.replace(b"</w:body>", b'<w:ins w:id="1"/> </w:body>')
            if member.filename == "word/_rels/document.xml.rels":
                payload = payload.replace(
                    b"</Relationships>",
                    b'<Relationship Id="rId900" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/></Relationships>',
                )
            out.writestr(member, payload)
        out.writestr("word/comments.xml", b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')

    report = TemplateHealthService().inspect_structure(changed)

    assert {"template.protected", "template.linked_content", "template.comments", "template.tracked_changes"} <= _codes(report)
    assert report.section_geometries[0].width_points > 0
    assert report.section_geometries[0].height_points > 0
    assert any(issue.blocking for issue in report.issues)


def test_unsupported_embedded_document_content_blocks_review(docx_factory, tmp_path):
    source = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    changed = tmp_path / "embedded.docx"
    with ZipFile(source) as package, ZipFile(changed, "w", ZIP_DEFLATED) as out:
        for member in package.infolist():
            payload = package.read(member.filename)
            if member.filename == "word/document.xml":
                payload = payload.replace(b"</w:body>", b'<w:altChunk/></w:body>')
            out.writestr(member, payload)

    report = TemplateHealthService().inspect_structure(changed)

    assert "template.unsupported_content" in _codes(report)
    assert report.blocking


def test_representatives_cover_longest_mapped_values_and_edges():
    selected = TemplateHealthService().select_representatives(_dataset(), _plan(), limit=8)

    assert {record.row_id for record in selected} == {"first", "long-name", "long-award", "last"}
    assert selected[0].row_id == "first"
    assert selected[-1].row_id == "last"


def test_representatives_are_deterministic_and_capped():
    rows = tuple(DataRow(f"row-{i}", i + 2, {"name": "X" * (i + 1), "award": "Y" * (21 - i)}) for i in range(20))
    data = TabularDataset(
        (Column("name", "Name"), Column("award", "Award")), rows,
        SourceSnapshot("manual", "Manual", None, "a" * 64, datetime.now(timezone.utc)),
    )

    selected = TemplateHealthService().select_representatives(data, _plan(), limit=8)

    assert len(selected) <= 8
    assert selected == TemplateHealthService().select_representatives(data, _plan(), limit=8)
    assert {"row-0", "row-19"} <= {item.row_id for item in selected}


class _PdfConverter:
    def __init__(self, *, pages=1, stale=False):
        self.pages = pages
        self.stale = stale

    def convert(self, _source: Path, destination: Path) -> None:
        if self.stale:
            return
        writer = PdfWriter()
        for _ in range(self.pages):
            writer.add_blank_page(width=612, height=792)
        with destination.open("wb") as stream:
            writer.write(stream)


def test_missing_pdf_never_marks_layout_ready(tmp_path, docx_factory):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}} {{AWARD}}"]]))

    review = TemplateHealthService(converter=_PdfConverter(stale=True), root=tmp_path).render_representatives(
        _dataset(), template, _plan(), expected_pages=1
    )

    assert not review.ready
    assert "preview.stale_output" in _codes(review)


def test_extra_pdf_page_never_marks_layout_ready(tmp_path, docx_factory):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}} {{AWARD}}"]]))

    review = TemplateHealthService(converter=_PdfConverter(pages=2), root=tmp_path).render_representatives(
        _dataset(), template, _plan(), expected_pages=1
    )

    assert not review.ready
    assert "preview.page_count_mismatch" in _codes(review)


def test_row_ids_cannot_escape_isolated_preview_directory(tmp_path, docx_factory):
    dataset = TabularDataset(
        (Column("name", "Name"),),
        (DataRow("../escape", 2, {"name": "Ana"}),),
        SourceSnapshot("manual", "Manual", None, "a" * 64, datetime.now(timezone.utc)),
    )
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))

    result = TemplateHealthService(_PdfConverter(), tmp_path).render_representatives(
        dataset, template, MappingPlan({"FULL_NAME": ColumnValue("name")}), expected_pages=1
    )

    assert result.ready
    assert result.previews[0].pdf_path.resolve().is_relative_to(tmp_path.resolve())
    assert not (tmp_path / "escape.docx").exists()
    assert not (tmp_path / "escape.pdf").exists()


def test_template_change_during_render_never_marks_layout_ready(tmp_path, docx_factory):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}} {{AWARD}}"]]))

    class ChangingConverter(_PdfConverter):
        def convert(self, source, destination):
            super().convert(source, destination)
            template.path.write_bytes(template.path.read_bytes() + b"changed-after-render")

    result = TemplateHealthService(ChangingConverter(), tmp_path).render_representatives(
        _dataset(), template, _plan(), expected_pages=1
    )

    assert not result.ready
    assert "validation.template_changed" in _codes(result)


def test_layout_cleanup_removes_only_its_session_directory(tmp_path, docx_factory):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}} {{AWARD}}"]]))
    keep = tmp_path / "keep.txt"
    keep.write_text("mine", encoding="utf-8")
    service = TemplateHealthService(_PdfConverter(), tmp_path)
    result = service.render_representatives(_dataset(), template, _plan(), expected_pages=1)
    assert result.ready

    service.clear()

    assert not result.previews[0].pdf_path.exists()
    assert keep.read_text(encoding="utf-8") == "mine"
