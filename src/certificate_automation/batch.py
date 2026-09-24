"""All-or-nothing certificate batch generation."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
from threading import Event
from typing import Callable
from uuid import uuid4

from certificate_automation import __version__
from certificate_automation.approval import ApprovalInput, ApprovalService, WorkflowApproval
from certificate_automation.audit import (
    AuditContext,
    CombinedAuditOutput,
    AuditOutput,
    sha256_file,
    pdf_page_fingerprints,
    write_manifest,
    write_support_log,
    write_summary,
)
from certificate_automation.batch_journal import BatchJournal, JournalState, read_publish_intents
from certificate_automation.dataset import TabularDataset
from certificate_automation.domain import BatchResult, BatchState, Issue, Severity
from certificate_automation.history import DuplicatePolicy, HistoryEntry, HistoryIndex, PublishedBatch
from certificate_automation.integrity import IntegrityService
from certificate_automation.filenames import safe_stem
from certificate_automation.mapping import MappingPlan, MappingSelection, evaluate_plan
from certificate_automation.output_options import OutputOptions
from certificate_automation.platform_report import PlatformReport
from certificate_automation.pdf_merge import (
    CombinedPdfError,
    CombinedPdfRecord,
    merge_verified_pdfs,
)
from certificate_automation.print_readiness import PrintReadinessService
from certificate_automation.template import TemplateInspection, render_template
from certificate_automation.validation import validate_preflight
from certificate_automation.verification import (
    ArtifactVerificationError,
    pdf_page_count,
    verify_docx,
    verify_pdf,
    verify_pdf_page_count,
)
from certificate_automation.word import PdfConversionError, PdfConverter
from certificate_automation.workbook import WorkbookData


ProgressCallback = Callable[["ProgressEvent"], None]


@contextmanager
def _destination_lock(destination: Path):
    """Hold one OS-level lock across revision selection and publication."""

    destination.mkdir(parents=True, exist_ok=True)
    lock_path = destination / ".official-batch.lock"
    if lock_path.is_symlink():
        raise BatchGenerationError("Unsafe destination lock.", code="output.destination_busy")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError) as error:
            raise BatchGenerationError("The output folder is busy.", code="output.destination_busy") from error
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@dataclass(frozen=True, slots=True, init=False)
class BatchRequest:
    dataset: WorkbookData | TabularDataset
    template: TemplateInspection
    mappings: MappingSelection | MappingPlan
    outputs: Path | OutputOptions
    locale: str
    duplicate_policy: DuplicatePolicy
    history_index: HistoryIndex | None
    warning_ack_digest: str | None
    approval_input: ApprovalInput | None
    approval: WorkflowApproval | None
    approval_digest: str | None
    revision_number: int | None
    lineage: tuple[str, ...]

    def __init__(
        self,
        dataset: WorkbookData | TabularDataset,
        template: TemplateInspection,
        mappings: MappingSelection | MappingPlan,
        outputs: Path | OutputOptions,
        locale: str = "en",
        *,
        duplicate_policy: DuplicatePolicy | None = None,
        history_index: HistoryIndex | None = None,
        warning_ack_digest: str | None = None,
        approval_input: ApprovalInput | None = None,
        approval: WorkflowApproval | None = None,
        approval_digest: str | None = None,
        revision_number: int | None = None,
        lineage: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "dataset", dataset)
        object.__setattr__(self, "template", template)
        object.__setattr__(self, "mappings", mappings)
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "locale", locale)
        object.__setattr__(self, "duplicate_policy", duplicate_policy or DuplicatePolicy())
        object.__setattr__(self, "history_index", history_index)
        object.__setattr__(self, "warning_ack_digest", warning_ack_digest)
        object.__setattr__(self, "approval_input", approval_input)
        object.__setattr__(self, "approval", approval)
        object.__setattr__(self, "approval_digest", approval_digest)
        object.__setattr__(self, "revision_number", revision_number)
        object.__setattr__(self, "lineage", tuple(lineage))

    @property
    def workbook(self) -> WorkbookData | TabularDataset:
        """Compatibility alias while the original generator remains supported."""

        return self.dataset

    @property
    def destination(self) -> Path:
        return (
            self.outputs.destination
            if isinstance(self.outputs, OutputOptions)
            else Path(self.outputs)
        )


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    phase: str
    current: int
    total: int
    message: str
    source_row: int | None = None


class CancellationToken:
    """Thread-safe cancellation request checked only at safe boundaries."""

    def __init__(self) -> None:
        self._event = Event()

    def request(self) -> None:
        self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()


class BatchGenerationError(RuntimeError):
    """Typed failure safe for presentation by the desktop interface."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        diagnostic_path: Path | None = None,
        user_action: str = "Review the diagnostic report and run validation again.",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostic_path = diagnostic_path
        self.user_action = user_action


class BatchGenerator:
    """Generate, verify, audit, and atomically publish a complete batch."""

    def __init__(
        self,
        converter: PdfConverter,
        *,
        clock: Callable[[], datetime] | None = None,
        batch_id_factory: Callable[[], str] | None = None,
        platform_inspector: Callable[[Path], PlatformReport] | None = None,
    ) -> None:
        self._converter = converter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._batch_id_factory = batch_id_factory or self._new_batch_id
        self._platform_inspector = platform_inspector or PlatformReport.inspect_volume

    def generate(
        self,
        request: BatchRequest,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> BatchResult:
        if isinstance(request.dataset, TabularDataset):
            if not isinstance(request.mappings, MappingPlan) or not isinstance(
                request.outputs, OutputOptions
            ):
                raise TypeError("TabularDataset generation requires typed mappings and outputs")
            return self._generate_typed(request, progress, cancellation)
        cancellation = cancellation or CancellationToken()
        started_at = self._clock()
        batch_id = self._batch_id_factory()
        destination = Path(request.destination)
        self._emit(progress, "preflight", 0, 1, "Validating the complete batch.")

        if cancellation.requested:
            return BatchResult(BatchState.CANCELLED)

        report = validate_preflight(
            request.workbook,
            request.template,
            request.mappings,
            destination,
        )
        if not report.ready:
            raise BatchGenerationError(
                "The batch did not pass validation.",
                code="validation_failed",
                user_action="Correct every validation error before generating documents.",
            )

        availability = self._converter.is_available()
        if not availability.available:
            raise BatchGenerationError(
                availability.message,
                code="pdf_converter_unavailable",
                user_action="Install or repair desktop Microsoft Word, then validate again.",
            )

        destination.mkdir(parents=True, exist_ok=True)
        final_directory = destination / self._published_folder_name(batch_id)
        incomplete_directory = destination / f".certificate-incomplete-{batch_id}"
        if final_directory.exists() or incomplete_directory.exists():
            raise BatchGenerationError(
                "A batch with this identifier already exists and was not overwritten.",
                code="batch_already_exists",
                user_action="Start a new generation run to receive a new batch identifier.",
            )

        staging = destination / f".certificate-staging-{batch_id}"
        if staging.exists():
            raise BatchGenerationError(
                "A staging folder with this batch identifier already exists.",
                code="staging_already_exists",
            )
        staging.mkdir()

        artifacts: list[AuditOutput] = []
        total = len(request.workbook.recipients)
        try:
            docx_by_row: dict[int, Path] = {}
            for index, recipient in enumerate(request.workbook.recipients, start=1):
                if cancellation.requested:
                    return self._cancel(staging)
                stem = report.filename_stems[recipient.source_row]
                docx_path = staging / f"{stem}_certificate.docx"
                render_template(
                    request.template.path,
                    docx_path,
                    request.mappings.replacements_for(recipient),
                )
                verify_docx(docx_path, set(request.template.names))
                docx_by_row[recipient.source_row] = docx_path
                self._emit(
                    progress,
                    "docx",
                    index,
                    total,
                    f"Created Word certificate {index} of {total}.",
                    recipient.source_row,
                )

            for index, recipient in enumerate(request.workbook.recipients, start=1):
                if cancellation.requested:
                    return self._cancel(staging)
                docx_path = docx_by_row[recipient.source_row]
                pdf_path = docx_path.with_suffix(".pdf")
                self._converter.convert(docx_path, pdf_path)
                verify_pdf(pdf_path)
                artifacts.append(
                    AuditOutput(recipient.source_row, docx_path, pdf_path)
                )
                self._emit(
                    progress,
                    "pdf",
                    index,
                    total,
                    f"Created PDF certificate {index} of {total}.",
                    recipient.source_row,
                )

            if cancellation.requested:
                return self._cancel(staging)

            self._verify_artifact_set(staging, artifacts, total)
            self._emit(
                progress,
                "verification",
                total,
                total,
                "Verified every Word and PDF certificate.",
            )
            completed_at = self._clock()
            audit_context = AuditContext(
                batch_id=batch_id,
                application_version=__version__,
                started_at=started_at,
                completed_at=completed_at,
                status="verified",
                workbook_path=request.workbook.path,
                template_path=request.template.path,
                worksheet=request.workbook.sheet_name,
                mappings={
                    placeholder: column or "[fixed value]"
                    for placeholder, column in request.mappings.columns.items()
                },
                outputs=tuple(artifacts),
                warnings=tuple(
                    issue
                    for issue in report.issues
                    if issue.severity is Severity.WARNING
                ),
            )
            write_summary(audit_context, staging / "batch_summary.html")
            write_manifest(audit_context, staging / "manifest.json")
            write_support_log(audit_context, staging / "support.log")

            if cancellation.requested:
                return self._cancel(staging)
            if final_directory.exists():
                raise BatchGenerationError(
                    "The final batch folder appeared during generation and was not overwritten.",
                    code="batch_already_exists",
                )
            os.replace(staging, final_directory)
            self._emit(
                progress,
                "publication",
                total,
                total,
                "Published the complete verified batch.",
            )
            return BatchResult(
                BatchState.PUBLISHED,
                output_dir=final_directory,
                generated_count=total,
                issues=report.issues,
            )
        except Exception as error:
            diagnostic_path = self._retain_incomplete(staging, batch_id, error)
            if isinstance(error, BatchGenerationError):
                error.diagnostic_path = diagnostic_path
                raise
            code = (
                error.code
                if isinstance(error, PdfConversionError)
                else "generation_failed"
            )
            user_action = (
                error.user_action
                if isinstance(error, PdfConversionError)
                else "Review the diagnostic report, correct the source files, and try again."
            )
            raise BatchGenerationError(
                "The batch could not be completed safely. No official batch was published.",
                code=code,
                diagnostic_path=diagnostic_path,
                user_action=user_action,
            ) from error

    def _generate_typed(
        self,
        request: BatchRequest,
        progress: ProgressCallback | None,
        cancellation: CancellationToken | None,
    ) -> BatchResult:
        dataset = request.dataset
        plan = request.mappings
        outputs = request.outputs
        assert isinstance(dataset, TabularDataset)
        assert isinstance(plan, MappingPlan)
        assert isinstance(outputs, OutputOptions)

        verification = ApprovalService.verify(request.approval, request.approval_input) if request.approval_input is not None else None
        if verification is None or not verification.valid or request.approval_digest != request.approval.snapshot.digest:
            code = verification.code if verification is not None and not verification.valid else "approval.required"
            raise BatchGenerationError(
                "The frozen project approval is missing or no longer current.",
                code=code,
                user_action="Return to Final approval and approve the current project revision.",
            )
        self._require_source_hash(dataset)

        cancellation = cancellation or CancellationToken()
        started_at = self._clock()
        batch_id = self._batch_id_factory()
        destination = outputs.destination
        total = len(outputs.row_ids)
        self._emit(progress, "preflight", 0, 1, "Validating the complete batch.")
        if cancellation.requested:
            return BatchResult(BatchState.CANCELLED)

        report = validate_preflight(
            dataset, request.template, plan, outputs,
            duplicate_policy=request.duplicate_policy,
            history_index=request.history_index,
        )
        if not report.ready:
            raise BatchGenerationError(
                "The batch did not pass validation.",
                code="validation_failed",
                user_action="Correct every validation error before generating documents.",
            )
        if report.warning_digest and request.warning_ack_digest != report.warning_digest:
            raise BatchGenerationError(
                "The current validation warnings were not acknowledged.",
                code="warnings_not_acknowledged",
                user_action="Review and acknowledge the current warnings before generating.",
            )

        frozen = request.approval_input
        warnings = tuple(sorted(issue.code for issue in report.issues if issue.severity is Severity.WARNING))
        if (
            frozen.dataset_revision != dataset.revision
            or frozen.dataset_sha256 != dataset.canonical_sha256()
            or frozen.source_sha256 != dataset.source.sha256
            or frozen.template_sha256 != report.template_sha256
            or frozen.payload()["mapping"] != plan.to_json()
            or frozen.payload()["outputs"] != outputs.to_json()
            or frozen.payload()["print_settings"] != (
                outputs.print_settings.to_json() if outputs.print_settings is not None else {}
            )
            or frozen.warning_codes != warnings
            or frozen.warning_ack_digest != (report.warning_digest or None)
            or frozen.locale != request.locale
            or frozen.recipient_count != len(outputs.row_ids)
            or frozen.destination != str(outputs.destination.resolve())
            or frozen.output_counts.get("separator", 0) != outputs.separator_count
        ):
            raise BatchGenerationError(
                "The generation request differs from the frozen approval.",
                code="approval.stale",
                user_action="Review and approve the current project revision again.",
            )

        platform = self._platform_inspector(outputs.destination)
        if not platform.authoritative:
            raise BatchGenerationError(
                "Official publication requires a fixed local NTFS destination.",
                code="output.authoritative_destination_required",
                user_action="Choose a fixed local NTFS folder for the official batch.",
            )

        with _destination_lock(outputs.destination):
            return self._generate_typed_locked(
                request, progress, cancellation, started_at, batch_id, report, platform
            )

    def _generate_typed_locked(
        self, request: BatchRequest, progress: ProgressCallback | None,
        cancellation: CancellationToken, started_at: datetime, batch_id: str,
        report, platform: PlatformReport,
    ) -> BatchResult:
        dataset = request.dataset
        plan = request.mappings
        outputs = request.outputs
        assert isinstance(dataset, TabularDataset)
        assert isinstance(plan, MappingPlan)
        assert isinstance(outputs, OutputOptions)
        destination = outputs.destination
        total = len(outputs.row_ids)

        needs_pdf = outputs.individual_pdf or outputs.combined_pdf
        if needs_pdf:
            availability = self._converter.is_available()
            if not availability.available:
                raise BatchGenerationError(
                    availability.message,
                    code="pdf_converter_unavailable",
                    user_action="Install or repair desktop Microsoft Word, then validate again.",
                )

        name = outputs.batch_name if outputs.batch_name else "Certificate Batch"
        stem = safe_stem(name)
        existing = []
        matcher = re.compile(re.escape(stem) + r"-revision-(\d+)$", re.IGNORECASE)
        for candidate in destination.iterdir():
            match = matcher.fullmatch(candidate.name)
            if match:
                existing.append(int(match.group(1)))
        try:
            pending_intents = read_publish_intents(destination)
        except OSError as error:
            raise BatchGenerationError(
                "Publication intent files could not be read; no official batch was started.",
                code="output.publication_intent_unavailable",
            ) from error
        for intent in pending_intents:
            match = matcher.fullmatch(intent.final_name)
            if match and int(match.group(1)) == intent.revision:
                existing.append(intent.revision)
        revision_number = max(existing, default=0) + 1
        if request.revision_number is not None and request.revision_number != revision_number:
            raise BatchGenerationError("The proposed revision is stale.", code="output.revision_changed")
        final_directory = destination / f"{stem}-revision-{revision_number}"
        incomplete_directory = destination / f".certificate-incomplete-{batch_id}"
        if final_directory.exists() or incomplete_directory.exists():
            raise BatchGenerationError(
                "A batch with this identifier already exists and was not overwritten.",
                code="batch_already_exists",
                user_action="Start a new generation run to receive a new batch identifier.",
            )
        staging = incomplete_directory
        if staging.exists():
            raise BatchGenerationError(
                "A staging folder with this batch identifier already exists.",
                code="staging_already_exists",
            )
        staging.mkdir()

        docx_by_row: dict[str, Path] = {}
        pdf_by_row: dict[str, Path] = {}
        page_counts: dict[str, int] = {}
        combined: CombinedPdfRecord | None = None
        intent_path: Path | None = None
        try:
            journal = BatchJournal.create(staging, {
                "batch_id": batch_id, "approval_digest": request.approval_digest,
                "project_revision_digest": request.approval_digest,
                "destination": str(destination), "revision": revision_number,
                "intended_counts": {
                    **dict(request.approval.snapshot.output_counts),
                    "recipients": request.approval.snapshot.recipient_count,
                },
                "approved_row_ids": list(outputs.row_ids),
            })
            journal.transition(JournalState.RENDERING)
            for index, row_id in enumerate(outputs.row_ids, start=1):
                if cancellation.requested:
                    return self._cancel(staging)
                self._require_template_hash(
                    request.template.path,
                    report.template_sha256,
                )
                stem = report.filename_stems[row_id]
                docx_path = staging / f"{stem}.docx"
                render_template(
                    request.template.path,
                    docx_path,
                    evaluate_plan(plan, dataset, row_id),
                )
                verify_docx(docx_path, set(request.template.names))
                docx_by_row[row_id] = docx_path
                self._emit(
                    progress,
                    "docx",
                    index,
                    total,
                    f"Created Word certificate {index} of {total}.",
                    dataset.row(row_id).source_row,
                )

            if needs_pdf:
                for index, row_id in enumerate(outputs.row_ids, start=1):
                    if cancellation.requested:
                        return self._cancel(staging)
                    pdf_path = docx_by_row[row_id].with_suffix(".pdf")
                    self._converter.convert(docx_by_row[row_id], pdf_path)
                    page_counts[row_id] = pdf_page_count(pdf_path)
                    pdf_by_row[row_id] = pdf_path
                    self._emit(
                        progress,
                        "pdf",
                        index,
                        total,
                        f"Created PDF certificate {index} of {total}.",
                        dataset.row(row_id).source_row,
                    )

            if outputs.combined_pdf:
                merge_args = (
                    {"separator_every": outputs.print_settings.separator_every}
                    if outputs.print_settings is not None and outputs.print_settings.separator_every is not None
                    else {}
                )
                combined = merge_verified_pdfs(
                    tuple(pdf_by_row[row_id] for row_id in outputs.row_ids),
                    staging / f"{outputs.batch_name}.pdf", **merge_args,
                )
                expected_pages = sum(page_counts.values()) + outputs.separator_count
                try:
                    verify_pdf_page_count(combined.path, expected_pages)
                except ArtifactVerificationError as error:
                    raise BatchGenerationError(
                        "The combined PDF did not match its verified inputs.",
                        code="output.combined_pdf_verification_failed",
                    ) from error
                if combined.page_count != expected_pages:
                    raise BatchGenerationError(
                        "The combined PDF page count did not match its verified inputs.",
                        code="output.combined_pdf_verification_failed",
                    )
                if outputs.print_settings is not None and request.approval_input.expected_pages != expected_pages:
                    raise BatchGenerationError(
                        "The combined page count differs from the approved print summary.",
                        code="print.page_count_mismatch",
                    )
                self._emit(
                    progress,
                    "combined_pdf",
                    total,
                    total,
                    "Created and verified the combined print PDF.",
                )

            if cancellation.requested:
                return self._cancel(staging)
            self._require_template_hash(
                request.template.path,
                report.template_sha256,
            )
            journal.transition(JournalState.VERIFYING)

            audit_outputs = tuple(
                AuditOutput(
                    dataset.row(row_id).source_row,
                    docx_by_row[row_id] if outputs.docx else None,
                    pdf_by_row.get(row_id) if outputs.individual_pdf else None,
                    row_id,
                )
                for row_id in outputs.row_ids
            )
            if combined is not None:
                actual_fingerprints = pdf_page_fingerprints(combined.path)
                source_fingerprints = iter(
                    fingerprint
                    for row_id in outputs.row_ids
                    for fingerprint in pdf_page_fingerprints(pdf_by_row[row_id])
                )
                separator_fingerprints = iter(
                    actual_fingerprints[position - 1] for position in combined.separator_positions
                )
            combined_audit = (
                CombinedAuditOutput(
                    combined.path,
                    combined.page_count,
                    sha256_file(combined.path),
                    outputs.row_ids,
                    tuple(
                        next(separator_fingerprints)
                        if position in combined.separator_positions
                        else next(source_fingerprints)
                        for position in range(1, combined.page_count + 1)
                    ),
                    combined.separator_positions,
                    tuple(page_counts[row_id] for row_id in outputs.row_ids),
                )
                if combined is not None
                else None
            )
            completed_at = self._clock()
            selected_options = {
                "docx": outputs.docx,
                "individual_pdf": outputs.individual_pdf,
                "combined_pdf": outputs.combined_pdf,
                "batch_name": outputs.batch_name,
                "print_settings": outputs.print_settings.to_json() if outputs.print_settings is not None else None,
            }
            audit_context = AuditContext(
                batch_id=batch_id,
                application_version=__version__,
                started_at=started_at,
                completed_at=completed_at,
                status="verified",
                workbook_path=dataset.source.path,
                template_path=request.template.path,
                worksheet=str(dataset.source.options.get("sheet_name", "")) or None,
                mappings=plan.to_json(),
                outputs=audit_outputs,
                warnings=tuple(
                    issue for issue in report.issues if issue.severity is Severity.WARNING
                ),
                locale=request.locale,
                source_kind=dataset.source.kind,
                source_label=dataset.source.label,
                source_sha256=dataset.source.sha256,
                dataset_revision=dataset.revision,
                dataset_sha256=dataset.canonical_sha256(),
                selected_outputs=selected_options,
                ordered_row_ids=outputs.row_ids,
                combined_pdf=combined_audit,
                revision_number=revision_number,
                approval_digest=request.approval_digest,
                journal_id=batch_id,
                platform_report=platform.to_json(),
                workflow=request.approval.to_json(),
                page_geometry=outputs.print_settings.to_json() if outputs.print_settings is not None else None,
                lineage=request.lineage,
            )
            write_summary(
                audit_context,
                staging / "batch_summary.html",
                locale=request.locale,
            )
            write_support_log(audit_context, staging / "support.log")

            if not outputs.docx:
                for path in docx_by_row.values():
                    path.unlink()
            if not outputs.individual_pdf:
                for path in pdf_by_row.values():
                    path.unlink()

            write_manifest(audit_context, staging / "manifest.json")

            selected_artifacts = tuple(
                path
                for paths in (
                    tuple(docx_by_row.values()) if outputs.docx else (),
                    tuple(pdf_by_row.values()) if outputs.individual_pdf else (),
                    (combined.path,) if combined is not None else (),
                )
                for path in paths
            )
            expected_hashes = {path: sha256_file(path) for path in selected_artifacts}
            self._verify_selected_artifacts(
                selected_artifacts,
                expected_hashes,
                combined,
                sum(page_counts.values()) + outputs.separator_count,
            )
            self._emit(
                progress,
                "verification",
                total,
                total,
                "Verified every selected output artifact.",
            )
            if cancellation.requested:
                return self._cancel(staging)
            self._require_source_hash(dataset)
            self._require_template_hash(request.template.path, report.template_sha256)
            journal.transition(JournalState.READY_TO_PUBLISH)
            integrity = IntegrityService().verify_revision(
                staging, allow_ready=True,
                approved_snapshot=request.approval.snapshot,
                approved_row_ids=outputs.row_ids,
            )
            if not integrity.valid:
                raise BatchGenerationError(
                    "The staged revision failed its integrity check.",
                    code="integrity.staging_failed",
                )
            if outputs.combined_pdf and outputs.print_settings is not None:
                readiness = PrintReadinessService().verify(
                    staging, outputs.print_settings, allow_ready=True,
                )
                if not readiness.ready:
                    raise BatchGenerationError(
                        "The published PDFs would not match the approved print settings.",
                        code="print.not_ready",
                    )
            if final_directory.exists():
                raise BatchGenerationError(
                    "The final batch folder appeared during generation and was not overwritten.",
                    code="batch_already_exists",
                )
            intent_path = BatchJournal.create_publish_intent(
                destination, batch_id, final_directory.name,
                request.approval_digest, revision_number,
            )
            os.replace(staging, final_directory)
            journal.path = final_directory / journal.path.name
            journal.transition(JournalState.PUBLISHED)
            result_issues = list(report.issues)
            history_indexed: bool | None = None
            if request.duplicate_policy.check_history:
                history_indexed = False
                try:
                    if request.history_index is None:
                        raise RuntimeError("history.unavailable")
                    entries = tuple(
                        HistoryEntry(
                            tuple(dataset.row(row_id).value(column) for column in request.duplicate_policy.identity_columns),
                            dataset.row(row_id).value(request.duplicate_policy.certificate_id_column)
                            if request.duplicate_policy.certificate_id_column else None,
                        )
                        for row_id in outputs.row_ids
                    )
                    request.history_index.record_batch(
                        PublishedBatch(batch_id, revision_number, completed_at, final_directory), entries
                    )
                    history_indexed = True
                except Exception:
                    result_issues.append(Issue(Severity.WARNING, "history", "history.record_failed"))
            try:
                for artifact in final_directory.iterdir():
                    if artifact.is_file() and not artifact.is_symlink():
                        artifact.chmod(artifact.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
            except OSError:
                result_issues.append(Issue(Severity.WARNING, "output", "output.protection_failed"))
            self._emit(
                progress,
                "publication",
                total,
                total,
                "Published the complete verified batch.",
            )
            if intent_path is not None:
                try:
                    BatchJournal.clear_publish_intent(intent_path, batch_id)
                except Exception:
                    result_issues.append(Issue(Severity.WARNING, "journal", "journal.durability_uncertain"))
            return BatchResult(
                BatchState.PUBLISHED,
                output_dir=final_directory,
                generated_count=total,
                issues=tuple(result_issues),
                combined_pdf_path=(
                    final_directory / combined.path.name
                    if combined is not None
                    else None
                ),
                revision_number=revision_number,
                history_indexed=history_indexed,
            )
        except Exception as error:
            if final_directory.exists() and not staging.exists():
                try:
                    if (
                        BatchJournal.open(final_directory / "batch_journal.json").state is JournalState.PUBLISHED
                        and IntegrityService().verify_revision(
                            final_directory,
                            approved_snapshot=request.approval.snapshot,
                            approved_row_ids=outputs.row_ids,
                        ).valid
                    ):
                        published_issues = list(report.issues)
                        published_issues.append(Issue(Severity.WARNING, "journal", "journal.durability_uncertain"))
                        if request.duplicate_policy.check_history:
                            published_issues.append(Issue(Severity.WARNING, "history", "history.record_failed"))
                        if intent_path is not None:
                            try:
                                BatchJournal.clear_publish_intent(intent_path, batch_id)
                            except Exception:
                                pass
                        return BatchResult(
                            BatchState.PUBLISHED, final_directory, total,
                            tuple(published_issues),
                            final_directory / combined.path.name if combined is not None else None,
                            revision_number, False if request.duplicate_policy.check_history else None,
                        )
                except Exception:
                    pass
            if final_directory.exists() and not staging.exists():
                try:
                    os.replace(final_directory, staging)
                except OSError as rollback_error:
                    try:
                        diagnostic_path = BatchJournal.mark_stranded(final_directory, batch_id)
                    except Exception:
                        diagnostic_path = final_directory / "batch_journal.json"
                    raise BatchGenerationError(
                        f"Publication could not be confirmed. Review the recoverable folder: {final_directory}",
                        code="output.publication_ambiguous",
                        diagnostic_path=diagnostic_path,
                        user_action="Open Recovery and inspect this exact folder before using or retrying it.",
                    ) from rollback_error
            if intent_path is not None:
                try:
                    BatchJournal.clear_publish_intent(intent_path, batch_id)
                except Exception:
                    pass
            diagnostic_path = self._retain_incomplete(staging, batch_id, error)
            if isinstance(error, BatchGenerationError):
                error.diagnostic_path = diagnostic_path
                raise
            code = (
                "output.combined_pdf_verification_failed"
                if isinstance(error, CombinedPdfError)
                else error.code
                if isinstance(error, PdfConversionError)
                else "generation_failed"
            )
            raise BatchGenerationError(
                "The batch could not be completed safely. No official batch was published.",
                code=code,
                diagnostic_path=diagnostic_path,
                user_action="Review the diagnostic report, correct the source files, and try again.",
            ) from error

    @staticmethod
    def _verify_selected_artifacts(
        paths: tuple[Path, ...],
        expected_hashes: dict[Path, str],
        combined: CombinedPdfRecord | None,
        combined_expected_pages: int,
    ) -> None:
        for path in paths:
            if path.suffix.casefold() == ".docx":
                verify_docx(path, set())
            elif path.suffix.casefold() == ".pdf":
                verify_pdf(path)
            if sha256_file(path) != expected_hashes[path]:
                raise BatchGenerationError(
                    "A selected output changed before publication.",
                    code="output.artifact_changed",
                )
        if combined is not None:
            try:
                verify_pdf_page_count(combined.path, combined_expected_pages)
            except ArtifactVerificationError as error:
                raise BatchGenerationError(
                    "The combined PDF changed before publication.",
                    code="output.combined_pdf_verification_failed",
                ) from error

    @staticmethod
    def _require_source_hash(dataset: TabularDataset) -> None:
        source = dataset.source
        if source.path is None:
            return
        try:
            current = sha256_file(source.path)
        except OSError as error:
            raise BatchGenerationError(
                "The recipient source became unavailable.", code="approval.source_changed"
            ) from error
        if current != source.sha256:
            raise BatchGenerationError(
                "The recipient source changed after approval.", code="approval.source_changed"
            )

    @staticmethod
    def _require_template_hash(path: Path, expected_hash: str) -> None:
        try:
            current_hash = sha256_file(path)
        except OSError as error:
            raise BatchGenerationError(
                "The certificate template became unavailable during generation.",
                code="template.changed_during_generation",
            ) from error
        if current_hash != expected_hash:
            raise BatchGenerationError(
                "The certificate template changed during generation.",
                code="template.changed_during_generation",
            )

    def _new_batch_id(self) -> str:
        return f"{self._clock():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"

    @staticmethod
    def _published_folder_name(batch_id: str) -> str:
        match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})-(\d{6})-([A-Za-z0-9_-]+)", batch_id)
        if match:
            year, month, day, clock, suffix = match.groups()
            return f"Certificate Batch {year}-{month}-{day} {clock} {suffix}"
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", batch_id).strip("-")
        return f"Certificate Batch {safe_id or uuid4().hex[:8]}"

    @staticmethod
    def _verify_artifact_set(
        staging: Path,
        artifacts: list[AuditOutput],
        expected: int,
    ) -> None:
        if len(artifacts) != expected:
            raise RuntimeError("The generated artifact count does not match the input count.")
        if len(list(staging.glob("*.docx"))) != expected:
            raise RuntimeError("The staged Word document count is incomplete.")
        if len(list(staging.glob("*.pdf"))) != expected:
            raise RuntimeError("The staged PDF document count is incomplete.")

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        phase: str,
        current: int,
        total: int,
        message: str,
        source_row: int | None = None,
    ) -> None:
        if callback is not None:
            callback(ProgressEvent(phase, current, total, message, source_row))

    @staticmethod
    def _cancel(staging: Path) -> BatchResult:
        shutil.rmtree(staging, ignore_errors=True)
        return BatchResult(BatchState.CANCELLED)

    @staticmethod
    def _retain_incomplete(
        staging: Path,
        batch_id: str,
        error: Exception,
    ) -> Path | None:
        if not staging.exists():
            return None
        (staging / "manifest.json").unlink(missing_ok=True)
        (staging / "batch_summary.html").unlink(missing_ok=True)
        (staging / "support.log").unlink(missing_ok=True)
        diagnostic = {
            "batch_id": batch_id,
            "status": "incomplete",
            "error_code": getattr(error, "code", "generation_failed"),
            "error_type": type(error).__name__,
            "attempts": getattr(error, "attempts", None),
            "user_action": getattr(
                error,
                "user_action",
                "Review the source files and retry the complete batch.",
            ),
        }
        diagnostic_path = staging / "diagnostic.json"
        temporary = staging / ".diagnostic.json.tmp"
        temporary.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, diagnostic_path)
        incomplete = staging.parent / f".certificate-incomplete-{batch_id}"
        if staging == incomplete:
            return diagnostic_path
        if incomplete.exists():
            incomplete = staging.parent / (
                f".certificate-incomplete-{batch_id}-{uuid4().hex[:8]}"
            )
        os.replace(staging, incomplete)
        return incomplete / "diagnostic.json"
