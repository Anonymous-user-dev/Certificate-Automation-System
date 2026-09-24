"""Create privacy-conscious, tamper-evident batch audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
from typing import Mapping
from uuid import uuid4
from pypdf import PdfReader

from certificate_automation.domain import Issue
from certificate_automation.i18n import CatalogSet, package_root


@dataclass(frozen=True, slots=True)
class AuditOutput:
    """Published artifacts associated with one workbook row."""

    source_row: int | None
    docx_path: Path | None
    pdf_path: Path | None
    row_id: str | None = None


@dataclass(frozen=True, slots=True)
class CombinedAuditOutput:
    path: Path
    page_count: int
    sha256: str
    source_order: tuple[str, ...]
    page_fingerprints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Information needed to create the final batch records."""

    batch_id: str
    application_version: str
    started_at: datetime
    completed_at: datetime
    status: str
    workbook_path: Path | None
    template_path: Path
    worksheet: str | None
    mappings: Mapping[str, object]
    outputs: tuple[AuditOutput, ...]
    warnings: tuple[Issue, ...] = field(default_factory=tuple)
    locale: str = "en"
    source_kind: str | None = None
    source_label: str | None = None
    source_sha256: str | None = None
    dataset_revision: int | None = None
    dataset_sha256: str | None = None
    selected_outputs: Mapping[str, object] | None = None
    ordered_row_ids: tuple[str, ...] = ()
    combined_pdf: CombinedAuditOutput | None = None
    revision_number: int | None = None
    approval_digest: str | None = None
    journal_id: str | None = None
    platform_report: Mapping[str, object] | None = None
    workflow: Mapping[str, object] | None = None
    page_geometry: Mapping[str, object] | None = None
    export_status: str = "not_exported"
    lineage: tuple[str, ...] = ()


def sha256_file(path: Path) -> str:
    """Calculate a file hash without loading the whole artifact into memory."""

    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pdf_page_fingerprints(path: Path) -> tuple[str, ...]:
    """Fingerprint page dimensions and content in stable reading order."""

    result = []
    reader = PdfReader(path, strict=True)
    for page in reader.pages:
        digest = sha256()
        geometry = (
            str(page.mediabox.left), str(page.mediabox.bottom),
            str(page.mediabox.right), str(page.mediabox.top), str(page.get("/Rotate", 0)),
        )
        digest.update(json.dumps(geometry).encode("ascii"))
        contents = page.get_contents()
        if contents is not None:
            streams = contents if isinstance(contents, list) else (contents,)
            for stream in streams:
                data = stream.get_object().get_data()
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)
        result.append(digest.hexdigest())
    return tuple(result)


def pdf_page_geometry(path: Path) -> list[dict[str, int | float]]:
    reader = PdfReader(path, strict=True)
    return [
        {
            "width_pt": float(page.mediabox.width),
            "height_pt": float(page.mediabox.height),
            "rotation": int(page.get("/Rotate", 0)),
        }
        for page in reader.pages
    ]


def write_manifest(context: AuditContext, destination: Path) -> Path:
    """Write the machine-readable batch manifest atomically."""

    if context.dataset_revision is not None:
        return _write_manifest_v2(context, destination)

    payload = {
        "schema_version": 1,
        "batch_id": context.batch_id,
        "application_version": context.application_version,
        "status": context.status,
        "locale": context.locale,
        "started_at": context.started_at.isoformat(),
        "completed_at": context.completed_at.isoformat(),
        "worksheet": context.worksheet,
        "sources": {
            "workbook": _source_record(context.workbook_path),
            "template": _source_record(context.template_path),
        },
        "mappings": dict(context.mappings),
        "counts": {
            "recipients": len(context.outputs),
            "docx": len(context.outputs),
            "pdf": len(context.outputs),
            "warnings": len(context.warnings),
        },
        "warnings": [
            {
                "code": issue.code,
                "source": issue.source,
                "row_id": issue.row_id,
                "column_id": issue.column_id,
                "parameters": dict(issue.parameters),
            }
            for issue in context.warnings
        ],
        "outputs": [
            {
                "source_row": output.source_row,
                "docx_filename": output.docx_path.name if output.docx_path else None,
                "docx_sha256": sha256_file(output.docx_path) if output.docx_path else None,
                "pdf_filename": output.pdf_path.name if output.pdf_path else None,
                "pdf_sha256": sha256_file(output.pdf_path) if output.pdf_path else None,
            }
            for output in context.outputs
        ],
    }
    return _atomic_write_text(
        Path(destination),
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_manifest_v2(context: AuditContext, destination: Path) -> Path:
    output_records = []
    for output in context.outputs:
        record = {
            "row_id": output.row_id,
            "source_row": output.source_row,
            "docx_filename": output.docx_path.name if output.docx_path else None,
            "docx_sha256": sha256_file(output.docx_path) if output.docx_path else None,
            "pdf_filename": output.pdf_path.name if output.pdf_path else None,
            "pdf_sha256": sha256_file(output.pdf_path) if output.pdf_path else None,
        }
        output_records.append(record)
    combined = None
    if context.combined_pdf is not None:
        combined = {
            "filename": context.combined_pdf.path.name,
            "sha256": context.combined_pdf.sha256,
            "page_count": context.combined_pdf.page_count,
            "source_order": list(context.combined_pdf.source_order),
        }
    payload = {
        "schema_version": 3 if context.revision_number is not None else 2,
        "batch_id": context.batch_id,
        "application_version": context.application_version,
        "status": context.status,
        "locale": context.locale,
        "started_at": context.started_at.isoformat(),
        "completed_at": context.completed_at.isoformat(),
        "sources": {
            "data": {
                "kind": context.source_kind,
                "label": context.source_label,
                "filename": context.workbook_path.name if context.workbook_path else None,
                "sha256": context.source_sha256,
            },
            "template": _source_record(context.template_path),
        },
        "dataset": {
            "revision": context.dataset_revision,
            "sha256": context.dataset_sha256,
        },
        "mappings": dict(context.mappings),
        "selected_outputs": dict(context.selected_outputs or {}),
        "ordered_row_ids": list(context.ordered_row_ids),
        "counts": {
            "recipients": len(context.outputs),
            "docx": sum(output.docx_path is not None for output in context.outputs),
            "pdf": sum(output.pdf_path is not None for output in context.outputs),
            "combined_pdf": int(context.combined_pdf is not None),
            "warnings": len(context.warnings),
        },
        "warnings": [_issue_record(issue) for issue in context.warnings],
        "outputs": output_records,
        "combined_pdf": combined,
    }
    if context.revision_number is not None:
        from certificate_automation.verification import pdf_page_count

        for record, output in zip(output_records, context.outputs):
            record["docx_size"] = output.docx_path.stat().st_size if output.docx_path else None
            record["pdf_size"] = output.pdf_path.stat().st_size if output.pdf_path else None
            record["pdf_pages"] = pdf_page_count(output.pdf_path) if output.pdf_path else None
            record["pdf_geometry"] = pdf_page_geometry(output.pdf_path) if output.pdf_path else None
        if combined is not None:
            combined["size"] = context.combined_pdf.path.stat().st_size
            combined["page_fingerprints"] = list(context.combined_pdf.page_fingerprints)
            combined["page_geometry"] = pdf_page_geometry(context.combined_pdf.path)
        artifacts = []
        for name in ("batch_summary.html", "support.log"):
            path = Path(destination).parent / name
            if path.is_file():
                artifacts.append({"filename": name, "size": path.stat().st_size, "sha256": sha256_file(path)})
        payload.update({
            "revision": context.revision_number,
            "approval_digest": context.approval_digest,
            "journal_id": context.journal_id,
            "platform_report": dict(context.platform_report or {}),
            "workflow": dict(context.workflow or {}),
            "page_geometry": dict(context.page_geometry or {}),
            "export_status": context.export_status,
            "lineage": list(context.lineage),
            "artifacts": artifacts,
        })
    return _atomic_write_text(
        Path(destination),
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_summary(
    context: AuditContext,
    destination: Path,
    *,
    locale: str | None = None,
) -> Path:
    """Write an escaped offline HTML summary intended for office staff."""

    catalogs = CatalogSet.load(package_root(), locale or context.locale)
    mapping_rows = "".join(
        f"<tr><td>{escape(placeholder)}</td><td>"
        f"{escape(str(column) if column else catalogs.text('summary.fixed_value'))}</td></tr>"
        for placeholder, column in context.mappings.items()
    )
    warning_items = "".join(
        f"<li>{escape(catalogs.text(issue.code, **dict(issue.parameters)))}</li>"
        for issue in context.warnings
    ) or f"<li>{escape(catalogs.text('summary.none'))}</li>"
    output_rows = "".join(
        "<tr>"
        f"<td>{output.source_row}</td>"
        f"<td>{escape(output.docx_path.name) if output.docx_path else ''}</td>"
        f"<td>{escape(output.pdf_path.name) if output.pdf_path else ''}</td>"
        "</tr>"
        for output in context.outputs
    )
    audit_details = ""
    if context.revision_number is not None:
        counts = {
            "summary.recipients": len(context.outputs),
            "summary.word_file": sum(item.docx_path is not None for item in context.outputs),
            "summary.pdf_file": sum(item.pdf_path is not None for item in context.outputs),
            "summary.combined_pdf": int(context.combined_pdf is not None),
            "summary.warnings": len(context.warnings),
        }
        workflow = context.workflow or {}
        snapshot = workflow.get("snapshot", {}) if isinstance(workflow, Mapping) else {}
        warning_codes = snapshot.get("warning_codes", ()) if isinstance(snapshot, Mapping) else ()
        facts: list[tuple[str, object]] = [
            ("summary.revision", context.revision_number),
            ("summary.approval_digest", context.approval_digest or catalogs.text("summary.none")),
            ("summary.source_hash", context.source_sha256 or catalogs.text("summary.none")),
            ("summary.dataset_hash", context.dataset_sha256 or catalogs.text("summary.none")),
            ("summary.template_hash", sha256_file(context.template_path)),
            ("summary.export_status", context.export_status),
            ("summary.lineage", ", ".join(context.lineage) or catalogs.text("summary.none")),
            ("summary.warning_ack", ", ".join(str(code) for code in warning_codes) or catalogs.text("summary.none")),
            ("summary.preparer", workflow.get("preparer_name") or catalogs.text("summary.none")),
            ("summary.reviewer", workflow.get("reviewer_name") or catalogs.text("summary.none")),
            ("summary.prepared_at", workflow.get("prepared_at") or catalogs.text("summary.none")),
            ("summary.reviewed_at", workflow.get("reviewed_at") or catalogs.text("summary.none")),
            ("summary.started_at", context.started_at.isoformat()),
            ("summary.completed_at", context.completed_at.isoformat()),
        ]
        for key in (
            "application_version", "python_version", "qt_version", "windows_release",
            "windows_build", "word_version", "converter_version", "filesystem",
        ):
            facts.append((f"summary.{key}", (context.platform_report or {}).get(key) or catalogs.text("summary.none")))
        rows = "".join(
            f"<tr><th>{escape(catalogs.text(label))}</th><td>{escape(str(value))}</td></tr>"
            for label, value in facts
        )
        count_rows = "".join(
            f"<tr><th>{escape(catalogs.text(label))}</th><td>{count}</td></tr>"
            for label, count in counts.items()
        )
        audit_details = (
            f"<h2>{escape(catalogs.text('summary.audit_facts'))}</h2>"
            f"<table><tbody>{rows}{count_rows}</tbody></table>"
            f"<p>{escape(catalogs.text('summary.workflow_disclaimer'))}</p>"
        )
    content = f"""<!doctype html>
<html lang="{escape(catalogs.locale)}">
<head>
  <meta charset="utf-8">
  <title>{escape(catalogs.text('summary.document_title', batch_id=context.batch_id))}</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 2rem; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
    th, td {{ border: 1px solid #d1d5db; padding: .55rem; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .status {{ font-weight: 700; color: #166534; }}
  </style>
</head>
<body>
  <h1>{escape(catalogs.text('summary.title'))}</h1>
  <p class="status">{escape(catalogs.text('summary.status'))}: {escape(context.status.title())}</p>
  <dl>
    <dt>{escape(catalogs.text('summary.batch_id'))}</dt><dd>{escape(context.batch_id)}</dd>
    <dt>{escape(catalogs.text('summary.workbook'))}</dt><dd>{escape(context.workbook_path.name if context.workbook_path else context.source_label or catalogs.text('summary.none'))}</dd>
    <dt>{escape(catalogs.text('summary.template'))}</dt><dd>{escape(context.template_path.name)}</dd>
    <dt>{escape(catalogs.text('summary.worksheet'))}</dt><dd>{escape(context.worksheet or catalogs.text('summary.none'))}</dd>
    <dt>{escape(catalogs.text('summary.recipients'))}</dt><dd>{len(context.outputs)}</dd>
  </dl>
  <h2>{escape(catalogs.text('summary.mappings'))}</h2>
  <table><thead><tr><th>{escape(catalogs.text('summary.placeholder'))}</th><th>{escape(catalogs.text('summary.data_column'))}</th></tr></thead>
    <tbody>{mapping_rows}</tbody></table>
  <h2>{escape(catalogs.text('summary.warnings'))}</h2><ul>{warning_items}</ul>
  <h2>{escape(catalogs.text('summary.generated_files'))}</h2>
  <table><thead><tr><th>{escape(catalogs.text('summary.source_row'))}</th><th>{escape(catalogs.text('summary.word_file'))}</th><th>{escape(catalogs.text('summary.pdf_file'))}</th></tr></thead>
    <tbody>{output_rows}</tbody></table>
  {audit_details}
</body>
</html>
"""
    return _atomic_write_text(Path(destination), content)


def write_support_log(context: AuditContext, destination: Path) -> Path:
    """Write operational facts without recipient values or output filenames."""

    warning_codes = ",".join(
        issue.code or "unspecified_warning" for issue in context.warnings
    ) or "none"
    lines = [
        "certificate_automation_support_log=1",
        f"batch_id={context.batch_id}",
        f"application_version={context.application_version}",
        f"status={context.status}",
        f"started_at={context.started_at.isoformat()}",
        f"completed_at={context.completed_at.isoformat()}",
        f"worksheet={context.worksheet}",
        f"recipient_count={len(context.outputs)}",
        f"warning_count={len(context.warnings)}",
        f"warning_codes={warning_codes}",
    ]
    return _atomic_write_text(Path(destination), "\n".join(lines) + "\n")


def _source_record(path: Path) -> dict[str, str]:
    return {"filename": path.name, "sha256": sha256_file(path)}


def _issue_record(issue: Issue) -> dict[str, object]:
    return {
        "code": issue.code,
        "source": issue.source,
        "row_id": issue.row_id,
        "column_id": issue.column_id,
        "parameters": dict(issue.parameters),
    }


def _atomic_write_text(destination: Path, content: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
