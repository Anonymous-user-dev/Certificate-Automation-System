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
    separator_positions: tuple[int, ...] = ()


def merge_verified_pdfs(
    inputs: tuple[Path, ...],
    destination: Path,
    *,
    separator_every: int | None = None,
) -> CombinedPdfRecord:
    """Merge already generated PDFs atomically and verify the result independently."""

    inputs = tuple(Path(path) for path in inputs)
    destination = Path(destination)
    if not inputs:
        raise CombinedPdfError("output.combined_pdf_empty")
    if separator_every is not None and (type(separator_every) is not int or separator_every < 1):
        raise CombinedPdfError("output.separator_interval_invalid")
    if any(path.resolve() == destination.resolve() for path in inputs):
        raise CombinedPdfError("output.combined_pdf_overwrites_source")
    if destination.exists():
        raise CombinedPdfError("output.combined_pdf_destination_exists")

    expected_pages = 0
    separator_count = (len(inputs) - 1) // separator_every if separator_every is not None else 0
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
        separator_positions: list[int] = []
        page_number = 0
        for index, path in enumerate(inputs, start=1):
            reader = PdfReader(path, strict=True)
            writer.append(reader)
            page_number += len(reader.pages)
            if separator_every is not None and index < len(inputs) and index % separator_every == 0:
                last_page = reader.pages[-1]
                blank = writer.add_blank_page(
                    width=float(last_page.mediabox.width), height=float(last_page.mediabox.height)
                )
                rotation = int(last_page.get("/Rotate", 0))
                if rotation:
                    blank.rotate(rotation)
                page_number += 1
                separator_positions.append(page_number)
        with temporary.open("wb") as output:
            writer.write(output)
            output.flush()
            os.fsync(output.fileno())
        verify_pdf(temporary)
        actual_pages = len(PdfReader(temporary, strict=True).pages)
        if actual_pages != expected_pages + separator_count:
            raise CombinedPdfError("output.combined_pdf_page_count_mismatch")
        digest = _sha256_file(temporary)
        os.replace(temporary, destination)
        return CombinedPdfRecord(destination, actual_pages, digest, inputs, tuple(separator_positions))
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
