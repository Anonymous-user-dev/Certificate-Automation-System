"""Strict, order-preserving PDF merge for print-ready certificate batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader, PdfWriter

from certificate_automation.verification import ArtifactVerificationError, verify_pdf


class CombinedPdfError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CombinedPdfRecord:
    path: Path
    page_count: int
    sha256: str
    source_order: tuple[Path, ...]


def merge_verified_pdfs(
    inputs: tuple[Path, ...],
    destination: Path,
) -> CombinedPdfRecord:
    """Merge already generated PDFs atomically and verify the result independently."""

    inputs = tuple(Path(path) for path in inputs)
    destination = Path(destination)
    if not inputs:
        raise CombinedPdfError("output.combined_pdf_empty")
    if any(path.resolve() == destination.resolve() for path in inputs):
        raise CombinedPdfError("output.combined_pdf_overwrites_source")
    if destination.exists():
        raise CombinedPdfError("output.combined_pdf_destination_exists")

    expected_pages = 0
    try:
        for path in inputs:
            verify_pdf(path)
            expected_pages += len(PdfReader(path, strict=True).pages)
    except (ArtifactVerificationError, OSError, ValueError) as error:
        raise CombinedPdfError("output.combined_pdf_input_invalid") from error

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    writer = PdfWriter()
    try:
        for path in inputs:
            writer.append(path)
        with temporary.open("wb") as output:
            writer.write(output)
            output.flush()
            os.fsync(output.fileno())
        verify_pdf(temporary)
        actual_pages = len(PdfReader(temporary, strict=True).pages)
        if actual_pages != expected_pages:
            raise CombinedPdfError("output.combined_pdf_page_count_mismatch")
        digest = _sha256_file(temporary)
        os.replace(temporary, destination)
        return CombinedPdfRecord(destination, actual_pages, digest, inputs)
    except CombinedPdfError:
        raise
    except Exception as error:
        raise CombinedPdfError("output.combined_pdf_failed") from error
    finally:
        writer.close()
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
