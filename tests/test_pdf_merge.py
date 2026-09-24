from __future__ import annotations

from pypdf import PdfReader, PdfWriter
import pytest

from certificate_automation.pdf_merge import CombinedPdfError, merge_verified_pdfs


def _pdf(path, widths):
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=792)
    with path.open("wb") as output:
        writer.write(output)
    return path


def test_merge_preserves_selected_order_and_total_pages(tmp_path):
    second = _pdf(tmp_path / "second.pdf", (220, 221))
    first = _pdf(tmp_path / "first.pdf", (110,))

    record = merge_verified_pdfs((second, first), tmp_path / "batch.pdf")

    assert record.page_count == 3
    assert [float(page.mediabox.width) for page in PdfReader(record.path).pages] == [220, 221, 110]
    assert record.source_order == (second, first)
    assert len(record.sha256) == 64


def test_separator_page_preserves_recipient_pages_and_order(tmp_path):
    first = _pdf(tmp_path / "first.pdf", (611,))
    second = _pdf(tmp_path / "second.pdf", (612,))
    third = _pdf(tmp_path / "third.pdf", (613,))

    record = merge_verified_pdfs((first, second, third), tmp_path / "batch.pdf", separator_every=2)

    pages = PdfReader(record.path).pages
    assert record.source_order == (first, second, third)
    assert record.separator_positions == (3,)
    assert record.page_count == 4
    assert [float(page.mediabox.width) for page in pages] == [611, 612, 612, 613]


@pytest.mark.parametrize("interval", [0, -1, True])
def test_separator_interval_must_be_positive_integer(tmp_path, interval):
    source = _pdf(tmp_path / "one.pdf", (612,))
    with pytest.raises(CombinedPdfError) as caught:
        merge_verified_pdfs((source,), tmp_path / "batch.pdf", separator_every=interval)
    assert caught.value.code == "output.separator_interval_invalid"
    assert not (tmp_path / "batch.pdf").exists()


def test_merge_rejects_empty_input_without_creating_output(tmp_path):
    destination = tmp_path / "batch.pdf"

    with pytest.raises(CombinedPdfError) as caught:
        merge_verified_pdfs((), destination)

    assert caught.value.code == "output.combined_pdf_empty"
    assert not destination.exists()


def test_merge_rejects_corrupt_input_without_replacing_existing_file(tmp_path):
    destination = tmp_path / "batch.pdf"
    destination.write_bytes(b"existing official pdf")
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not pdf")

    with pytest.raises(CombinedPdfError):
        merge_verified_pdfs((corrupt,), destination)

    assert destination.read_bytes() == b"existing official pdf"


def test_merge_never_overwrites_an_existing_destination(tmp_path):
    source = _pdf(tmp_path / "source.pdf", (100,))
    destination = tmp_path / "batch.pdf"
    destination.write_bytes(b"existing official pdf")

    with pytest.raises(CombinedPdfError) as caught:
        merge_verified_pdfs((source,), destination)

    assert caught.value.code == "output.combined_pdf_destination_exists"
    assert destination.read_bytes() == b"existing official pdf"
