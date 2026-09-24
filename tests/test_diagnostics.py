from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from certificate_automation.diagnostics import (
    DiagnosticBundleService,
    DiagnosticContext,
    DiagnosticError,
)


def test_default_bundle_redacts_values_paths_and_document_bytes(tmp_path):
    project = tmp_path / "Ana García" / "private.certproject"
    context = DiagnosticContext(
        application_version="3.0.0",
        project_path=project,
        issue_codes=("validation.missing_name",),
        exception_text=f"Failed for Ana García at {project} and {Path.home()}",
        configuration={"mapping": {"FULL_NAME": "Ana García"}, "row_values": ["Ana García"]},
        manifest={"schema_version": 3, "outputs": [{"pdf_filename": "Ana García.pdf", "pdf_sha256": "a" * 64}]},
    )

    output = DiagnosticBundleService().create(context, tmp_path / "support.zip")
    with ZipFile(output) as archive:
        names = archive.namelist()
        payload = "\n".join(archive.read(name).decode("utf-8") for name in names)

    assert names == ["diagnostic.json", "support.log"]
    assert "Ana García" not in payload
    assert str(project) not in payload
    assert str(Path.home()) not in payload
    assert "validation.missing_name" in payload
    assert "a" * 64 in payload
    assert not any(name.endswith((".docx", ".pdf", ".xlsx")) for name in names)


def test_bundle_never_overwrites_existing_file(tmp_path):
    destination = tmp_path / "support.zip"
    destination.write_bytes(b"original")

    with pytest.raises(DiagnosticError, match="diagnostic.destination_exists"):
        DiagnosticBundleService().create(DiagnosticContext(), destination)

    assert destination.read_bytes() == b"original"


def test_sensitive_attachment_uses_opaque_archive_name_and_requires_explicit_list(tmp_path):
    sensitive = tmp_path / "Ana García.pdf"
    sensitive.write_bytes(b"official-bytes")

    output = DiagnosticBundleService().create(
        DiagnosticContext(), tmp_path / "support.zip", sensitive_files=(sensitive,)
    )
    with ZipFile(output) as archive:
        names = archive.namelist()
        assert names[-1] == "sensitive/0001.bin"
        assert archive.read(names[-1]) == b"official-bytes"
        assert "Ana García" not in "\n".join(names)


def test_sensitive_attachment_rejects_symlink(tmp_path):
    target = tmp_path / "official.pdf"
    target.write_bytes(b"official-bytes")
    alias = tmp_path / "alias.pdf"
    alias.symlink_to(target)

    with pytest.raises(DiagnosticError, match="diagnostic.unsafe_attachment"):
        DiagnosticBundleService().create(
            DiagnosticContext(), tmp_path / "support.zip", sensitive_files=(alias,)
        )
    assert not (tmp_path / "support.zip").exists()


def test_archive_entry_validator_rejects_traversal_and_absolute_names():
    service = DiagnosticBundleService()
    for name in ("../payload", "folder/../../payload", "/payload", "C:/payload", "folder\\payload"):
        with pytest.raises(DiagnosticError, match="diagnostic.unsafe_name"):
            service.validate_entry_name(name)


def test_bundle_rejects_duplicate_sensitive_paths(tmp_path):
    source = tmp_path / "official.pdf"
    source.write_bytes(b"pdf")
    with pytest.raises(DiagnosticError, match="diagnostic.duplicate_attachment"):
        DiagnosticBundleService().create(
            DiagnosticContext(), tmp_path / "support.zip", sensitive_files=(source, source)
        )
    assert not (tmp_path / "support.zip").exists()


def test_default_bundle_redacts_dynamic_keys_and_platform_paths(tmp_path):
    private = tmp_path / "Ana García" / "certificates"
    context = DiagnosticContext(
        configuration={"Ana García": {"identity": "李明"}, "safe": "value"},
        platform_report={"filesystem": "NTFS", "project_path": str(private), "username": "Ana García"},
    )

    output = DiagnosticBundleService().create(context, tmp_path / "support.zip")
    with ZipFile(output) as archive:
        payload = archive.read("diagnostic.json").decode("utf-8")

    assert "Ana García" not in payload
    assert "李明" not in payload
    assert str(private) not in payload
    assert "NTFS" in payload


def test_default_bundle_ignores_malformed_nested_journal_values(tmp_path):
    context = DiagnosticContext(crash_journal={"state": {"Ana García": "private"}, "schema_version": 1})

    output = DiagnosticBundleService().create(context, tmp_path / "support.zip")
    with ZipFile(output) as archive:
        payload = archive.read("diagnostic.json").decode("utf-8")

    assert "Ana García" not in payload
    assert json.loads(payload)["crash_journal"] == {"schema_version": 1}


def test_manifest_counts_and_hashes_reject_dynamic_private_keys(tmp_path):
    private = str(tmp_path / "Ana García" / "recipients.xlsx")
    context = DiagnosticContext(manifest={
        "schema_version": 3,
        "counts": {
            "recipients": 2, "combined_pdf": 1,
            "Ana García": 7, private: 8, "row\nprivate": 9,
            "pdf": True, "docx": -1,
        },
        "sources": {"template": {"sha256": "a" * 64}},
        "unknown": {"private_sha256": "f" * 64, "Ana García": {"sha256": "e" * 64}},
    })

    output = DiagnosticBundleService().create(context, tmp_path / "support.zip")
    with ZipFile(output) as archive:
        raw = archive.read("diagnostic.json").decode("utf-8")
    facts = json.loads(raw)["manifest_facts"]

    assert facts["counts"] == {"recipients": 2, "combined_pdf": 1}
    assert facts["sha256"] == ["a" * 64]
    assert "Ana García" not in raw
    assert private not in raw
    assert "row\\nprivate" not in raw
    assert "f" * 64 not in raw and "e" * 64 not in raw
