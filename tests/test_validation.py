from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from certificate_automation.domain import Recipient
from certificate_automation.filenames import MAX_STEM_LENGTH, RESERVED_NAMES, safe_stem
from certificate_automation.mapping import MappingSelection
from certificate_automation.template import Placeholder, TemplateInspection
from certificate_automation.validation import validate_preflight
from certificate_automation.workbook import WorkbookData


def _inputs(tmp_path: Path, *names: str):
    workbook_path = tmp_path / "students.xlsx"
    template_path = tmp_path / "certificate.docx"
    workbook_path.write_bytes(b"workbook source")
    template_path.write_bytes(b"template source")
    destination = tmp_path / "output"
    destination.mkdir()
    workbook = WorkbookData(
        path=workbook_path,
        sheet_name="Students",
        headers=("full_name", "award"),
        display_headers={"full_name": "Full Name", "award": "Award"},
        recipients=tuple(
            Recipient(index, {"full_name": name, "award": "Gold"})
            for index, name in enumerate(names or ("Ana García",), start=2)
        ),
    )
    template = TemplateInspection(
        path=template_path,
        placeholders=(
            Placeholder("FULL_NAME", 1, ("word/document.xml",)),
            Placeholder("AWARD", 1, ("word/document.xml",)),
        ),
    )
    mappings = MappingSelection(
        columns={"FULL_NAME": "full_name", "AWARD": "award"}
    )
    return workbook, template, mappings, destination


@pytest.mark.parametrize("name", ["CON", "con.txt", "AUX", "NUL", "COM1", "Lpt9"])
def test_reserved_windows_names_are_rewritten(name):
    assert safe_stem(name).casefold().split(".")[0] not in RESERVED_NAMES


def test_filename_replaces_unsafe_characters_and_preserves_unicode():
    assert safe_stem(' Ana García: Cohort/1? ') == "Ana_García_Cohort_1"


def test_long_filename_is_bounded_and_stable():
    first = safe_stem("A" * 300)
    second = safe_stem("A" * 300)

    assert first == second
    assert len(first) <= MAX_STEM_LENGTH
    assert first.endswith("-4daeb9ac")


def test_valid_preflight_plans_one_filename_per_recipient(tmp_path):
    workbook, template, mappings, destination = _inputs(
        tmp_path,
        "Ana García",
        "李明",
    )

    report = validate_preflight(workbook, template, mappings, destination)

    assert report.ready is True
    assert report.filename_stems == {2: "Ana_García", 3: "李明"}
    assert report.issues == ()


def test_duplicate_output_names_block_batch(tmp_path):
    workbook, template, mappings, destination = _inputs(tmp_path, "Ana", " ana ")

    report = validate_preflight(workbook, template, mappings, destination)

    assert any(
        issue.code == "validation.duplicate_output_filename" and issue.blocking
        for issue in report.issues
    )


def test_missing_mapping_and_blank_value_are_both_reported(tmp_path):
    workbook, template, mappings, destination = _inputs(tmp_path, "")
    mappings = MappingSelection(columns={"FULL_NAME": "full_name", "AWARD": None})

    report = validate_preflight(workbook, template, mappings, destination)

    assert {issue.code for issue in report.issues} >= {
        "validation.unresolved_placeholder",
        "validation.blank_mapped_value",
    }
    assert report.ready is False


def test_unknown_mapped_column_is_reported(tmp_path):
    workbook, template, _, destination = _inputs(tmp_path)
    mappings = MappingSelection(
        columns={"FULL_NAME": "student_name", "AWARD": "award"}
    )

    report = validate_preflight(workbook, template, mappings, destination)

    assert any(issue.code == "validation.unknown_workbook_column" for issue in report.issues)


def test_duplicate_normalized_recipient_is_reported(tmp_path):
    workbook, template, mappings, destination = _inputs(tmp_path, "Ana", " ANA ")

    report = validate_preflight(workbook, template, mappings, destination)

    assert any(issue.code == "validation.duplicate_recipient" for issue in report.issues)


def test_excessively_long_mapped_value_is_blocking(tmp_path):
    workbook, template, mappings, destination = _inputs(tmp_path, "A" * 501)

    report = validate_preflight(workbook, template, mappings, destination)

    assert any(issue.code == "validation.value_too_long" and issue.blocking for issue in report.issues)


def test_empty_workbook_and_template_without_placeholders_are_reported(tmp_path):
    workbook, template, mappings, destination = _inputs(tmp_path)
    workbook = replace(workbook, recipients=())
    template = replace(template, placeholders=())
    mappings = MappingSelection(columns={})

    report = validate_preflight(workbook, template, mappings, destination)

    assert {issue.code for issue in report.issues} >= {
        "validation.no_recipients",
        "validation.no_placeholders",
    }


def test_full_name_fixed_value_collision_is_reported(tmp_path):
    workbook, template, _, destination = _inputs(tmp_path, "Ana", "Bea")
    mappings = MappingSelection(
        columns={"FULL_NAME": None, "AWARD": "award"},
        fixed_values={"FULL_NAME": "One Certificate"},
    )

    report = validate_preflight(workbook, template, mappings, destination)

    assert any(issue.code == "validation.duplicate_output_filename" for issue in report.issues)


def test_filename_falls_back_to_source_row_without_full_name_placeholder(tmp_path):
    workbook, template, _, destination = _inputs(tmp_path, "Ana")
    template = replace(
        template,
        placeholders=(Placeholder("AWARD", 1, ("word/document.xml",)),),
    )
    mappings = MappingSelection(columns={"AWARD": "award"})

    report = validate_preflight(workbook, template, mappings, destination)

    assert report.filename_stems == {2: "certificate-row-2"}


def test_destination_that_is_a_file_is_rejected(tmp_path):
    workbook, template, mappings, _ = _inputs(tmp_path)
    destination = tmp_path / "not-a-folder"
    destination.write_text("occupied", encoding="utf-8")

    report = validate_preflight(workbook, template, mappings, destination)

    assert any(issue.code == "validation.destination_not_directory" for issue in report.issues)


def test_destination_cannot_be_a_source_file(tmp_path):
    workbook, template, mappings, _ = _inputs(tmp_path)

    report = validate_preflight(workbook, template, mappings, workbook.path)

    assert any(issue.code == "validation.destination_is_source" for issue in report.issues)
