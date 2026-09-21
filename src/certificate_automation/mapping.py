"""Automatic and user-selected workbook-to-template field mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping

from certificate_automation.dataset import Column, DatasetError, TabularDataset
from certificate_automation.domain import Recipient
from certificate_automation.workbook import normalize_field_name


class MappingPlanError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MappingEvaluationError(MappingPlanError):
    def __init__(
        self,
        code: str,
        *,
        row_id: str | None = None,
        column_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.row_id = row_id
        self.column_id = column_id


@dataclass(frozen=True, slots=True)
class ColumnValue:
    column_id: str
    kind: ClassVar[str] = "column"

    def __post_init__(self) -> None:
        if not self.column_id:
            raise MappingPlanError("mapping.column_missing")

    def parameters(self) -> dict[str, object]:
        return {"column_id": self.column_id}


@dataclass(frozen=True, slots=True)
class FixedValue:
    value: str
    kind: ClassVar[str] = "fixed"

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", str(self.value))

    def parameters(self) -> dict[str, object]:
        return {"value": self.value}


@dataclass(frozen=True, slots=True)
class SequenceValue:
    start: int = 1
    step: int = 1
    width: int = 1
    prefix: str = ""
    suffix: str = ""
    kind: ClassVar[str] = "sequence"

    def __post_init__(self) -> None:
        if self.width < 1 or self.step == 0:
            raise MappingPlanError("mapping.invalid_sequence")

    def parameters(self) -> dict[str, object]:
        return {
            "start": self.start,
            "step": self.step,
            "width": self.width,
            "prefix": self.prefix,
            "suffix": self.suffix,
        }


@dataclass(frozen=True, slots=True)
class SourceRowValue:
    kind: ClassVar[str] = "source_row"

    def parameters(self) -> dict[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class FormattedDateValue:
    source: ColumnValue
    input_format: str
    output_format: str
    kind: ClassVar[str] = "formatted_date"

    def __post_init__(self) -> None:
        if not isinstance(self.source, ColumnValue) or not self.output_format:
            raise MappingPlanError("mapping.invalid_date_format")

    def parameters(self) -> dict[str, object]:
        return {
            "source": {"type": self.source.kind, **self.source.parameters()},
            "input_format": self.input_format,
            "output_format": self.output_format,
        }


@dataclass(frozen=True, slots=True)
class JoinValue:
    column_ids: tuple[str, ...]
    separator: str = " "
    kind: ClassVar[str] = "join"

    def __post_init__(self) -> None:
        object.__setattr__(self, "column_ids", tuple(self.column_ids))
        if not self.column_ids or any(not item for item in self.column_ids):
            raise MappingPlanError("mapping.invalid_join")

    def parameters(self) -> dict[str, object]:
        return {"column_ids": list(self.column_ids), "separator": self.separator}


MappingSource = (
    ColumnValue
    | FixedValue
    | SequenceValue
    | SourceRowValue
    | FormattedDateValue
    | JoinValue
)


@dataclass(frozen=True, slots=True)
class MappingPlan:
    sources: Mapping[str, MappingSource]

    def __post_init__(self) -> None:
        copied = dict(self.sources)
        if any(not str(name).strip() for name in copied):
            raise MappingPlanError("mapping.blank_placeholder")
        allowed = (
            ColumnValue,
            FixedValue,
            SequenceValue,
            SourceRowValue,
            FormattedDateValue,
            JoinValue,
        )
        if any(not isinstance(source, allowed) for source in copied.values()):
            raise MappingPlanError("mapping.unknown_source_type")
        object.__setattr__(self, "sources", MappingProxyType(copied))

    def unresolved(self, placeholders: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in placeholders if name not in self.sources)

    def to_json(self) -> dict[str, object]:
        return {
            name: {"type": source.kind, **source.parameters()}
            for name, source in sorted(self.sources.items())
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "MappingPlan":
        return cls(
            {
                str(name): mapping_source_from_json(record)
                for name, record in value.items()
            }
        )


@dataclass(frozen=True, slots=True)
class MappingSuggestion:
    placeholder: str
    status: Literal["exact", "suggested", "unresolved"]
    source: ColumnValue | None
    score: float = 0.0


def mapping_source_from_json(value: object) -> MappingSource:
    if not isinstance(value, Mapping):
        raise MappingPlanError("mapping.invalid_json")
    kind = value.get("type")
    try:
        if kind == "column":
            return ColumnValue(str(value["column_id"]))
        if kind == "fixed":
            return FixedValue(str(value.get("value", "")))
        if kind == "sequence":
            return SequenceValue(
                int(value.get("start", 1)),
                int(value.get("step", 1)),
                int(value.get("width", 1)),
                str(value.get("prefix", "")),
                str(value.get("suffix", "")),
            )
        if kind == "source_row":
            return SourceRowValue()
        if kind == "formatted_date":
            source = mapping_source_from_json(value["source"])
            if not isinstance(source, ColumnValue):
                raise MappingPlanError("mapping.invalid_date_source")
            return FormattedDateValue(
                source,
                str(value.get("input_format", "")),
                str(value["output_format"]),
            )
        if kind == "join":
            return JoinValue(
                tuple(str(item) for item in value["column_ids"]),
                str(value.get("separator", " ")),
            )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, MappingPlanError):
            raise
        raise MappingPlanError("mapping.invalid_json") from error
    raise MappingPlanError("mapping.unknown_source_type")


def evaluate_plan(
    plan: MappingPlan,
    dataset: TabularDataset,
    row_id: str,
) -> dict[str, str]:
    row = dataset.row(row_id)
    return {
        placeholder: _evaluate_source(source, dataset, row_id, row.source_row)
        for placeholder, source in plan.sources.items()
    }


def _evaluate_source(
    source: MappingSource,
    dataset: TabularDataset,
    row_id: str,
    source_row: int | None,
) -> str:
    row = dataset.row(row_id)
    try:
        if isinstance(source, ColumnValue):
            return row.value(source.column_id)
        if isinstance(source, FixedValue):
            return source.value
        if isinstance(source, SequenceValue):
            position = dataset.order.index(row_id)
            number = source.start + position * source.step
            return f"{source.prefix}{number:0{source.width}d}{source.suffix}"
        if isinstance(source, SourceRowValue):
            return "" if source_row is None else str(source_row)
        if isinstance(source, JoinValue):
            return source.separator.join(row.value(item) for item in source.column_ids)
        if isinstance(source, FormattedDateValue):
            text = row.value(source.source.column_id).strip()
            if not source.input_format:
                if _looks_like_ambiguous_numeric_date(text):
                    raise MappingEvaluationError(
                        "mapping.date_ambiguous",
                        row_id=row_id,
                        column_id=source.source.column_id,
                    )
                raise MappingEvaluationError(
                    "mapping.date_format_required",
                    row_id=row_id,
                    column_id=source.source.column_id,
                )
            try:
                parsed = datetime.strptime(text, source.input_format)
            except ValueError as error:
                raise MappingEvaluationError(
                    "mapping.date_invalid",
                    row_id=row_id,
                    column_id=source.source.column_id,
                ) from error
            return parsed.strftime(source.output_format)
    except DatasetError as error:
        column_id = getattr(source, "column_id", None)
        raise MappingEvaluationError(
            "mapping.unknown_column",
            row_id=row_id,
            column_id=column_id,
        ) from error
    raise MappingEvaluationError("mapping.unknown_source_type", row_id=row_id)


def _looks_like_ambiguous_numeric_date(value: str) -> bool:
    parts = value.split("/")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return False
    first, second = (int(parts[0]), int(parts[1]))
    return 1 <= first <= 12 and 1 <= second <= 12


def suggest_mapping_plan(
    columns: tuple[Column, ...],
    placeholders: tuple[str, ...],
) -> Mapping[str, MappingSuggestion]:
    """Suggest columns while clearly separating exact and review-required matches."""

    result: dict[str, MappingSuggestion] = {}
    normalized = {
        column.column_id: normalize_field_name(column.label) for column in columns
    }
    for placeholder in placeholders:
        target = normalize_field_name(placeholder)
        exact = [
            column
            for column in columns
            if target in {normalize_field_name(column.column_id), normalized[column.column_id]}
        ]
        if len(exact) == 1:
            result[placeholder] = MappingSuggestion(
                placeholder, "exact", ColumnValue(exact[0].column_id), 1.0
            )
            continue
        scored = sorted(
            [
                (
                    max(
                        SequenceMatcher(
                            None,
                            target,
                            normalize_field_name(column.column_id),
                        ).ratio(),
                        SequenceMatcher(
                            None,
                            target,
                            normalized[column.column_id],
                        ).ratio(),
                    ),
                    column,
                )
                for column in columns
            ],
            key=lambda item: (item[0], item[1].column_id),
        )
        if scored and scored[-1][0] >= 0.55 and (
            len(scored) == 1 or scored[-1][0] > scored[-2][0]
        ):
            score, column = scored[-1]
            result[placeholder] = MappingSuggestion(
                placeholder, "suggested", ColumnValue(column.column_id), score
            )
        else:
            result[placeholder] = MappingSuggestion(placeholder, "unresolved", None)
    return MappingProxyType(result)


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
