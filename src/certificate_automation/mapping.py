"""Automatic and user-selected workbook-to-template field mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from certificate_automation.domain import Recipient
from certificate_automation.workbook import normalize_field_name


@dataclass(frozen=True, slots=True)
class MappingSelection:
    """Selected workbook columns or fixed values for template placeholders."""

    columns: Mapping[str, str | None]
    fixed_values: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", MappingProxyType(dict(self.columns)))
        object.__setattr__(
            self,
            "fixed_values",
            MappingProxyType(dict(self.fixed_values)),
        )

    def replacements_for(self, recipient: Recipient) -> dict[str, str]:
        placeholders = tuple(
            dict.fromkeys((*self.columns.keys(), *self.fixed_values.keys()))
        )
        replacements: dict[str, str] = {}
        for placeholder in placeholders:
            column = self.columns.get(placeholder)
            if column is not None:
                replacements[placeholder] = recipient.values.get(column, "")
            else:
                replacements[placeholder] = self.fixed_values.get(placeholder, "")
        return replacements


def suggest_mappings(
    headers: tuple[str, ...],
    placeholders: tuple[str, ...],
) -> MappingSelection:
    """Select only unambiguous normalized header matches."""

    candidates: dict[str, list[str]] = {}
    for header in headers:
        candidates.setdefault(normalize_field_name(header), []).append(header)

    columns: dict[str, str | None] = {}
    for placeholder in placeholders:
        matches = candidates.get(normalize_field_name(placeholder), [])
        columns[placeholder] = matches[0] if len(matches) == 1 else None
    return MappingSelection(columns=columns)

