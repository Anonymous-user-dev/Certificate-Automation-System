from __future__ import annotations

from datetime import datetime, timezone

from pypdf import PdfWriter

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.mapping import ColumnValue, MappingPlan
from certificate_automation.preview import PreviewService
from certificate_automation.template import inspect_template
from fixtures import docx_factory


class PdfConverter:
    def __init__(self):
        self.calls = 0

    def convert(self, _source, destination):
        self.calls += 1
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=100)
        with destination.open("wb") as stream:
            writer.write(stream)


def _dataset():
    return TabularDataset(
        (Column("name", "Name"),),
        (DataRow("row-1", 2, {"name": "Li Ming"}),),
        SourceSnapshot("manual", "Manual", None, "d" * 64, datetime.now(timezone.utc)),
    )


def test_preview_is_verified_cached_and_replaced_for_new_revision(tmp_path, docx_factory):
    converter = PdfConverter()
    service = PreviewService(converter, tmp_path / "previews")
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    plan = MappingPlan({"FULL_NAME": ColumnValue("name")})
    dataset = _dataset()

    first = service.generate(dataset, "row-1", template, plan)
    cached = service.generate(dataset, "row-1", template, plan)
    changed = dataset.with_cell("row-1", "name", "Changed")
    replacement = service.generate(changed, "row-1", template, plan)

    assert first == cached
    assert converter.calls == 2
    assert replacement.dataset_revision == changed.revision
    assert replacement.pdf_path.is_file()
    assert not first.pdf_path.exists()
