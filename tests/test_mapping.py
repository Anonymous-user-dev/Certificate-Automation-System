from __future__ import annotations

from datetime import datetime, timezone

import pytest

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.domain import Recipient
from certificate_automation.mapping import (
    ColumnValue,
    FixedValue,
    FormattedDateValue,
    JoinValue,
    MappingEvaluationError,
    MappingPlan,
    SequenceValue,
    SourceRowValue,
    evaluate_plan,
    suggest_mapping_plan,
    MappingSelection,
    suggest_mappings,
)


def _dataset() -> TabularDataset:
    return TabularDataset(
        (
            Column("given", "Given Name"),
            Column("family", "Family Name"),
            Column("date", "Award Date"),
        ),
        (
            DataRow("row-1", 2, {"given": "Ana", "family": "García", "date": "2026-09-19"}),
            DataRow("row-2", 3, {"given": "Chen", "family": "Wei", "date": "2026-09-20"}),
        ),
        SourceSnapshot(
            "manual",
            "Recipients",
            None,
            "a" * 64,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        ),
    )


def test_suggests_separator_insensitive_mapping():
    selection = suggest_mappings(
        ("full_name", "award_type"),
        ("FULL-NAME", "AWARD TYPE"),
    )

    assert selection.columns == {
        "FULL-NAME": "full_name",
        "AWARD TYPE": "award_type",
    }


def test_unmatched_placeholder_is_not_guessed():
    selection = suggest_mappings(("student",), ("FULL_NAME",))

    assert selection.columns["FULL_NAME"] is None


def test_mapping_can_use_a_fixed_value():
    selection = MappingSelection(
        columns={"FULL_NAME": "full_name", "SIGNATORY": None},
        fixed_values={"SIGNATORY": "Dr. Rivera"},
    )
    recipient = Recipient(2, {"full_name": "Ana García"})

    assert selection.replacements_for(recipient) == {
        "FULL_NAME": "Ana García",
        "SIGNATORY": "Dr. Rivera",
    }


def test_explicit_column_takes_precedence_over_fixed_value():
    selection = MappingSelection(
        columns={"AWARD": "award"},
        fixed_values={"AWARD": "Default Award"},
    )
    recipient = Recipient(2, {"award": "Gold"})

    assert selection.replacements_for(recipient)["AWARD"] == "Gold"


def test_typed_mapping_evaluates_all_six_sources_deterministically():
    dataset = _dataset()
    plan = MappingPlan(
        {
            "FULL_NAME": JoinValue(("given", "family"), " "),
            "CERT_NO": SequenceValue(41, 1, 4, "C-", ""),
            "DATE": FormattedDateValue(ColumnValue("date"), "%Y-%m-%d", "%d %B %Y"),
            "AWARD": FixedValue("Gold"),
            "SOURCE_ROW": SourceRowValue(),
            "GIVEN": ColumnValue("given"),
        }
    )

    assert evaluate_plan(plan, dataset, "row-2") == {
        "FULL_NAME": "Chen Wei",
        "CERT_NO": "C-0042",
        "DATE": "20 September 2026",
        "AWARD": "Gold",
        "SOURCE_ROW": "3",
        "GIVEN": "Chen",
    }


def test_sequence_follows_generation_order_not_row_storage_order():
    dataset = _dataset().with_order(("row-2", "row-1"))
    plan = MappingPlan({"N": SequenceValue(1, 1, 2, "", "")})

    assert evaluate_plan(plan, dataset, "row-2")["N"] == "01"
    assert evaluate_plan(plan, dataset, "row-1")["N"] == "02"


def test_mapping_plan_json_round_trip_preserves_closed_types():
    plan = MappingPlan(
        {
            "A": ColumnValue("given"),
            "B": FixedValue("固定"),
            "C": SequenceValue(7, 2, 3, "X", "Z"),
            "D": SourceRowValue(),
            "E": FormattedDateValue(ColumnValue("date"), "%Y-%m-%d", "%Y"),
            "F": JoinValue(("given", "family"), " / "),
        }
    )

    assert MappingPlan.from_json(plan.to_json()) == plan


def test_invalid_or_ambiguous_dates_are_structured_errors():
    dataset = _dataset().with_cell("row-1", "date", "01/02/2026")
    plan = MappingPlan({"DATE": FormattedDateValue(ColumnValue("date"), "", "%Y-%m-%d")})

    with pytest.raises(MappingEvaluationError) as caught:
        evaluate_plan(plan, dataset, "row-1")

    assert caught.value.code == "mapping.date_ambiguous"
    assert caught.value.column_id == "date"


def test_mapping_suggestions_distinguish_exact_suggested_and_unresolved():
    suggestions = suggest_mapping_plan(
        (Column("full_name", "Full Name"), Column("award_title", "Award Title")),
        ("FULL-NAME", "AWARD", "DATE"),
    )

    assert suggestions["FULL-NAME"].status == "exact"
    assert suggestions["AWARD"].status == "suggested"
    assert suggestions["DATE"].status == "unresolved"
