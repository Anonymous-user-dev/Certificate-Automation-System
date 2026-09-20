"""Source-independent immutable tabular data records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType


class DatasetError(ValueError):
    """The canonical table violates an invariant."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_column_id(value: str) -> str:
    """Return a stable, Unicode-aware identifier for a displayed header."""

    normalized = re.sub(r"[\W_]+", "_", str(value).strip().casefold())
    return normalized.strip("_")


@dataclass(frozen=True, slots=True)
class Column:
    column_id: str
    label: str

    def __post_init__(self) -> None:
        if not self.column_id or not self.label.strip():
            raise DatasetError("dataset.blank_column")


@dataclass(frozen=True, slots=True)
class DataRow:
    row_id: str
    source_row: int | None
    values: Mapping[str, str]
    display_values: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.row_id:
            raise DatasetError("dataset.blank_row_id")
        normalized = {key: str(value) for key, value in self.values.items()}
        displayed = (
            normalized
            if self.display_values is None
            else {key: str(value) for key, value in self.display_values.items()}
        )
        object.__setattr__(self, "values", MappingProxyType(normalized))
        object.__setattr__(self, "display_values", MappingProxyType(dict(displayed)))

    def value(self, column_id: str) -> str:
        try:
            return self.values[column_id]
        except KeyError as error:
            raise DatasetError("dataset.unknown_column") from error

    def with_value(self, column_id: str, value: str) -> "DataRow":
        if column_id not in self.values:
            raise DatasetError("dataset.unknown_column")
        normalized = dict(self.values)
        displayed = dict(self.display_values or {})
        normalized[column_id] = str(value)
        displayed[column_id] = str(value)
        return replace(self, values=normalized, display_values=displayed)


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    kind: str
    label: str
    path: Path | None
    sha256: str
    imported_at: datetime
    options: Mapping[str, str | bool | int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind or not self.label:
            raise DatasetError("dataset.invalid_source")
        object.__setattr__(self, "path", Path(self.path) if self.path else None)
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class TabularDataset:
    columns: tuple[Column, ...]
    rows: tuple[DataRow, ...]
    source: SourceSnapshot
    revision: int = 0
    order: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        columns = tuple(self.columns)
        rows = tuple(self.rows)
        column_ids = tuple(column.column_id for column in columns)
        row_ids = tuple(row.row_id for row in rows)
        if len(set(column_ids)) != len(column_ids):
            raise DatasetError("dataset.duplicate_column_id")
        if len(set(row_ids)) != len(row_ids):
            raise DatasetError("dataset.duplicate_row_id")
        expected_columns = set(column_ids)
        for row in rows:
            if set(row.values) != expected_columns or set(row.display_values or {}) != expected_columns:
                raise DatasetError("dataset.non_rectangular")
        order = tuple(self.order) if self.order else row_ids
        if len(order) != len(row_ids) or set(order) != set(row_ids):
            raise DatasetError("dataset.invalid_order")
        if self.revision < 0:
            raise DatasetError("dataset.invalid_revision")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "order", order)

    def row(self, row_id: str) -> DataRow:
        for row in self.rows:
            if row.row_id == row_id:
                return row
        raise DatasetError("dataset.unknown_row")

    def with_cell(self, row_id: str, column_id: str, value: str) -> "TabularDataset":
        self.row(row_id)
        if column_id not in {column.column_id for column in self.columns}:
            raise DatasetError("dataset.unknown_column")
        rows = tuple(
            row.with_value(column_id, value) if row.row_id == row_id else row
            for row in self.rows
        )
        return replace(self, rows=rows, revision=self.revision + 1)

    def with_rows(self, rows: tuple[DataRow, ...]) -> "TabularDataset":
        new_ids = tuple(row.row_id for row in rows)
        return replace(
            self,
            rows=tuple(rows),
            order=new_ids,
            revision=self.revision + 1,
        )

    def with_columns(self, columns: tuple[Column, ...]) -> "TabularDataset":
        return replace(
            self,
            columns=tuple(columns),
            revision=self.revision + 1,
        )

    def with_order(self, order: tuple[str, ...]) -> "TabularDataset":
        if len(order) != len(self.rows) or set(order) != {
            row.row_id for row in self.rows
        }:
            raise DatasetError("dataset.invalid_order")
        return replace(self, order=tuple(order), revision=self.revision + 1)

    def to_json(self) -> dict[str, object]:
        return {
            "columns": [
                {"column_id": column.column_id, "label": column.label}
                for column in self.columns
            ],
            "rows": [
                {
                    "row_id": row.row_id,
                    "source_row": row.source_row,
                    "values": dict(row.values),
                    "display_values": dict(row.display_values or {}),
                }
                for row in self.rows
            ],
            "source": {
                "kind": self.source.kind,
                "label": self.source.label,
                "path": str(self.source.path) if self.source.path else None,
                "sha256": self.source.sha256,
                "imported_at": self.source.imported_at.isoformat(),
                "options": dict(self.source.options),
            },
            "revision": self.revision,
            "order": list(self.order),
        }

    def canonical_sha256(self) -> str:
        payload = json.dumps(
            self.to_json(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()
