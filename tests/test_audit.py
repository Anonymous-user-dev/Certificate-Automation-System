from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
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
                "validation.review_value",
                {"value": "A <value>"},
                row_id="row-2",
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
    assert payload["warnings"][0] == {
        "code": "validation.review_value",
        "source": "workbook",
        "row_id": "row-2",
        "column_id": None,
        "parameters": {"value": "A <value>"},
    }
    assert "message" not in payload["warnings"][0]


def test_manifest_write_is_atomic_and_leaves_no_temporary_file(tmp_path):
    destination = tmp_path / "manifest.json"

    write_manifest(_context(tmp_path), destination)

    assert destination.exists()
    assert list(tmp_path.glob(".manifest.json.*.tmp")) == []


def test_html_summary_escapes_user_controlled_content(tmp_path):
    destination = tmp_path / "batch_summary.html"

    write_summary(_context(tmp_path), destination, locale="en")
    content = destination.read_text("utf-8")

    assert "A &lt;value&gt; needs review &amp; approval." in content
    assert "A <value>" not in content
    assert "Traceback" not in content
    assert "Ana_Garcia.pdf" in content


def test_schema_three_audit_shows_frozen_facts_and_escaped_workflow(tmp_path):
    context = replace(
        _context(tmp_path),
        revision_number=4,
        source_sha256="b" * 64,
        dataset_sha256="c" * 64,
        approval_digest="d" * 64,
        selected_outputs={"docx": True, "individual_pdf": True, "combined_pdf": False},
        platform_report={
            "application_version": "3.0.0", "python_version": "3.14.0",
            "qt_version": "6.11.0", "windows_release": "11", "windows_build": "26100",
            "word_version": "16.0", "converter_version": "Word 16.0", "filesystem": "NTFS",
        },
        workflow={
            "preparer_name": "Анна <approved>", "prepared_at": "2026-09-20T12:00:00+00:00",
            "two_person": True, "reviewer_name": "李 & 王", "reviewed_at": "2026-09-20T12:01:00+00:00",
            "snapshot": {"warning_codes": ["validation.review_value"]},
        },
        export_status="not_exported",
        lineage=("Awards-revision-3",),
    )

    path = write_summary(context, tmp_path / "batch_summary.html")
    html = path.read_text("utf-8")

    for fact in ("4", "1", "3.14.0", "6.11.0", "26100", "16.0", "NTFS", "Awards-revision-3", "validation.review_value", "not_exported"):
        assert fact in html
    for digest in ("b" * 64, "c" * 64, "d" * 64, sha256_file(context.template_path)):
        assert digest in html
    assert "Анна &lt;approved&gt;" in html
    assert "李 &amp; 王" in html
    assert "Анна <approved>" not in html
    assert "李 & 王" not in html
    assert "not identity verification or a digital signature" in html
