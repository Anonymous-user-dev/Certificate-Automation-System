from __future__ import annotations

from certificate_automation.domain import Recipient
from certificate_automation.mapping import MappingSelection, suggest_mappings


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

