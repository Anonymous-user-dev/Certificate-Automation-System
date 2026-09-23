from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform

import pytest
from pypdf import PdfReader

from certificate_automation.batch import BatchGenerator, BatchRequest
from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.importers.clipboard import create_manual_dataset, import_clipboard
from certificate_automation.importers.delimited import import_delimited
from certificate_automation.importers.excel import import_excel, inspect_excel
from certificate_automation.mapping import ColumnValue, MappingPlan
from certificate_automation.output_options import OutputOptions
from certificate_automation.template import inspect_template
from certificate_automation.word import WordPdfConverter


ROOT = Path(__file__).parents[2]


def test_release_accepts_every_offline_source_family(tmp_path):
    excel = ROOT / "examples" / "sample_students.xlsx"
    sheet = inspect_excel(excel).sheet_name
    assert import_excel(excel, sheet).rows

    utf8 = tmp_path / "utf8.csv"
    utf8.write_text("Name,Award\n李明,优秀奖\n", "utf-8")
    assert import_delimited(utf8, "utf-8", ",").rows[0].value("name") == "李明"

    cp1251 = tmp_path / "russian.csv"
    cp1251.write_bytes("Name,Award\nАнна,Золото\n".encode("cp1251"))
    assert import_delimited(cp1251, "cp1251", ",").rows[0].value("award") == "Золото"

    utf16 = tmp_path / "people.tsv"
    utf16.write_bytes("Name\tAward\nAna\tGold\n".encode("utf-16"))
    assert import_delimited(utf16, "utf-16", "\t").rows[0].value("name") == "Ana"

    assert import_clipboard("Name\tAward\nLi\tGold", "tabs").rows
    assert create_manual_dataset(("Name", "Award")).columns


@pytest.mark.word_integration
@pytest.mark.skipif(platform.system() != "Windows", reason="requires Windows")
def test_real_word_publishes_verified_50_recipient_mixed_script_batch(tmp_path):
    columns = (
        Column("name", "Full Name"),
        Column("award", "Award"),
        Column("date", "Date"),
        Column("certificate_id", "Certificate ID"),
    )
    names = ("Ana García", "Анна Петрова", "李明", "Chen Wei", "Олег Иванов")
    rows = tuple(
        DataRow(
            f"row-{index + 1}",
            index + 2,
            {
                "name": f"{names[index % len(names)]} {index + 1:02d}",
                "award": "Excellence / 优秀 / Отличие",
                "date": "2026-09-20",
                "certificate_id": f"CERT-2026-{index + 1:03d}",
            },
        )
        for index in range(50)
    )
    dataset = TabularDataset(
        columns,
        rows,
        SourceSnapshot(
            "manual",
            "50-recipient release acceptance",
            None,
            "a" * 64,
            datetime.now(timezone.utc),
        ),
    )
    template = inspect_template(ROOT / "examples" / "sample_certificate_template.docx")
    plan = MappingPlan(
        {
            "FULL_NAME": ColumnValue("name"),
            "AWARD": ColumnValue("award"),
            "DATE": ColumnValue("date"),
            "CERTIFICATE_ID": ColumnValue("certificate_id"),
        }
    )
    options = OutputOptions(True, True, True, tmp_path, "All Certificates", dataset.order)

    result = BatchGenerator(WordPdfConverter(max_attempts=2)).generate(
        BatchRequest(dataset, template, plan, options, "en")
    )

    output = result.output_dir
    assert output is not None
    docx_files = tuple(output.glob("*.docx"))
    pdf_files = tuple(path for path in output.glob("*.pdf") if path.name != "All Certificates.pdf")
    combined = output / "All Certificates.pdf"
    assert result.combined_pdf_path == combined
    assert len(docx_files) == 50
    assert len(pdf_files) == 50
    assert len(PdfReader(combined).pages) == sum(len(PdfReader(path).pages) for path in pdf_files)
    manifest = json.loads((output / "manifest.json").read_text("utf-8"))
    for artifact in manifest["outputs"]:
        assert artifact["docx_sha256"] == sha256((output / artifact["docx_filename"]).read_bytes()).hexdigest()
        assert artifact["pdf_sha256"] == sha256((output / artifact["pdf_filename"]).read_bytes()).hexdigest()
    assert all(inspect_template(path).names == () for path in docx_files)
    assert not tuple(tmp_path.glob(".certificate-staging-*"))
    support = (output / "support.log").read_text("utf-8")
    assert not any(name in support for name in names)
