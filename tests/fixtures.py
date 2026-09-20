from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
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

