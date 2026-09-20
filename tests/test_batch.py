from __future__ import annotations

import json

import pytest
from pypdf import PdfWriter

from certificate_automation.batch import (
    BatchGenerationError,
    BatchGenerator,
    BatchRequest,
    CancellationToken,
)
from certificate_automation.domain import BatchState
from certificate_automation.mapping import suggest_mappings
from certificate_automation.template import inspect_template
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
