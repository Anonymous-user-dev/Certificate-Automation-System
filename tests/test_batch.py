from __future__ import annotations

import json
import stat
from pathlib import Path
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
from certificate_automation.approval import ApprovalInput, ApprovalService
from certificate_automation.integrity import IntegrityService
from certificate_automation.domain import BatchState
from certificate_automation.history import DuplicatePolicy, HistoryIndex, HistoryStatus, PublishedBatch
from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.mapping import ColumnValue, MappingPlan, suggest_mappings
from certificate_automation.output_options import OutputOptions
from certificate_automation.platform_report import PlatformReport
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
        platform_inspector=lambda path: PlatformReport.from_facts(path, filesystem="NTFS", fixed=True, cloud=False, unc=False),
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


def _typed_request(tmp_path, docx_factory, *, approved=True, **selected):
    from decimal import Decimal
    from certificate_automation.print_readiness import PrintSettings
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
        PrintSettings(Decimal("612"), Decimal("792"), "portrait")
        if selected.get("combined_pdf", True) else None,
    )
    plan = MappingPlan({"FULL_NAME": ColumnValue("full_name")})
    if not approved:
        return BatchRequest(dataset, template, plan, outputs, "zh_CN")
    inputs = ApprovalInput(
        1, dataset.revision, dataset.canonical_sha256(), dataset.source.sha256,
        template.sha256, plan.to_json(), {"reviewed": True}, ("preview",), (),
        None, outputs.to_json(),
        outputs.print_settings.to_json() if outputs.print_settings is not None else {},
        True, "FakeConverter", "zh_CN", len(outputs.row_ids),
        0, {"docx": len(outputs.row_ids) if outputs.docx else 0,
            "pdf": len(outputs.row_ids) if outputs.individual_pdf else 0,
            "combined": int(outputs.combined_pdf)},
        len(outputs.row_ids), str(destination.resolve()), "pending", template.path.name,
    )
    approval = ApprovalService.freeze(inputs, "Preparer")
    return BatchRequest(dataset, template, plan, outputs, "zh_CN",
                        approval_input=inputs, approval=approval,
                        approval_digest=approval.snapshot.digest)


def test_typed_generation_requires_verified_workflow_approval(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory, approved=False)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert caught.value.code == "approval.required"
    assert not list(request.destination.glob(".certificate-incomplete-*"))


def test_typed_generation_rejects_missing_print_settings_before_staging(tmp_path, docx_factory):
    from dataclasses import replace
    basic = _typed_request(tmp_path, docx_factory)
    object.__setattr__(basic.outputs, "print_settings", None)
    frozen = replace(basic.approval_input, outputs=basic.outputs.to_json(), print_settings={})
    approval = ApprovalService.freeze(frozen, "Preparer")
    request = replace(basic, approval_input=frozen, approval=approval,
                      approval_digest=approval.snapshot.digest)

    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)

    assert caught.value.code == "output.print_settings_required"
    assert not list(request.destination.glob(".certificate-incomplete-*"))


def test_official_manifest_and_audit_record_prior_revision_lineage(tmp_path, docx_factory):
    basic = _typed_request(tmp_path, docx_factory)
    request = BatchRequest(
        basic.dataset, basic.template, basic.mappings, basic.outputs, basic.locale,
        approval_input=basic.approval_input, approval=basic.approval,
        approval_digest=basic.approval_digest,
        lineage=("Awards-revision-1",),
    )

    result = _generator(FakeConverter()).generate(request)
    manifest = json.loads((result.output_dir / "manifest.json").read_text("utf-8"))
    html = (result.output_dir / "batch_summary.html").read_text("utf-8")

    assert manifest["lineage"] == ["Awards-revision-1"]
    assert "Awards-revision-1" in html
    assert IntegrityService().verify_revision(result.output_dir).valid


def test_typed_generation_rejects_request_changed_after_approval(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)
    changed = OutputOptions(True, False, False, request.destination, "Awards", request.outputs.row_ids)
    tampered = BatchRequest(
        request.dataset, request.template, request.mappings, changed, request.locale,
        approval_input=request.approval_input, approval=request.approval,
        approval_digest=request.approval_digest,
    )
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(tampered)
    assert caught.value.code == "approval.stale"


@pytest.mark.parametrize("keep_individual_pdfs", (False, True))
def test_typed_generation_records_separator_positions_and_print_settings(tmp_path, docx_factory, keep_individual_pdfs):
    from dataclasses import replace
    from decimal import Decimal
    from certificate_automation.print_readiness import PrintReadinessService, PrintSettings
    from pypdf import PdfReader

    basic = _typed_request(tmp_path, docx_factory, individual_pdf=keep_individual_pdfs)
    settings = PrintSettings(Decimal("612"), Decimal("792"), "portrait", 1)
    outputs = replace(basic.outputs, print_settings=settings)
    frozen = replace(
        basic.approval_input, outputs=outputs.to_json(), print_settings=settings.to_json(),
        output_counts={"docx": 0, "pdf": 2 if keep_individual_pdfs else 0,
                       "combined": 1, "separator": 1},
        expected_pages=3,
    )
    approval = ApprovalService.freeze(frozen, "Preparer")
    request = replace(basic, outputs=outputs, approval_input=frozen, approval=approval,
                      approval_digest=approval.snapshot.digest)

    result = _generator(FakeConverter()).generate(request)
    manifest = json.loads((result.output_dir / "manifest.json").read_text("utf-8"))

    assert manifest["combined_pdf"]["separator_positions"] == [2]
    assert manifest["combined_pdf"]["source_page_counts"] == [1, 1]
    assert len(PdfReader(result.combined_pdf_path).pages) == 3
    assert len(list(result.output_dir.glob("*.pdf"))) == (3 if keep_individual_pdfs else 1)
    assert PrintReadinessService().verify(result.output_dir).ready


def test_typed_generation_blocks_publication_when_pdf_differs_from_approved_page_size(tmp_path, docx_factory):
    from dataclasses import replace
    from decimal import Decimal
    from certificate_automation.print_readiness import PrintSettings

    class WrongSizeConverter(FakeConverter):
        def convert(self, docx_path, pdf_path, on_attempt=None):
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=792)
            with pdf_path.open("wb") as output:
                writer.write(output)
            writer.close()

    basic = _typed_request(tmp_path, docx_factory, individual_pdf=True)
    settings = PrintSettings(Decimal("612"), Decimal("792"), "portrait")
    outputs = replace(basic.outputs, print_settings=settings)
    frozen = replace(basic.approval_input, outputs=outputs.to_json(),
                     print_settings=settings.to_json())
    approval = ApprovalService.freeze(frozen, "Preparer")
    request = replace(basic, outputs=outputs, approval_input=frozen, approval=approval,
                      approval_digest=approval.snapshot.digest)

    with pytest.raises(BatchGenerationError) as caught:
        _generator(WrongSizeConverter()).generate(request)

    assert caught.value.code == "print.not_ready"
    assert not list(outputs.destination.glob("Awards-revision-*"))


def test_typed_generation_rejects_changed_source_file_before_staging(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)
    source = tmp_path / "recipients.csv"
    source.write_text("name\nAna\n", encoding="utf-8")
    from dataclasses import replace
    changed_source = replace(request.dataset.source, path=source, sha256=sha256(source.read_bytes()).hexdigest())
    dataset = replace(request.dataset, source=changed_source)
    frozen = replace(request.approval_input, source_sha256=changed_source.sha256,
                     dataset_sha256=dataset.canonical_sha256())
    approval = ApprovalService.freeze(frozen, "Preparer")
    source.write_text("name\nChanged\n", encoding="utf-8")
    tampered = BatchRequest(
        dataset, request.template, request.mappings, request.outputs, request.locale,
        approval_input=frozen, approval=approval,
        approval_digest=approval.snapshot.digest,
    )
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(tampered)
    assert caught.value.code == "approval.source_changed"


def test_typed_generation_rejects_non_authoritative_destination_before_staging(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)
    generator = BatchGenerator(
        FakeConverter(),
        platform_inspector=lambda path: PlatformReport.from_facts(path, filesystem="exFAT", fixed=False, cloud=False, unc=False),
    )
    with pytest.raises(BatchGenerationError) as caught:
        generator.generate(request)
    assert caught.value.code == "output.authoritative_destination_required"
    assert not list(request.destination.glob(".certificate-incomplete-*"))


def test_typed_publication_creates_verified_immutable_revisions(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)
    generator = _generator(FakeConverter())
    first = generator.generate(request)
    second = generator.generate(request)
    assert first.output_dir.name == "Awards-revision-1"
    assert second.output_dir.name == "Awards-revision-2"
    assert first.revision_number == 1
    assert second.revision_number == 2
    assert IntegrityService().verify_revision(first.output_dir).valid
    assert IntegrityService().verify_revision(second.output_dir).valid
    assert json.loads((first.output_dir / "batch_journal.json").read_text("utf-8"))["state"] == "published"


def test_published_batch_is_indexed_only_after_publication(tmp_path, docx_factory):
    class Protector:
        def protect(self, value, *, purpose):
            return value[::-1]
        def unprotect(self, value, *, purpose):
            return value[::-1]
    basic = _typed_request(tmp_path, docx_factory)
    history = HistoryIndex(tmp_path / "history.sqlite", Protector())
    history.record(PublishedBatch("seed", 1, datetime.now(timezone.utc), tmp_path / "seed"), ("Someone Else",))
    policy = DuplicatePolicy(None, ("full_name",), True)
    request = BatchRequest(
        basic.dataset, basic.template, basic.mappings, basic.outputs, basic.locale,
        duplicate_policy=policy, history_index=history,
        approval_input=basic.approval_input, approval=basic.approval,
        approval_digest=basic.approval_digest,
    )
    result = _generator(FakeConverter()).generate(request)
    assert result.history_indexed is True
    assert history.check(("Ana García",)).status is HistoryStatus.MATCH


def test_history_index_write_failure_keeps_verified_published_bytes(tmp_path, docx_factory, monkeypatch):
    class Protector:
        def protect(self, value, *, purpose):
            return value[::-1]
        def unprotect(self, value, *, purpose):
            return value[::-1]
    basic = _typed_request(tmp_path, docx_factory)
    history = HistoryIndex(tmp_path / "history.sqlite", Protector())
    history.record(PublishedBatch("seed", 1, datetime.now(timezone.utc), tmp_path / "seed"), ("Someone Else",))
    def fail_index(*args):
        raise PermissionError("history database locked")
    monkeypatch.setattr(history, "record_batch", fail_index)
    request = BatchRequest(
        basic.dataset, basic.template, basic.mappings, basic.outputs, basic.locale,
        duplicate_policy=DuplicatePolicy(None, ("full_name",), True), history_index=history,
        approval_input=basic.approval_input, approval=basic.approval,
        approval_digest=basic.approval_digest,
    )
    result = _generator(FakeConverter()).generate(request)
    assert result.state is BatchState.PUBLISHED
    assert result.history_indexed is False
    assert any(issue.code == "history.record_failed" for issue in result.issues)
    assert IntegrityService().verify_revision(result.output_dir).valid
    assert not (result.combined_pdf_path.stat().st_mode & stat.S_IWUSR)


def test_failed_published_journal_update_rolls_complete_folder_back_to_recovery(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal, JournalError, JournalState
    request = _typed_request(tmp_path, docx_factory)
    original = BatchJournal.transition
    def fail_published(self, state, **facts):
        if state is JournalState.PUBLISHED:
            raise JournalError("journal.write_failed")
        return original(self, state, **facts)
    monkeypatch.setattr(BatchJournal, "transition", fail_published)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert not list(request.destination.glob("Awards-revision-*"))
    assert caught.value.diagnostic_path.is_file()
    assert json.loads((caught.value.diagnostic_path.parent / "batch_journal.json").read_text("utf-8"))["state"] == "ready_to_publish"


def test_journal_write_error_after_published_record_keeps_verified_revision(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal, JournalError, JournalState
    request = _typed_request(tmp_path, docx_factory)
    original = BatchJournal.transition
    def write_then_fail(self, state, **facts):
        original(self, state, **facts)
        if state is JournalState.PUBLISHED:
            raise JournalError("journal.write_failed")
    monkeypatch.setattr(BatchJournal, "transition", write_then_fail)
    result = _generator(FakeConverter()).generate(request)
    assert result.state is BatchState.PUBLISHED
    assert IntegrityService().verify_revision(result.output_dir).valid
    assert not list(request.destination.glob(".certificate-incomplete-*"))
    assert any(issue.code == "journal.durability_uncertain" for issue in result.issues)


def test_failed_final_integrity_and_failed_rollback_remain_visible_to_recovery(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.integrity import IntegrityReport
    from certificate_automation.recovery import RecoveryService
    request = _typed_request(tmp_path, docx_factory)
    original_verify = IntegrityService.verify_revision
    original_replace = __import__("os").replace

    def fail_final_verification(self, path, **kwargs):
        if Path(path).name == "Awards-revision-1":
            return IntegrityReport(False, ("integrity.artifact_changed",))
        return original_verify(self, path, **kwargs)

    def fail_rollback(source, destination):
        if Path(source).name == "Awards-revision-1" and Path(destination).name.startswith(".certificate-incomplete-"):
            raise PermissionError("rollback locked")
        return original_replace(source, destination)

    def fail_after_rename(event):
        if event.phase == "publication":
            raise OSError("post-publication I/O fault")

    monkeypatch.setattr(IntegrityService, "verify_revision", fail_final_verification)
    monkeypatch.setattr("certificate_automation.batch.os.replace", fail_rollback)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request, progress=fail_after_rename)
    stranded = request.destination / "Awards-revision-1"
    assert stranded.is_dir()
    assert caught.value.diagnostic_path is not None
    assert caught.value.diagnostic_path.is_file()
    assert caught.value.code == "output.publication_ambiguous"
    assert any(record.path == stranded for record in RecoveryService().find_incomplete(request.destination))
    assert not IntegrityService().verify_revision(stranded).valid


def test_recovery_finds_stranded_published_folder_when_marker_write_also_fails(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal, JournalError
    from certificate_automation.integrity import IntegrityReport
    from certificate_automation.recovery import RecoveryService
    request = _typed_request(tmp_path, docx_factory)
    original_verify = IntegrityService.verify_revision
    original_replace = __import__("os").replace
    failing = True

    def transient_integrity_failure(self, path, **kwargs):
        if failing and Path(path).name == "Awards-revision-1":
            return IntegrityReport(False, ("integrity.transient_failure",))
        return original_verify(self, path, **kwargs)

    def fail_rollback(source, destination):
        if Path(source).name == "Awards-revision-1" and Path(destination).name.startswith(".certificate-incomplete-"):
            raise PermissionError("locked")
        return original_replace(source, destination)

    def fail_marker(*args):
        raise JournalError("journal.recovery_marker_failed")

    def fail_after_rename(event):
        if event.phase == "publication":
            raise OSError("transient verification fault")

    monkeypatch.setattr(IntegrityService, "verify_revision", transient_integrity_failure)
    monkeypatch.setattr("certificate_automation.batch.os.replace", fail_rollback)
    monkeypatch.setattr(BatchJournal, "mark_stranded", fail_marker)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request, progress=fail_after_rename)
    failing = False
    stranded = request.destination / "Awards-revision-1"
    assert IntegrityService().verify_revision(stranded).valid
    assert caught.value.code == "output.publication_ambiguous"
    assert caught.value.diagnostic_path.is_file()
    assert any(record.path == stranded for record in RecoveryService().find_incomplete(request.destination))


def test_successful_published_revision_is_not_offered_as_incomplete_recovery(tmp_path, docx_factory):
    from certificate_automation.recovery import RecoveryService
    request = _typed_request(tmp_path, docx_factory)
    result = _generator(FakeConverter()).generate(request)
    assert RecoveryService().find_incomplete(request.destination) == ()
    assert result.output_dir.is_dir()


def test_publication_intent_write_failure_blocks_final_rename(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal, JournalError
    request = _typed_request(tmp_path, docx_factory)
    def fail_intent(*args):
        raise JournalError("journal.publication_intent_failed")
    monkeypatch.setattr(BatchJournal, "create_publish_intent", fail_intent)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert not list(request.destination.glob("Awards-revision-*"))
    assert caught.value.diagnostic_path.is_file()


def test_unremovable_intent_keeps_published_folder_visible_to_recovery(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal, JournalError
    from certificate_automation.recovery import RecoveryService
    request = _typed_request(tmp_path, docx_factory)
    def fail_clear(*args):
        raise JournalError("journal.publication_intent_clear_failed")
    monkeypatch.setattr(BatchJournal, "clear_publish_intent", fail_clear)
    result = _generator(FakeConverter()).generate(request)
    assert result.state is BatchState.PUBLISHED
    assert any(issue.code == "journal.durability_uncertain" for issue in result.issues)
    assert any(record.path == result.output_dir for record in RecoveryService().find_incomplete(request.destination))


@pytest.mark.parametrize("boundary", ["created", "rendering", "verifying", "ready_to_publish", "published"])
def test_interruption_at_each_journal_boundary_never_publishes_partial_batch(tmp_path, docx_factory, monkeypatch, boundary):
    from certificate_automation.batch_journal import BatchJournal, JournalError, JournalState
    request = _typed_request(tmp_path, docx_factory)
    if boundary == "created":
        original_create = BatchJournal.create
        def create_then_fail(staging, summary):
            original_create(staging, summary)
            raise JournalError("journal.write_failed")
        monkeypatch.setattr(BatchJournal, "create", create_then_fail)
    else:
        original_transition = BatchJournal.transition
        def fail_before_write(self, state, **facts):
            if state.value == boundary:
                raise JournalError("journal.write_failed")
            return original_transition(self, state, **facts)
        monkeypatch.setattr(BatchJournal, "transition", fail_before_write)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert not list(request.destination.glob("Awards-revision-*"))
    assert caught.value.diagnostic_path.is_file()


def test_partial_converter_output_is_only_in_recoverable_staging(tmp_path, docx_factory):
    request = _typed_request(tmp_path, docx_factory)
    class PartialConverter(FakeConverter):
        def convert(self, docx_path, pdf_path, on_attempt=None):
            pdf_path.write_bytes(b"%PDF incomplete")
            raise PermissionError("locked by another process")
    with pytest.raises(BatchGenerationError) as caught:
        _generator(PartialConverter()).generate(request)
    assert not list(request.destination.glob("Awards-revision-*"))
    assert caught.value.diagnostic_path.is_file()


def test_disk_full_while_writing_manifest_retains_incomplete_journal(tmp_path, docx_factory, monkeypatch):
    request = _typed_request(tmp_path, docx_factory)
    def disk_full(*args):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr("certificate_automation.batch.write_manifest", disk_full)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert not list(request.destination.glob("Awards-revision-*"))
    assert (caught.value.diagnostic_path.parent / "batch_journal.json").is_file()


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
        approval_input=basic.approval_input, approval=basic.approval,
        approval_digest=basic.approval_digest,
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
        approval_input=basic.approval_input, approval=basic.approval,
        approval_digest=basic.approval_digest,
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
    assert manifest["schema_version"] == 3
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


@pytest.mark.parametrize("reverse", [False, True])
def test_stale_intent_for_same_target_cannot_hide_current_publication(
    tmp_path, docx_factory, monkeypatch, reverse,
):
    from certificate_automation.batch_journal import BatchJournal, JournalError
    from certificate_automation.recovery import RecoveryService

    request = _typed_request(tmp_path, docx_factory)
    def retain_intent(_path):
        raise JournalError("journal.publication_intent_clear_failed")
    monkeypatch.setattr(BatchJournal, "clear_publish_intent", retain_intent)
    result = _generator(FakeConverter()).generate(request)
    stale = BatchJournal.create_publish_intent(
        request.destination, "stale-batch", result.output_dir.name,
        "b" * 64, result.revision_number,
    )

    original_glob = Path.glob
    def ordered_glob(path, pattern):
        matches = list(original_glob(path, pattern))
        if pattern.startswith(".certificate-publish-intent-"):
            matches.sort(key=lambda item: item.name, reverse=reverse)
        return iter(matches)
    monkeypatch.setattr(Path, "glob", ordered_glob)

    records = RecoveryService().find_incomplete(request.destination)
    assert any(
        record.path == result.output_dir
        and record.batch_id == "20260920-120000-abcd1234"
        for record in records
    )
    assert any(record.diagnostic_path == stale for record in records)


def test_pending_intent_reserves_revision_number(tmp_path, docx_factory):
    from certificate_automation.batch_journal import BatchJournal

    request = _typed_request(tmp_path, docx_factory)
    BatchJournal.create_publish_intent(
        request.destination, "pending-batch", "Awards-revision-1", "a" * 64, 1,
    )
    result = _generator(FakeConverter()).generate(request)

    assert result.revision_number == 2


def test_unreadable_publish_intent_blocks_revision_allocation_before_staging(tmp_path, docx_factory, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal
    request = _typed_request(tmp_path, docx_factory)
    intent = BatchJournal.create_publish_intent(
        request.destination, "batch-locked", "Awards-revision-1", "a" * 64, 1,
    )
    original_read_text = Path.read_text

    def denied(self, *args, **kwargs):
        if self == intent:
            raise PermissionError("intent locked")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(BatchGenerationError) as caught:
        _generator(FakeConverter()).generate(request)
    assert caught.value.code == "output.publication_intent_unavailable"
    assert not list(request.destination.glob(".certificate-incomplete-*"))
    assert intent.exists()


def test_clear_publish_intent_requires_matching_batch_ownership(tmp_path):
    from certificate_automation.batch_journal import BatchJournal, JournalError

    own = BatchJournal.create_publish_intent(
        tmp_path, "batch-owned", "Awards-revision-1", "a" * 64, 1,
    )
    unrelated = BatchJournal.create_publish_intent(
        tmp_path, "batch-other", "Other-revision-2", "b" * 64, 2,
    )
    with pytest.raises(JournalError, match="journal.invalid_publication_intent"):
        BatchJournal.clear_publish_intent(own, "batch-other")

    assert own.is_file()
    original_payload = json.loads(own.read_text("utf-8"))
    tampered_payload = dict(original_payload, batch_id="batch-other")
    own.write_text(json.dumps(tampered_payload), encoding="utf-8")
    with pytest.raises(JournalError, match="journal.invalid_publication_intent"):
        BatchJournal.clear_publish_intent(own, "batch-owned")
    own.write_text(json.dumps(original_payload), encoding="utf-8")
    BatchJournal.clear_publish_intent(own, "batch-owned")
    assert not own.exists()
    assert unrelated.is_file()
