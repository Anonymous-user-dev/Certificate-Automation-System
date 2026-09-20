"""Compatibility facade for the canonical Excel importer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from certificate_automation.dataset import normalize_column_id
from certificate_automation.domain import Recipient
from certificate_automation.importers.excel import (
    ExcelImportError,
    import_excel,
    inspect_excel,
)


class WorkbookInputError(ValueError):
    """Raised when a workbook cannot safely provide recipient data."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkbookData:
    """Legacy view used until every service consumes ``TabularDataset``."""

    path: Path
    sheet_name: str
    headers: tuple[str, ...]
    display_headers: Mapping[str, str]
    recipients: tuple[Recipient, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "display_headers",
            MappingProxyType(dict(self.display_headers)),
        )


def normalize_field_name(value: str) -> str:
    """Retain the version 1 name for canonical column normalization."""

    return normalize_column_id(value)


def list_worksheets(path: Path) -> tuple[str, ...]:
    """List worksheet names without accepting unsafe cell data."""

    try:
        return inspect_excel(Path(path)).sheet_names
    except ExcelImportError as error:
        raise _compatibility_error(error, Path(path)) from error


def load_workbook_data(path: Path, sheet_name: str) -> WorkbookData:
    """Load through the safe importer and expose the version 1 record shape."""

    path = Path(path)
    try:
        dataset = import_excel(path, sheet_name, include_hidden=True)
    except ExcelImportError as error:
        raise _compatibility_error(error, path, sheet_name) from error
    return WorkbookData(
        path=path,
        sheet_name=sheet_name,
        headers=tuple(column.column_id for column in dataset.columns),
        display_headers={column.column_id: column.label for column in dataset.columns},
        recipients=tuple(
            Recipient(
                source_row=row.source_row or index,
                values=row.values,
            )
            for index, row in enumerate(dataset.rows, start=2)
        ),
    )


def _compatibility_error(
    error: ExcelImportError,
    path: Path,
    sheet_name: str | None = None,
) -> WorkbookInputError:
    selected_sheet = error.sheet_name or sheet_name or ""
    if error.code == "import.excel.sheet_missing":
        message = f"Worksheet '{selected_sheet}' was not found in '{path.name}'."
    elif error.code == "import.excel.duplicate_header":
        message = "Two column headers resolve to the same field name. Rename one column."
    elif error.code == "import.excel.blank_header":
        message = f"Column {error.cell or ''} has a blank column header."
    elif error.code == "import.excel.formula_cache_missing":
        message = (
            "A formula has no saved result. Open the workbook in Excel, "
            "recalculate it, save it, and import again."
        )
    elif error.code == "import.excel.merged_data_cells":
        message = "Merged cells overlap the recipient data area. Unmerge them and retry."
    else:
        message = (
            f"Excel workbook '{path.name}' could not be read. "
            "It may be damaged or not a valid .xlsx file."
        )
    return WorkbookInputError(message, code=error.code)
