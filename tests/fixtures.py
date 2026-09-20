from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from lxml import etree
from openpyxl import Workbook


@pytest.fixture
def xlsx_factory(tmp_path: Path) -> Callable[..., Path]:
    created = 0

    def create(
        rows: Sequence[Sequence[Any]],
        *,
        sheet_name: str = "Students",
        extra_sheets: Sequence[str] = (),
    ) -> Path:
        nonlocal created
        created += 1
        path = tmp_path / f"workbook-{created}.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = sheet_name
        for row in rows:
            worksheet.append(list(row))
        for name in extra_sheets:
            workbook.create_sheet(name)
        workbook.save(path)
        workbook.close()
        return path

    return create


@pytest.fixture
def docx_factory(tmp_path: Path) -> Callable[..., Path]:
    created = 0

    def create(
        *,
        paragraph_runs: Sequence[Sequence[str]] = (),
        table_text: str | None = None,
        header_text: str | None = None,
        footer_text: str | None = None,
    ) -> Path:
        nonlocal created
        created += 1
        path = tmp_path / f"template-{created}.docx"
        document = Document()
        for run_texts in paragraph_runs:
            paragraph = document.add_paragraph()
            for run_text in run_texts:
                paragraph.add_run(run_text)
        if table_text is not None:
            document.add_table(rows=1, cols=1).cell(0, 0).text = table_text
        if header_text is not None:
            document.sections[0].header.paragraphs[0].text = header_text
        if footer_text is not None:
            document.sections[0].footer.paragraphs[0].text = footer_text
        document.save(path)
        return path

    return create


@pytest.fixture
def ooxml_docx_factory(docx_factory) -> Callable[..., Path]:
    def create(*, text_box: str) -> Path:
        path = docx_factory(paragraph_runs=[["Ordinary body text"]])
        with ZipFile(path, "r") as source:
            members = {item.filename: source.read(item.filename) for item in source.infolist()}

        root = etree.fromstring(members["word/document.xml"])
        namespaces = {
            "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
            "v": "urn:schemas-microsoft-com:vml",
        }
        body = root.find("w:body", namespaces)
        paragraph = etree.fromstring(
            (
                '<w:p xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml">'
                '<w:r><w:pict><v:shape id="TextBox1" style="width:200pt;height:30pt">'
                '<v:textbox><w:txbxContent><w:p><w:r><w:t></w:t></w:r></w:p>'
                '</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>'
            ).encode("utf-8")
        )
        paragraph.find(".//w:t", namespaces).text = text_box
        body.insert(len(body) - 1, paragraph)
        members["word/document.xml"] = etree.tostring(
            root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

        with ZipFile(path, "w", ZIP_DEFLATED) as destination:
            for name, data in members.items():
                destination.writestr(name, data)
        return path

    return create
