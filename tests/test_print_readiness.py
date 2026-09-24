from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from certificate_automation.audit import (
    AuditContext, AuditOutput, CombinedAuditOutput, pdf_page_fingerprints, pdf_page_geometry,
    sha256_file, write_manifest,
)
from certificate_automation.batch_journal import approval_facts_digest
from certificate_automation.pdf_merge import merge_verified_pdfs
from certificate_automation.print_readiness import (
    ExportError, ExportService, PrintReadinessService, PrintSettings,
)


def _pdf(path: Path, width: float = 612, height: float = 792, *, crop_width: float | None = None) -> Path:
    writer = PdfWriter()
    page = writer.add_blank_page(width=width, height=height)
    stream = DecodedStreamObject()
    stream.set_data(f"0 0 m {width} 20 l S".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if crop_width is not None:
        page.cropbox.upper_right = (crop_width, height)
    with path.open("wb") as output:
        writer.write(output)
    writer.close()
    return path


def _revision(
    tmp_path: Path, *, separator_every: int | None = None,
    widths: tuple[int, int, int] = (611, 612, 613),
) -> Path:
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    template = tmp_path / "source.docx"
    template.write_bytes(b"source")
    first = _pdf(folder / "first.pdf", width=widths[0])
    second = _pdf(folder / "second.pdf", width=widths[1])
    third = _pdf(folder / "third.pdf", width=widths[2])
    sources = (first, second, third)
    combined = merge_verified_pdfs(sources, folder / "Awards.pdf", separator_every=separator_every)
    rows = ("row-1", "row-2", "row-3")
    settings = PrintSettings(Decimal("612"), Decimal("792"), "portrait", separator_every)
    (folder / "batch_summary.html").write_text("summary", encoding="utf-8")
    (folder / "support.log").write_text("support", encoding="utf-8")
    context = AuditContext(
        "batch-1", "3.0", datetime.now(timezone.utc), datetime.now(timezone.utc),
        "verified", None, template, None, {},
        tuple(AuditOutput(index + 2, None, path, rows[index]) for index, path in enumerate(sources)),
        dataset_revision=1, revision_number=1, approval_digest="a" * 64,
        journal_id="batch-1", ordered_row_ids=rows,
        selected_outputs={"print_settings": settings.to_json()},
        workflow={"snapshot": {"digest": "a" * 64, "recipient_count": 3,
                               "output_counts": {"docx": 0, "pdf": 3, "combined": 1,
                                                 "separator": len(combined.separator_positions)}}},
        combined_pdf=CombinedAuditOutput(
            combined.path, combined.page_count, sha256_file(combined.path), rows,
            pdf_page_fingerprints(combined.path), combined.separator_positions,
            (1, 1, 1),
        ),
    )
    write_manifest(context, folder / "manifest.json")
    counts = {"recipients": 3, "docx": 0, "pdf": 3, "combined": 1}
    (folder / "batch_journal.json").write_text(json.dumps({
        "schema_version": 1, "batch_id": "batch-1", "state": "published",
        "approval_digest": "a" * 64, "revision": 1,
        "intended_counts": counts, "approved_row_ids": list(rows),
        "approval_facts_sha256": approval_facts_digest("a" * 64, counts, list(rows)),
    }), encoding="utf-8")
    return folder


@pytest.mark.parametrize("separator_every, expected_pages", [(None, 3), (2, 4)])
def test_readiness_verifies_published_pages_in_recipient_order(tmp_path, separator_every, expected_pages):
    revision = _revision(tmp_path, separator_every=separator_every)

    report = PrintReadinessService().verify(revision)

    assert report.ready
    assert report.recipient_count == 3
    assert report.individual_page_count == 3
    assert report.combined_page_count == expected_pages
    assert report.issues == ()


@pytest.mark.parametrize("mutation", [
    "wrong_size", "wrong_orientation", "missing_row", "duplicate_row",
    "wrong_order", "wrong_hash", "wrong_crop", "wrong_separator",
])
def test_readiness_rejects_changed_geometry_order_bytes_and_separator(tmp_path, mutation):
    revision = _revision(tmp_path, separator_every=2)
    manifest_path = revision / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if mutation == "wrong_size":
        manifest["selected_outputs"]["print_settings"]["expected_width_points"] = "610"
    elif mutation == "wrong_orientation":
        manifest["selected_outputs"]["print_settings"]["orientation"] = "landscape"
    elif mutation == "missing_row":
        manifest["ordered_row_ids"] = ["row-1", "row-2"]
    elif mutation == "duplicate_row":
        manifest["ordered_row_ids"][2] = "row-2"
    elif mutation == "wrong_order":
        manifest["combined_pdf"]["source_order"] = ["row-2", "row-1", "row-3"]
    elif mutation == "wrong_hash":
        (revision / "Awards.pdf").write_bytes(b"changed")
    elif mutation == "wrong_crop":
        _pdf(revision / "first.pdf", crop_width=600)
        manifest["outputs"][0]["pdf_size"] = (revision / "first.pdf").stat().st_size
        manifest["outputs"][0]["pdf_sha256"] = sha256_file(revision / "first.pdf")
        manifest["outputs"][0]["pdf_geometry"] = [{"width_pt": 612.0, "height_pt": 792.0, "rotation": 0}]
    elif mutation == "wrong_separator":
        manifest["combined_pdf"]["separator_positions"] = [2]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = PrintReadinessService().verify(revision)

    assert report.ready is False
    assert report.issues


def test_geometry_allows_one_point_difference_but_not_more(tmp_path):
    revision = _revision(tmp_path, widths=(612, 612, 612))
    manifest_path = revision / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["selected_outputs"]["print_settings"]["expected_width_points"] = "611"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert PrintReadinessService().verify(revision).ready
    manifest["selected_outputs"]["print_settings"]["expected_width_points"] = "610.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not PrintReadinessService().verify(revision).ready


def test_readiness_compares_combined_pages_to_individual_sources_even_if_manifest_rehashed(tmp_path):
    revision = _revision(tmp_path)
    combined = revision / "Awards.pdf"
    writer = PdfWriter()
    for name in ("second.pdf", "first.pdf", "third.pdf"):
        writer.append(revision / name)
    with combined.open("wb") as output:
        writer.write(output)
    writer.close()
    manifest_path = revision / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["combined_pdf"].update({
        "sha256": sha256_file(combined), "size": combined.stat().st_size,
        "page_fingerprints": list(pdf_page_fingerprints(combined)),
        "page_geometry": pdf_page_geometry(combined),
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = PrintReadinessService().verify(revision)

    assert not report.ready
    assert any(issue.code == "print.order_mismatch" for issue in report.issues)


def test_readiness_rejects_nonblank_separator_even_if_manifest_rehashed(tmp_path):
    revision = _revision(tmp_path, separator_every=2)
    combined = revision / "Awards.pdf"
    writer = PdfWriter()
    for name in ("first.pdf", "second.pdf", "second.pdf", "third.pdf"):
        writer.append(revision / name)
    with combined.open("wb") as output:
        writer.write(output)
    writer.close()
    manifest_path = revision / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["combined_pdf"].update({
        "sha256": sha256_file(combined), "size": combined.stat().st_size,
        "page_fingerprints": list(pdf_page_fingerprints(combined)),
        "page_geometry": pdf_page_geometry(combined),
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = PrintReadinessService().verify(revision)

    assert not report.ready
    assert any(issue.code == "print.separator_mismatch" for issue in report.issues)


def test_export_copies_only_verified_revision_into_new_folder(tmp_path):
    revision = _revision(tmp_path)
    destination = tmp_path / "removable-copy"

    result = ExportService().export_revision(revision, destination)

    assert result.exported_copy == destination / revision.name
    assert result.local_authoritative == revision
    assert PrintReadinessService().verify(result.exported_copy).ready
    assert {item.name: sha256_file(item) for item in revision.iterdir()} == {
        item.name: sha256_file(item) for item in result.exported_copy.iterdir()
    }
    with pytest.raises(ExportError):
        ExportService().export_revision(revision, destination)


def test_export_refuses_changed_local_source_before_copy(tmp_path):
    revision = _revision(tmp_path)
    (revision / "first.pdf").write_bytes(b"tampered")
    destination = tmp_path / "copy"
    with pytest.raises(ExportError):
        ExportService().export_revision(revision, destination)
    assert not (destination / revision.name).exists()


def test_export_never_overwrites_file_that_appears_in_new_copy_folder(tmp_path, monkeypatch):
    revision = _revision(tmp_path)
    destination = tmp_path / "copy"
    target = destination / revision.name
    real_mkdir = Path.mkdir

    def planted_mkdir(path, *args, **kwargs):
        result = real_mkdir(path, *args, **kwargs)
        if path == target:
            (target / "manifest.json").write_bytes(b"someone else's file")
        return result

    monkeypatch.setattr(Path, "mkdir", planted_mkdir)

    with pytest.raises(ExportError):
        ExportService().export_revision(revision, destination)
    assert (target / "manifest.json").read_bytes() == b"someone else's file"
