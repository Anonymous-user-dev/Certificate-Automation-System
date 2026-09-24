from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest
from pypdf import PdfWriter

from certificate_automation.audit import AuditContext, AuditOutput, CombinedAuditOutput, sha256_file, write_manifest
from certificate_automation.batch_journal import approval_facts_digest
from certificate_automation.integrity import IntegrityService


def _pdf(path, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as stream:
        writer.write(stream)
    writer.close()


@pytest.fixture
def revision(tmp_path):
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    template = tmp_path / "source.docx"
    template.write_bytes(b"template")
    docx = folder / "one.docx"
    docx.write_bytes(b"docx")
    pdf = folder / "one.pdf"
    _pdf(pdf)
    summary = folder / "batch_summary.html"
    summary.write_text("summary", encoding="utf-8")
    support = folder / "support.log"
    support.write_text("support", encoding="utf-8")
    context = AuditContext(
        "batch-1", "3.0", datetime.now(timezone.utc), datetime.now(timezone.utc),
        "verified", None, template, None, {}, (AuditOutput(2, docx, pdf, "row-1"),),
        dataset_revision=1, revision_number=1, approval_digest="a" * 64,
        journal_id="batch-1", ordered_row_ids=("row-1",),
        platform_report={"volume": "NTFS"},
        workflow={"snapshot": {"digest": "a" * 64, "recipient_count": 1,
                               "output_counts": {"docx": 1, "pdf": 1, "combined": 0}}},
    )
    write_manifest(context, folder / "manifest.json")
    counts = {"recipients": 1, "docx": 1, "pdf": 1, "combined": 0}
    (folder / "batch_journal.json").write_text(json.dumps({
        "schema_version": 1, "batch_id": "batch-1", "state": "published",
        "approval_digest": "a" * 64, "revision": 1,
        "intended_counts": counts,
        "approved_row_ids": ["row-1"],
        "approval_facts_sha256": approval_facts_digest("a" * 64, counts, ["row-1"]),
    }), encoding="utf-8")
    return folder


def test_schema3_manifest_verifies_artifact_bytes_and_order(revision):
    manifest = json.loads((revision / "manifest.json").read_text("utf-8"))
    assert manifest["schema_version"] == 3
    assert manifest["revision"] == 1
    assert manifest["approval_digest"] == "a" * 64
    assert manifest["outputs"][0]["docx_size"] == 4
    assert manifest["outputs"][0]["pdf_pages"] == 1
    assert manifest["outputs"][0]["pdf_geometry"] == [{"width_pt": 612.0, "height_pt": 792.0, "rotation": 0}]
    assert IntegrityService().verify_revision(revision).valid


def test_integrity_rejects_extra_file_with_same_name_ignoring_case(revision):
    (revision / "ONE.PDF").write_bytes(b"impostor")
    assert not IntegrityService().verify_revision(revision).valid


def test_integrity_rejects_missing_publication_journal(revision):
    (revision / "batch_journal.json").unlink()
    assert not IntegrityService().verify_revision(revision).valid


def test_integrity_rejects_coherently_removed_recipient_and_artifacts(revision):
    manifest_path = revision / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["outputs"] = []
    manifest["ordered_row_ids"] = []
    manifest["counts"].update({"recipients": 0, "docx": 0, "pdf": 0})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (revision / "one.docx").unlink()
    (revision / "one.pdf").unlink()
    assert not IntegrityService().verify_revision(revision).valid


def test_integrity_rejects_changed_journal_intent_when_approval_binding_is_unchanged(revision):
    journal_path = revision / "batch_journal.json"
    journal = json.loads(journal_path.read_text("utf-8"))
    journal["intended_counts"] = {"recipients": 0, "docx": 0, "pdf": 0, "combined": 0}
    journal["approved_row_ids"] = []
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    assert not IntegrityService().verify_revision(revision).valid


def test_external_frozen_approval_rejects_coordinated_manifest_and_journal_omission(revision):
    from certificate_automation.approval import ApprovalSnapshot
    manifest_path = revision / "manifest.json"
    journal_path = revision / "batch_journal.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    journal = json.loads(journal_path.read_text("utf-8"))
    frozen = ApprovalSnapshot("a" * 64, 1, 1, {"docx": 1, "pdf": 1, "combined": 0}, ())
    manifest["outputs"] = []
    manifest["ordered_row_ids"] = []
    manifest["counts"].update({"recipients": 0, "docx": 0, "pdf": 0})
    manifest["workflow"]["snapshot"]["recipient_count"] = 0
    manifest["workflow"]["snapshot"]["output_counts"].update({"docx": 0, "pdf": 0})
    journal["intended_counts"].update({"recipients": 0, "docx": 0, "pdf": 0})
    journal["approved_row_ids"] = []
    journal["approval_facts_sha256"] = approval_facts_digest("a" * 64, journal["intended_counts"], [])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    (revision / "one.docx").unlink()
    (revision / "one.pdf").unlink()
    report = IntegrityService().verify_revision(
        revision, approved_snapshot=frozen, approved_row_ids=("row-1",),
    )
    assert not report.valid
    assert "integrity.external_approval_mismatch" in report.issues


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed", "renamed", "wrong_pages", "wrong_order", "traversal", "collision", "wrong_count"])
def test_integrity_rejects_modified_revision(revision, mutation):
    manifest_path = revision / "manifest.json"
    payload = json.loads(manifest_path.read_text("utf-8"))
    if mutation == "missing":
        (revision / "one.pdf").unlink()
    elif mutation == "extra":
        (revision / "other.pdf").write_bytes(b"unexpected")
    elif mutation == "changed":
        (revision / "one.docx").write_bytes(b"changed")
    elif mutation == "renamed":
        (revision / "one.pdf").rename(revision / "renamed.pdf")
    elif mutation == "wrong_pages":
        payload["outputs"][0]["pdf_pages"] = 2
    elif mutation == "wrong_order":
        payload["ordered_row_ids"] = ["different-row"]
    elif mutation == "traversal":
        payload["outputs"][0]["pdf_filename"] = "../one.pdf"
    elif mutation == "collision":
        payload["outputs"][0]["pdf_filename"] = "ONE.DOCX"
    elif mutation == "wrong_count":
        payload["counts"]["recipients"] = 99
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not IntegrityService().verify_revision(revision).valid


def test_integrity_detects_combined_page_swap_even_with_updated_file_hash(tmp_path):
    from certificate_automation.audit import pdf_page_fingerprints
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    template = tmp_path / "template.docx"
    template.write_bytes(b"template")
    first = folder / "first.pdf"
    second = folder / "second.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=613, height=792)
    with first.open("wb") as stream:
        writer.write(stream)
    writer.close()
    writer = PdfWriter()
    writer.add_blank_page(width=614, height=792)
    with second.open("wb") as stream:
        writer.write(stream)
    writer.close()
    combined = folder / "All.pdf"
    writer = PdfWriter()
    writer.append(first)
    writer.append(second)
    with combined.open("wb") as stream:
        writer.write(stream)
    writer.close()
    context = AuditContext(
        "batch-1", "3.0", datetime.now(timezone.utc), datetime.now(timezone.utc),
        "verified", None, template, None, {},
        (AuditOutput(2, None, first, "row-1"), AuditOutput(3, None, second, "row-2")),
        dataset_revision=1, revision_number=1, approval_digest="a" * 64,
        journal_id="batch-1", ordered_row_ids=("row-1", "row-2"),
        workflow={"snapshot": {"digest": "a" * 64, "recipient_count": 2,
                               "output_counts": {"docx": 0, "pdf": 2, "combined": 1}}},
        combined_pdf=CombinedAuditOutput(combined, 2, sha256_file(combined), ("row-1", "row-2"),
                                         pdf_page_fingerprints(first) + pdf_page_fingerprints(second)),
    )
    write_manifest(context, folder / "manifest.json")
    counts = {"recipients": 2, "docx": 0, "pdf": 2, "combined": 1}
    (folder / "batch_journal.json").write_text(json.dumps({
        "schema_version": 1, "batch_id": "batch-1", "state": "published",
        "approval_digest": "a" * 64, "revision": 1,
        "intended_counts": counts, "approved_row_ids": ["row-1", "row-2"],
        "approval_facts_sha256": approval_facts_digest("a" * 64, counts, ["row-1", "row-2"]),
    }), encoding="utf-8")
    assert IntegrityService().verify_revision(folder).valid
    writer = PdfWriter()
    writer.append(second)
    writer.append(first)
    with combined.open("wb") as stream:
        writer.write(stream)
    writer.close()
    payload = json.loads((folder / "manifest.json").read_text("utf-8"))
    payload["combined_pdf"]["sha256"] = sha256_file(combined)
    payload["combined_pdf"]["size"] = combined.stat().st_size
    (folder / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    assert "integrity.combined_order_mismatch" in IntegrityService().verify_revision(folder).issues


def test_correction_clone_advances_project_and_clears_approval_without_changing_original(revision):
    from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
    from certificate_automation.project import ProjectState
    dataset = TabularDataset(
        (Column("name", "Name"),), (DataRow("row-1", 2, {"name": "Ana"}),),
        SourceSnapshot("manual", "People", None, "a" * 64, datetime.now(timezone.utc)),
    )
    project = ProjectState(4, dataset, approval={"digest": "frozen"},
                           acknowledgements=("reviewed",), preview_revision=4)
    before = (revision / "manifest.json").read_bytes()
    corrected = IntegrityService().clone_for_correction(project, revision)
    assert corrected.revision == 5
    assert corrected.approval is None
    assert corrected.acknowledgements == ()
    assert corrected.preview_revision is None
    assert corrected.published_revisions == (str(revision),)
    assert project.approval is not None
    assert (revision / "manifest.json").read_bytes() == before
