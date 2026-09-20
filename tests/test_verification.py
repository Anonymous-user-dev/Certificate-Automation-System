from __future__ import annotations

import pytest
from pypdf import PdfWriter

from certificate_automation.template import render_template
from certificate_automation.verification import (
    ArtifactVerificationError,
    verify_docx,
    verify_pdf,
)
from fixtures import docx_factory


def test_valid_rendered_docx_passes_verification(docx_factory, tmp_path):
    source = docx_factory(paragraph_runs=[["Certificate for {{FULL_NAME}}"]])
    output = tmp_path / "certificate.docx"
    render_template(source, output, {"FULL_NAME": "Ana García"})

    verify_docx(output, {"FULL_NAME"})


def test_remaining_placeholder_is_rejected(docx_factory):
    source = docx_factory(paragraph_runs=[["Certificate for {{FULL_NAME}}"]])

    with pytest.raises(ArtifactVerificationError, match="placeholder"):
        verify_docx(source, {"FULL_NAME"})


def test_corrupt_docx_is_rejected(tmp_path):
    path = tmp_path / "corrupt.docx"
    path.write_bytes(b"not a docx")

    with pytest.raises(ArtifactVerificationError, match="could not be opened"):
        verify_docx(path, set())


def test_missing_docx_is_rejected(tmp_path):
    with pytest.raises(ArtifactVerificationError, match="missing or empty"):
        verify_docx(tmp_path / "missing.docx", set())


def test_valid_pdf_with_nonzero_page_passes(tmp_path):
    path = tmp_path / "valid.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as output:
        writer.write(output)

    verify_pdf(path)


def test_zero_page_pdf_is_rejected(tmp_path):
    path = tmp_path / "empty.pdf"
    writer = PdfWriter()
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(ArtifactVerificationError, match="page"):
        verify_pdf(path)


def test_pdf_with_empty_page_dimensions_is_rejected(tmp_path):
    path = tmp_path / "empty-box.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=0, height=792)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(ArtifactVerificationError, match="dimensions"):
        verify_pdf(path)


def test_non_pdf_file_is_rejected(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"not a pdf")

    with pytest.raises(ArtifactVerificationError, match="valid PDF"):
        verify_pdf(path)


def test_missing_pdf_is_rejected(tmp_path):
    with pytest.raises(ArtifactVerificationError, match="missing or empty"):
        verify_pdf(tmp_path / "missing.pdf")
