from __future__ import annotations

from datetime import date, datetime, time

import pytest

from certificate_automation.workbook import (
    WorkbookInputError,
    list_worksheets,
    load_workbook_data,
    normalize_field_name,
)
from fixtures import xlsx_factory


def test_loads_rows_and_normalizes_headers(xlsx_factory):
    path = xlsx_factory(
        [["Full Name", "Award-Type"], [" Ana ", "Gold"], [None, None]]
    )

    data = load_workbook_data(path, "Students")

    assert data.headers == ("full_name", "award_type")
    assert data.display_headers == {
        "full_name": "Full Name",
        "award_type": "Award-Type",
    }
    assert len(data.recipients) == 1
    assert data.recipients[0].values == {
        "full_name": "Ana",
        "award_type": "Gold",
    }
    assert data.recipients[0].source_row == 2


def test_lists_worksheets_in_workbook_order(xlsx_factory):
    path = xlsx_factory(
        [["Full Name"], ["Ana"]],
        extra_sheets=("Evening Class", "Archive"),
    )

    assert list_worksheets(path) == ("Students", "Evening Class", "Archive")


def test_missing_worksheet_has_plain_language_error(xlsx_factory):
    path = xlsx_factory([["Full Name"], ["Ana"]])

    with pytest.raises(WorkbookInputError, match="Worksheet 'Missing' was not found"):
        load_workbook_data(path, "Missing")


def test_dates_and_times_are_stable_iso_strings(xlsx_factory):
    path = xlsx_factory(
        [
            ["Full Name", "Date", "Created", "Time"],
            [
                "Ana",
                date(2026, 9, 20),
                datetime(2026, 9, 20, 14, 5, 6),
                time(14, 5, 6),
            ],
        ]
    )

    values = load_workbook_data(path, "Students").recipients[0].values

    assert values == {
        "full_name": "Ana",
        "date": "2026-09-20T00:00:00",
        "created": "2026-09-20T14:05:06",
        "time": "14:05:06",
    }


def test_formula_without_cached_value_is_rejected(xlsx_factory):
    path = xlsx_factory([["Full Name", "Calculated"], ["Ana", "=1+1"]])

    with pytest.raises(WorkbookInputError, match="recalculate"):
        load_workbook_data(path, "Students")


def test_duplicate_normalized_headers_are_reported(xlsx_factory):
    path = xlsx_factory([["Full Name", "full_name"], ["Ana", "Other"]])

    with pytest.raises(WorkbookInputError, match="same field name"):
        load_workbook_data(path, "Students")


def test_blank_header_is_rejected(xlsx_factory):
    path = xlsx_factory([["Full Name", None], ["Ana", "Gold"]])

    with pytest.raises(WorkbookInputError, match="blank column header"):
        load_workbook_data(path, "Students")


def test_corrupt_workbook_has_plain_language_error(tmp_path):
    path = tmp_path / "corrupt.xlsx"
    path.write_bytes(b"not an Excel workbook")

    with pytest.raises(WorkbookInputError, match="could not be read"):
        load_workbook_data(path, "Students")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Full Name ", "full_name"),
        ("AWARD-Type", "award_type"),
        ("Certificate   ID", "certificate_id"),
        ("Numéro Étudiant", "numéro_étudiant"),
    ],
)
def test_normalize_field_name_is_separator_and_unicode_aware(value, expected):
    assert normalize_field_name(value) == expected
