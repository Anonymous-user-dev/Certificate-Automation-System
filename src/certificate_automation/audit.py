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

from certificate_automation.domain import Issue


@dataclass(frozen=True, slots=True)
class AuditOutput:
    """Published artifacts associated with one workbook row."""

    source_row: int
    docx_path: Path
    pdf_path: Path


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Information needed to create the final batch records."""

    batch_id: str
    application_version: str
    started_at: datetime
    completed_at: datetime
    status: str
    workbook_path: Path
    template_path: Path
    worksheet: str
    mappings: Mapping[str, str | None]
    outputs: tuple[AuditOutput, ...]
    warnings: tuple[Issue, ...] = field(default_factory=tuple)


def sha256_file(path: Path) -> str:
    """Calculate a file hash without loading the whole artifact into memory."""

    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(context: AuditContext, destination: Path) -> Path:
    """Write the machine-readable batch manifest atomically."""

    payload = {
        "schema_version": 1,
        "batch_id": context.batch_id,
        "application_version": context.application_version,
        "status": context.status,
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
                "row_number": issue.row_number,
                "message": issue.message,
            }
            for issue in context.warnings
        ],
        "outputs": [
            {
                "source_row": output.source_row,
                "docx_filename": output.docx_path.name,
                "docx_sha256": sha256_file(output.docx_path),
                "pdf_filename": output.pdf_path.name,
                "pdf_sha256": sha256_file(output.pdf_path),
            }
            for output in context.outputs
        ],
    }
    return _atomic_write_text(
        Path(destination),
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_summary(context: AuditContext, destination: Path) -> Path:
    """Write an escaped offline HTML summary intended for office staff."""

    mapping_rows = "".join(
        f"<tr><td>{escape(placeholder)}</td><td>{escape(column or 'Fixed value')}</td></tr>"
        for placeholder, column in context.mappings.items()
    )
    warning_items = "".join(
        f"<li>{escape(issue.message)}</li>" for issue in context.warnings
    ) or "<li>None</li>"
    output_rows = "".join(
        "<tr>"
        f"<td>{output.source_row}</td>"
        f"<td>{escape(output.docx_path.name)}</td>"
        f"<td>{escape(output.pdf_path.name)}</td>"
        "</tr>"
        for output in context.outputs
    )
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Certificate Batch {escape(context.batch_id)}</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 2rem; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
    th, td {{ border: 1px solid #d1d5db; padding: .55rem; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .status {{ font-weight: 700; color: #166534; }}
  </style>
</head>
<body>
  <h1>Certificate batch summary</h1>
  <p class="status">Status: {escape(context.status.title())}</p>
  <dl>
    <dt>Batch ID</dt><dd>{escape(context.batch_id)}</dd>
    <dt>Workbook</dt><dd>{escape(context.workbook_path.name)}</dd>
    <dt>Template</dt><dd>{escape(context.template_path.name)}</dd>
    <dt>Worksheet</dt><dd>{escape(context.worksheet)}</dd>
    <dt>Recipients</dt><dd>{len(context.outputs)}</dd>
  </dl>
  <h2>Mappings</h2>
  <table><thead><tr><th>Placeholder</th><th>Excel column</th></tr></thead>
    <tbody>{mapping_rows}</tbody></table>
  <h2>Warnings</h2><ul>{warning_items}</ul>
  <h2>Generated files</h2>
  <table><thead><tr><th>Source row</th><th>Word file</th><th>PDF file</th></tr></thead>
    <tbody>{output_rows}</tbody></table>
</body>
</html>
"""
    return _atomic_write_text(Path(destination), content)


def _source_record(path: Path) -> dict[str, str]:
    return {"filename": path.name, "sha256": sha256_file(path)}


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

