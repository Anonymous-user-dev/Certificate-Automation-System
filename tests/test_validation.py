from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.domain import Recipient
from certificate_automation.filenames import MAX_STEM_LENGTH, RESERVED_NAMES, safe_stem
from certificate_automation.history import DuplicatePolicy, HistoryIndex, PublishedBatch
from certificate_automation.mapping import (
    ColumnValue,
    FormattedDateValue,
    MappingPlan,
    MappingSelection,
)
from certificate_automation.output_options import OutputOptions, OutputOptionsError
from certificate_automation.print_readiness import PrintSettings
from decimal import Decimal
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


def test_print_settings_round_trip_with_output_choices(tmp_path):
    settings = PrintSettings(Decimal("612"), Decimal("792"), "portrait", 2)
    choices = OutputOptions(True, True, True, tmp_path, "Awards", ("row-1", "row-2", "row-3"), settings)

    reopened = OutputOptions.from_json(choices.to_json())

    assert reopened == choices
    assert reopened.separator_count == 1


def test_separator_choice_requires_combined_pdf(tmp_path):
    settings = PrintSettings(Decimal("612"), Decimal("792"), "portrait", 2)
    with pytest.raises(OutputOptionsError) as caught:
        OutputOptions(True, False, False, tmp_path, "Awards", ("row-1",), settings)
    assert caught.value.code == "output.separator_requires_combined"


def test_combined_pdf_requires_explicit_valid_print_settings(tmp_path):
    with pytest.raises(OutputOptionsError) as caught:
        OutputOptions(False, False, True, tmp_path, "Awards", ("row-1",))
    assert caught.value.code == "output.print_settings_required"

    with pytest.raises(OutputOptionsError) as reopened:
        OutputOptions.from_json({
            "docx": False, "individual_pdf": False, "combined_pdf": True,
            "destination": str(tmp_path), "batch_name": "Awards", "row_ids": ["row-1"],
        })
    assert reopened.value.code == "output.print_settings_required"


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


def _canonical_dataset(*names: str) -> TabularDataset:
    return TabularDataset(
        (Column("full_name", "Full Name"), Column("date", "Date")),
        tuple(
            DataRow(f"row-{index}", index + 1, {"full_name": name, "date": "2026-09-20"})
            for index, name in enumerate(names, start=1)
        ),
        SourceSnapshot(
            "manual",
            "Recipients",
            None,
            "d" * 64,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        ),
    )


def _typed_template(tmp_path: Path) -> TemplateInspection:
    path = tmp_path / "typed.docx"
    path.write_bytes(b"typed template")
    return TemplateInspection(
        path,
        (
            Placeholder("FULL_NAME", 1, ("word/document.xml",)),
            Placeholder("DATE", 1, ("word/document.xml",)),
        ),
    )


def _typed_options(tmp_path: Path, dataset: TabularDataset) -> OutputOptions:
    destination = tmp_path / "typed-output"
    destination.mkdir()
    return OutputOptions(
        docx=True,
        individual_pdf=False,
        combined_pdf=False,
        destination=destination,
        batch_name="Awards 2026",
        row_ids=dataset.order,
    )


def test_typed_preflight_is_revision_bound_and_uses_stable_row_ids(tmp_path):
    dataset = _canonical_dataset("Ana García", "李明")
    report = validate_preflight(
        dataset,
        _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
    )

    assert report.ready
    assert report.filename_stems == {"row-1": "Ana_García", "row-2": "李明"}
    assert report.dataset_revision == dataset.revision
    assert len(report.template_sha256) == 64


def test_ambiguous_date_blocks_the_exact_source_cell(tmp_path):
    dataset = _canonical_dataset("Ana").with_cell("row-1", "date", "01/02/2026")
    plan = MappingPlan(
        {
            "FULL_NAME": ColumnValue("full_name"),
            "DATE": FormattedDateValue(ColumnValue("date"), "", "%Y-%m-%d"),
        }
    )

    report = validate_preflight(dataset, _typed_template(tmp_path), plan, _typed_options(tmp_path, dataset))
    issue = next(item for item in report.issues if item.code == "mapping.date_ambiguous")

    assert (issue.row_id, issue.column_id) == ("row-1", "date")
    assert report.ready is False


def test_unicode_normalization_filename_collision_blocks_both_rows(tmp_path):
    dataset = _canonical_dataset("José", "Jose\u0301")
    report = validate_preflight(
        dataset,
        _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
    )

    collisions = [item for item in report.issues if item.code == "output.filename_collision"]
    assert {item.row_id for item in collisions} == {"row-1", "row-2"}


def test_selected_identity_duplicate_is_warning_requiring_acknowledgement(tmp_path):
    dataset = _canonical_dataset(" Ana ", "ANA")
    report = validate_preflight(
        dataset, _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
        duplicate_policy=DuplicatePolicy(None, ("full_name",), False),
    )
    matches = [issue for issue in report.issues if issue.code == "validation.identity_duplicate"]
    assert len(matches) == 1
    assert matches[0].row_id == "row-2"
    assert matches[0].severity.value == "warning"


def test_exact_certificate_id_collision_blocks_batch(tmp_path):
    source = _canonical_dataset("Ana", "Bea")
    dataset = replace(source,
        columns=source.columns + (Column("certificate_id", "Certificate ID"),),
        rows=tuple(replace(row, values={**row.values, "certificate_id": "ABC-1"},
                           display_values={**row.display_values, "certificate_id": "ABC-1"})
                   for row in source.rows))
    report = validate_preflight(
        dataset, _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
        duplicate_policy=DuplicatePolicy("certificate_id", ("full_name",), False),
    )
    assert {issue.row_id for issue in report.issues if issue.code == "validation.certificate_id_collision"} == {"row-1", "row-2"}
    assert report.ready is False


def test_unavailable_history_warns_instead_of_reporting_clean(tmp_path):
    dataset = _canonical_dataset("Ana")
    report = validate_preflight(
        dataset, _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
        duplicate_policy=DuplicatePolicy(None, ("full_name",), True),
    )
    assert any(issue.code == "history.unavailable" and issue.severity.value == "warning"
               for issue in report.issues)


def test_history_check_without_identity_fields_is_configuration_error(tmp_path):
    dataset = _canonical_dataset("Ana")
    report = validate_preflight(
        dataset, _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
        duplicate_policy=DuplicatePolicy(None, (), True),
    )
    assert any(issue.code == "validation.history_identity_required" and issue.blocking
               for issue in report.issues)


def test_blank_selected_identity_is_not_silently_skipped(tmp_path):
    dataset = _canonical_dataset("Ana").with_cell("row-1", "full_name", "")
    report = validate_preflight(
        dataset, _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
        duplicate_policy=DuplicatePolicy(None, ("full_name",), True),
    )
    assert any(issue.code == "validation.blank_identity" and issue.blocking
               for issue in report.issues)


def test_historical_identity_match_warns_for_affected_row(tmp_path):
    class MemoryProtector:
        def protect(self, value, *, purpose):
            return value[::-1]
        def unprotect(self, value, *, purpose):
            return value[::-1]

    history = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    history.record(PublishedBatch("old", 1, datetime(2026, 9, 21, tzinfo=timezone.utc), tmp_path / "published"),
                   identities=("Ana",))
    dataset = _canonical_dataset("Ana", "Bea")
    report = validate_preflight(
        dataset, _typed_template(tmp_path),
        MappingPlan({"FULL_NAME": ColumnValue("full_name"), "DATE": ColumnValue("date")}),
        _typed_options(tmp_path, dataset),
        duplicate_policy=DuplicatePolicy(None, ("full_name",), True),
        history_index=history,
    )
    assert [(issue.code, issue.row_id, issue.severity.value) for issue in report.issues
            if issue.code == "validation.history_duplicate"] == [
                ("validation.history_duplicate", "row-1", "warning")]


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"docx": False, "individual_pdf": False, "combined_pdf": False}, "output.none_selected"),
        ({"destination": None}, "output.destination_missing"),
        ({"row_ids": ("row-1", "row-1")}, "output.duplicate_row"),
        ({"combined_pdf": True, "batch_name": "CON"}, "output.invalid_batch_name"),
    ],
)
def test_output_options_reject_unsafe_combinations(tmp_path, kwargs, code):
    values = {
        "docx": True,
        "individual_pdf": False,
        "combined_pdf": False,
        "destination": tmp_path,
        "batch_name": "Awards",
        "row_ids": ("row-1",),
    }
    values.update(kwargs)

    with pytest.raises(OutputOptionsError) as caught:
        OutputOptions(**values)

    assert caught.value.code == code
