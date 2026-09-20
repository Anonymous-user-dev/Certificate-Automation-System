from __future__ import annotations

from datetime import datetime, timezone
import json

from certificate_automation.audit import (
    AuditContext,
    AuditOutput,
    sha256_file,
    write_manifest,
    write_summary,
)
from certificate_automation.domain import Issue, Severity


def _context(tmp_path):
    workbook = tmp_path / "students.xlsx"
    template = tmp_path / "certificate.docx"
    docx = tmp_path / "Ana_Garcia.docx"
    pdf = tmp_path / "Ana_Garcia.pdf"
    workbook.write_bytes(b"workbook")
    template.write_bytes(b"template")
    docx.write_bytes(b"generated docx")
    pdf.write_bytes(b"generated pdf")
    return AuditContext(
        batch_id="20260920-120000-abcd1234",
        application_version="0.1.0",
        started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
        status="verified",
        workbook_path=workbook,
        template_path=template,
        worksheet="Students",
        mappings={"FULL_NAME": "full_name"},
        outputs=(AuditOutput(2, docx, pdf),),
        warnings=(
            Issue(
                Severity.WARNING,
                "workbook",
                "A <value> needs review & approval.",
                code="review_value",
                row_number=2,
            ),
        ),
    )


def test_sha256_file_is_deterministic(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"official")

    assert sha256_file(path) == (
        "6896191a14f6c66534bac457f50996b9330cd702cb6dbaae4c08d1d213e93d98"
    )


def test_manifest_contains_sources_mappings_outputs_and_status(tmp_path):
    context = _context(tmp_path)

    path = write_manifest(context, tmp_path / "manifest.json")
    payload = json.loads(path.read_text("utf-8"))

    assert payload["status"] == "verified"
    assert payload["sources"]["workbook"] == {
        "filename": "students.xlsx",
        "sha256": sha256_file(context.workbook_path),
    }
    assert payload["mappings"]["FULL_NAME"] == "full_name"
    assert payload["outputs"][0]["source_row"] == 2
    assert payload["outputs"][0]["pdf_sha256"] == sha256_file(
        context.outputs[0].pdf_path
    )
    assert "recipient_values" not in payload


def test_manifest_write_is_atomic_and_leaves_no_temporary_file(tmp_path):
    destination = tmp_path / "manifest.json"

    write_manifest(_context(tmp_path), destination)

    assert destination.exists()
    assert list(tmp_path.glob(".manifest.json.*.tmp")) == []


def test_html_summary_escapes_user_controlled_content(tmp_path):
    destination = tmp_path / "batch_summary.html"

    write_summary(_context(tmp_path), destination)
    content = destination.read_text("utf-8")

    assert "A &lt;value&gt; needs review &amp; approval." in content
    assert "A <value>" not in content
    assert "Traceback" not in content
    assert "Ana_Garcia.pdf" in content
