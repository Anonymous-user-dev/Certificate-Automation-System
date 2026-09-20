from hashlib import sha256

import pytest
from openpyxl import Workbook

from certificate_automation.importers.excel import (
    ExcelImportError,
    import_excel,
    inspect_excel,
)


def _save_workbook(tmp_path, configure, name="recipients.xlsx"):
    path = tmp_path / name
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Recipients"
    configure(workbook, worksheet)
    workbook.save(path)
    workbook.close()
    return path


def test_excel_import_builds_canonical_unicode_dataset_without_modifying_source(tmp_path):
    path = _save_workbook(
        tmp_path,
        lambda _book, sheet: (
            sheet.append(["Full Name", "Award"]),
            sheet.append(["李明", "优秀奖"]),
        ),
    )
    original = path.read_bytes()

    dataset = import_excel(path, "Recipients")

    assert tuple(column.column_id for column in dataset.columns) == ("full_name", "award")
    assert dataset.row("row-2").value("full_name") == "李明"
    assert dataset.row("row-2").display_values["award"] == "优秀奖"
    assert dataset.source.sha256 == sha256(original).hexdigest()
    assert path.read_bytes() == original


def test_excel_formula_without_cached_value_is_rejected(tmp_path):
    path = _save_workbook(
        tmp_path,
        lambda _book, sheet: (
            sheet.append(["Full Name", "Calculated"]),
            sheet.append(["Ana", "=1+1"]),
        ),
    )

    with pytest.raises(ExcelImportError) as caught:
        import_excel(path, "Recipients")

    assert caught.value.code == "import.excel.formula_cache_missing"
    assert caught.value.cell == "B2"


def test_excel_reports_hidden_data_before_import(tmp_path):
    def configure(_book, sheet):
        sheet.append(["Full Name", "Award"])
        sheet.append(["Ana", "Gold"])
        sheet.append(["Bea", "Silver"])
        sheet.row_dimensions[3].hidden = True
        sheet.column_dimensions["B"].hidden = True

    path = _save_workbook(tmp_path, configure)

    inspection = inspect_excel(path, "Recipients")

    assert inspection.hidden_rows == (3,)
    assert inspection.hidden_columns == ("B",)
    assert inspection.requires_hidden_data_choice is True


def test_hidden_rows_are_excluded_or_included_only_by_explicit_choice(tmp_path):
    def configure(_book, sheet):
        sheet.append(["Full Name"])
        sheet.append(["Ana"])
        sheet.append(["Hidden"])
        sheet.row_dimensions[3].hidden = True

    path = _save_workbook(tmp_path, configure)

    visible = import_excel(path, "Recipients", include_hidden=False)
    complete = import_excel(path, "Recipients", include_hidden=True)

    assert tuple(row.value("full_name") for row in visible.rows) == ("Ana",)
    assert tuple(row.value("full_name") for row in complete.rows) == ("Ana", "Hidden")


def test_excel_rejects_merged_cells_intersecting_data(tmp_path):
    def configure(_book, sheet):
        sheet.append(["Full Name", "Award"])
        sheet.append(["Ana", "Gold"])
        sheet.merge_cells("A2:B2")

    path = _save_workbook(tmp_path, configure)

    with pytest.raises(ExcelImportError) as caught:
        import_excel(path, "Recipients")

    assert caught.value.code == "import.excel.merged_data_cells"
    assert caught.value.ranges == ("A2:B2",)


def test_duplicate_headers_and_missing_sheet_have_stable_codes(tmp_path):
    duplicate = _save_workbook(
        tmp_path,
        lambda _book, sheet: (
            sheet.append(["Full Name", "full_name"]),
            sheet.append(["Ana", "Other"]),
        ),
        name="duplicate.xlsx",
    )

    with pytest.raises(ExcelImportError) as duplicate_error:
        import_excel(duplicate, "Recipients")
    with pytest.raises(ExcelImportError) as sheet_error:
        import_excel(duplicate, "Missing")

    assert duplicate_error.value.code == "import.excel.duplicate_header"
    assert sheet_error.value.code == "import.excel.sheet_missing"
