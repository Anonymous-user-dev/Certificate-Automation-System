from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from pypdf import PdfWriter

from certificate_automation.batch import (
    BatchGenerationError,
    BatchGenerator,
    BatchRequest,
    CancellationToken,
)
from certificate_automation.domain import BatchState
from certificate_automation.history import DuplicatePolicy, HistoryIndex, HistoryStatus, PublishedBatch
from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.mapping import ColumnValue, MappingPlan, suggest_mappings
from certificate_automation.output_options import OutputOptions
from certificate_automation.pdf_merge import CombinedPdfRecord
from certificate_automation.template import inspect_template
from certificate_automation.validation import validate_preflight
from certificate_automation.word import Availability
from certificate_automation.workbook import load_workbook_data
from fixtures import docx_factory, xlsx_factory


class FakeConverter:
    def __init__(self, fail_on_call=None):
        self.fail_on_call = fail_on_call
        self.calls = 0

    def is_available(self):
        return Availability(True, "Fake PDF converter is available.")

    def convert(self, docx_path, pdf_path, on_attempt=None):
        self.calls += 1
        if on_attempt is not None:
            on_attempt(1, 1)
        if self.calls == self.fail_on_call:
            raise RuntimeError("simulated converter failure for private recipient data")
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with pdf_path.open("wb") as output:
            writer.write(output)


@pytest.fixture
def batch_request(tmp_path, xlsx_factory, docx_factory):
    workbook_path = xlsx_factory(
        [
            ["Full Name", "Award", "Date"],
            ["Ana García", "Gold", "2026-09-20"],
            ["李明", "Excellence", "2026-09-20"],
        ]
    )
    template_path = docx_factory(
        paragraph_runs=[
            ["Certificate for ", "{{FULL_", "NAME}}"],
            ["Award: {{AWARD}}"],
            ["Date: {{DATE}}"],
        ]
    )
    workbook = load_workbook_data(workbook_path, "Students")
    template = inspect_template(template_path)
    mappings = suggest_mappings(workbook.headers, template.names)
    destination = tmp_path / "batches"
    destination.mkdir()
    return BatchRequest(workbook, template, mappings, destination)


def _generator(converter):
    return BatchGenerator(
        converter=converter,
        batch_id_factory=lambda: "20260920-120000-abcd1234",
    )


def test_success_publishes_complete_timestamped_batch(batch_request):
    result = _generator(FakeConverter()).generate(batch_request)

    assert result.state is BatchState.PUBLISHED
    assert result.output_dir.name == "Certificate Batch 2026-09-20 120000 abcd1234"
    assert len(list(result.output_dir.glob("*.docx"))) == 2
    assert len(list(result.output_dir.glob("*.pdf"))) == 2
    assert (result.output_dir / "manifest.json").exists()
    assert (result.output_dir / "batch_summary.html").exists()
    support_log = (result.output_dir / "support.log").read_text("utf-8")
    assert "status=verified" in support_log
    assert "Ana García" not in support_log
    assert "李明" not in support_log
    assert not any(batch_request.destination.glob(".certificate-staging-*"))


def test_published_manifest_has_verified_counts_and_hashes(batch_request):
    result = _generator(FakeConverter()).generate(batch_request)

    manifest = json.loads((result.output_dir / "manifest.json").read_text("utf-8"))

    assert manifest["status"] == "verified"
    assert manifest["counts"] == {
        "recipients": 2,
        "docx": 2,
        "pdf": 2,
        "warnings": 0,
    }
    assert all(output["docx_sha256"] for output in manifest["outputs"])
    assert all(output["pdf_sha256"] for output in manifest["outputs"])


def test_conversion_failure_never_publishes_partial_batch(batch_request):
    with pytest.raises(BatchGenerationError) as error:
        _generator(FakeConverter(fail_on_call=2)).generate(batch_request)

    assert not list(batch_request.destination.glob("Certificate Batch *"))
    assert error.value.diagnostic_path is not None
    assert error.value.diagnostic_path.exists()
    diagnostic = json.loads(error.value.diagnostic_path.read_text("utf-8"))
    assert diagnostic["status"] == "incomplete"
    assert "private recipient data" not in json.dumps(diagnostic)
    assert not list(error.value.diagnostic_path.parent.glob("manifest.json"))


def test_cancellation_occurs_between_recipients(batch_request):
    cancellation = CancellationToken()

    def cancelling_progress(event):
        if event.phase == "docx" and event.current == 1:
            cancellation.request()

    result = _generator(FakeConverter()).generate(
        batch_request,
        progress=cancelling_progress,
        cancellation=cancellation,
    )

    assert result.state is BatchState.CANCELLED
    assert result.output_dir is None
    assert not list(batch_request.destination.glob("Certificate Batch *"))
    assert not list(batch_request.destination.glob(".certificate-*"))


def test_progress_reports_all_transaction_phases(batch_request):
    events = []

    _generator(FakeConverter()).generate(batch_request, progress=events.append)

    phases = [event.phase for event in events]
    assert phases[0] == "preflight"
    assert phases.count("docx") == 2
    assert phases.count("pdf") == 2
    assert "verification" in phases
    assert phases[-1] == "publication"


def test_existing_final_batch_is_never_overwritten(batch_request):
    generator = _generator(FakeConverter())
    first = generator.generate(batch_request)
    sentinel = first.output_dir / "do-not-overwrite.txt"
    sentinel.write_text("original", encoding="utf-8")

    with pytest.raises(BatchGenerationError) as error:
        generator.generate(batch_request)

    assert error.value.code == "batch_already_exists"
    assert sentinel.read_text("utf-8") == "original"


def test_existing_incomplete_batch_is_never_overwritten(batch_request):
    incomplete = (
        batch_request.destination
        / ".certificate-incomplete-20260920-120000-abcd1234"
    )
    incomplete.mkdir()
    sentinel = incomplete / "diagnostic.json"
    sentinel.write_text('{"original": true}', encoding="utf-8")

    with pytest.raises(BatchGenerationError) as error:
        _generator(FakeConverter(fail_on_call=1)).generate(batch_request)

    assert error.value.code == "batch_already_exists"
    assert sentinel.read_text("utf-8") == '{"original": true}'


def test_unavailable_converter_blocks_before_staging(batch_request):
    class UnavailableConverter(FakeConverter):
        def is_available(self):
            return Availability(False, "Microsoft Word is not installed.")

    with pytest.raises(BatchGenerationError) as error:
        _generator(UnavailableConverter()).generate(batch_request)

    assert error.value.code == "pdf_converter_unavailable"
    assert not list(batch_request.destination.glob(".certificate-*"))


def test_original_workbook_and_template_are_never_modified(batch_request):
    workbook_before = batch_request.workbook.path.read_bytes()
    template_before = batch_request.template.path.read_bytes()

    _generator(FakeConverter()).generate(batch_request)

    assert batch_request.workbook.path.read_bytes() == workbook_before
    assert batch_request.template.path.read_bytes() == template_before


def _typed_request(tmp_path, docx_factory, **selected):
    template_path = docx_factory(paragraph_runs=[["Certificate for {{FULL_NAME}}"]])
    template = inspect_template(template_path)
    dataset = TabularDataset(
        (Column("full_name", "Full Name"),),
        (
            DataRow("row-1", 2, {"full_name": "Ana García"}),
            DataRow("row-2", 3, {"full_name": "李明"}),
        ),
        SourceSnapshot(
            "manual",
            "Recipients",
            None,
            "d" * 64,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        ),
        revision=4,
        order=("row-2", "row-1"),
    )


    destination = tmp_path / "typed-batches"
    destination.mkdir()
    outputs = OutputOptions(
        selected.get("docx", False),
        selected.get("individual_pdf", False),
        selected.get("combined_pdf", True),
        destination,
        "Awards",
        dataset.order,
    )
    return BatchRequest(
        dataset,
        template,
        MappingPlan({"FULL_NAME": ColumnValue("full_name")}),
        outputs,
        "zh_CN",
    )


def test_typed_generation_rechecks_history_and_requires_current_warning_ack(tmp_path, docx_factory):
    class Protector:
        def protect(self, value, *, purpose):
            return value[::-1]
        def unprotect(self, value, *, purpose):
            return value[::-1]

    basic = _typed_request(tmp_path, docx_factory)
    history = HistoryIndex(tmp_path / "history.sqlite", Protector())
    policy = DuplicatePolicy(None, ("full_name",), True)
    request = BatchRequest(
        basic.dataset, basic.template, basic.mappings, basic.outputs,
        duplicate_policy=policy, history_index=history,
    )
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert caught.value.code == "warnings_not_acknowledged"
    assert history.check(("Ana García",)).status is HistoryStatus.UNAVAILABLE
    assert not list(request.destination.glob("Certificate Batch *"))

    report = validate_preflight(
        basic.dataset, basic.template, basic.mappings, basic.outputs,
        duplicate_policy=policy, history_index=history,
    )
    acknowledged = BatchRequest(
        basic.dataset, basic.template, basic.mappings, basic.outputs,
        duplicate_policy=policy, history_index=history,
        warning_ack_digest=report.warning_digest,
    )
    history.record(PublishedBatch("previous", 1, datetime.now(timezone.utc), tmp_path / "old"),
                   ("Ana García",))
    with pytest.raises(BatchGenerationError) as stale:
        _generator(FakeConverter()).generate(acknowledged)
    assert stale.value.code == "warnings_not_acknowledged"


def test_combined_only_publishes_one_ordered_pdf_and_no_temporary_formats(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)

    result = _generator(FakeConverter()).generate(request)

    assert [path.name for path in result.output_dir.glob("*.pdf")] == ["Awards.pdf"]
    assert result.combined_pdf_path == result.output_dir / "Awards.pdf"
    assert result.combined_pdf_path.is_file()
    assert not list(result.output_dir.glob("*.docx"))
    manifest = json.loads((result.output_dir / "manifest.json").read_text("utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["ordered_row_ids"] == ["row-2", "row-1"]
    assert manifest["combined_pdf"]["source_order"] == ["row-2", "row-1"]
    assert "recipient_values" not in json.dumps(manifest)


def test_docx_only_does_not_require_pdf_converter(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory, docx=True, combined_pdf=False)

    class UnavailableConverter(FakeConverter):
        def is_available(self):
            return Availability(False, "Word unavailable")

    result = _generator(UnavailableConverter()).generate(request)

    assert len(list(result.output_dir.glob("*.docx"))) == 2
    assert not list(result.output_dir.glob("*.pdf"))


@pytest.mark.parametrize(
    ("selected", "docx_count", "pdf_count"),
    [
        ({"individual_pdf": True, "combined_pdf": False}, 0, 2),
        ({"docx": True, "individual_pdf": True, "combined_pdf": True}, 2, 3),
    ],
)
def test_selected_formats_are_the_only_published_recipient_files(
    tmp_path,
    docx_factory,
    selected,
    docx_count,
    pdf_count,
):
    request = _typed_request(tmp_path, docx_factory, **selected)

    result = _generator(FakeConverter()).generate(request)

    assert len(list(result.output_dir.glob("*.docx"))) == docx_count
    assert len(list(result.output_dir.glob("*.pdf"))) == pdf_count


def test_combined_page_count_mismatch_blocks_publication(tmp_path, docx_factory, monkeypatch):
    request = _typed_request(tmp_path, docx_factory)

    def corrupt_merge(_inputs, destination):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with destination.open("wb") as output:
            writer.write(output)
        return CombinedPdfRecord(
            destination,
            1,
            sha256(destination.read_bytes()).hexdigest(),
            tuple(_inputs),
        )

    monkeypatch.setattr("certificate_automation.batch.merge_verified_pdfs", corrupt_merge)

    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)

    assert caught.value.code == "output.combined_pdf_verification_failed"
    assert not list(request.destination.glob("Certificate Batch *"))


def test_cancel_between_merge_and_publish_removes_staging(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)
    cancellation = CancellationToken()

    def cancel_after_merge(event):
        if event.phase == "combined_pdf":
            cancellation.request()

    result = _generator(FakeConverter()).generate(
        request,
        progress=cancel_after_merge,
        cancellation=cancellation,
    )

    assert result.state is BatchState.CANCELLED
    assert not list(request.destination.glob(".certificate-staging-*"))
    assert not list(request.destination.glob("Certificate Batch *"))


def test_template_change_during_generation_blocks_publication(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory, docx=True, combined_pdf=False)

    def change_template(event):
        if event.phase == "docx" and event.current == 1:
            request.template.path.write_bytes(b"changed during generation")

    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request, progress=change_template)

    assert caught.value.code == "template.changed_during_generation"
    assert not list(request.destination.glob("Certificate Batch *"))
