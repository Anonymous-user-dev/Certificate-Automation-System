"""All-or-nothing certificate batch generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from threading import Event
from typing import Callable
from uuid import uuid4

from certificate_automation import __version__
from certificate_automation.audit import (
    AuditContext,
    AuditOutput,
    write_manifest,
    write_support_log,
    write_summary,
)
from certificate_automation.domain import BatchResult, BatchState, Severity
from certificate_automation.mapping import MappingSelection
from certificate_automation.template import TemplateInspection, render_template
from certificate_automation.validation import validate_preflight
from certificate_automation.verification import verify_docx, verify_pdf
from certificate_automation.word import PdfConversionError, PdfConverter
from certificate_automation.workbook import WorkbookData


ProgressCallback = Callable[["ProgressEvent"], None]


@dataclass(frozen=True, slots=True)
class BatchRequest:
    workbook: WorkbookData
    template: TemplateInspection
    mappings: MappingSelection
    destination: Path


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
    ) -> None:
        self._converter = converter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._batch_id_factory = batch_id_factory or self._new_batch_id

    def generate(
        self,
        request: BatchRequest,
        progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> BatchResult:
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
        if incomplete.exists():
            incomplete = staging.parent / (
                f".certificate-incomplete-{batch_id}-{uuid4().hex[:8]}"
            )
        os.replace(staging, incomplete)
        return incomplete / "diagnostic.json"
