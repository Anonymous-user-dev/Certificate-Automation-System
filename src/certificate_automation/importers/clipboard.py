"""Clipboard and manual-table adapters."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
from typing import Literal
from uuid import uuid4

from certificate_automation.dataset import (
    Column,
    DataRow,
    SourceSnapshot,
    TabularDataset,
    normalize_column_id,
)
from certificate_automation.importers.delimited import (
    DelimitedImportError,
    dataset_from_rectangular_rows,
)


class ClipboardImportError(ValueError):
    """Clipboard or manual data cannot be applied safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClipboardInspection:
    mode_candidates: tuple[str, ...]
    mode: str | None
    preview_rows: tuple[tuple[str, ...], ...]
    requires_choice: bool


def inspect_clipboard(text: str) -> ClipboardInspection:
    """Identify tabular paste modes without changing active data."""

    candidates: list[tuple[str, tuple[tuple[str, ...], ...]]] = []
    for mode, delimiter in (("tabs", "\t"), ("csv", ",")):
        try:
            rows = _read_clipboard_rows(text, delimiter)
        except ClipboardImportError:
            continue
        if rows and len(rows[0]) > 1 and all(len(row) == len(rows[0]) for row in rows):
            candidates.append((mode, rows))
    mode = candidates[0][0] if len(candidates) == 1 else None
    preview = (
        candidates[0][1][:10]
        if candidates
        else tuple((line,) for line in text.splitlines()[:10])
    )
    return ClipboardInspection(
        mode_candidates=tuple(candidate for candidate, _rows in candidates),
        mode=mode,
        preview_rows=preview,
        requires_choice=mode is None,
    )


def import_clipboard(
    text: str,
    mode: Literal["tabs", "csv"],
) -> TabularDataset:
    """Import clipboard text after the operator confirms its parse mode."""

    if mode not in ("tabs", "csv"):
        raise ClipboardImportError("import.clipboard.mode_required")
    delimiter = "\t" if mode == "tabs" else ","
    rows = _read_clipboard_rows(text, delimiter)
    encoded = text.encode("utf-8")
    source = SourceSnapshot(
        kind="clipboard",
        label="Clipboard table",
        path=None,
        sha256=sha256(encoded).hexdigest(),
        imported_at=datetime.now(timezone.utc),
        options={"mode": mode},
    )
    try:
        return dataset_from_rectangular_rows(rows, source)
    except DelimitedImportError as error:
        raise ClipboardImportError(
            error.code.replace("import.delimited.", "import.clipboard.")
        ) from error


def append_clipboard(
    dataset: TabularDataset,
    text: str,
    mode: Literal["tabs", "csv"],
) -> TabularDataset:
    """Append rows only when displayed headers match exactly."""

    incoming = import_clipboard(text, mode)
    if tuple(column.label for column in incoming.columns) != tuple(
        column.label for column in dataset.columns
    ):
        raise ClipboardImportError("import.clipboard.header_mismatch")

    incoming_ids = tuple(column.column_id for column in incoming.columns)
    target_ids = tuple(column.column_id for column in dataset.columns)
    remapped: list[DataRow] = []
    for row in incoming.rows:
        values = {
            target_id: row.values[incoming_id]
            for target_id, incoming_id in zip(target_ids, incoming_ids, strict=True)
        }
        display = {
            target_id: (row.display_values or {})[incoming_id]
            for target_id, incoming_id in zip(target_ids, incoming_ids, strict=True)
        }
        remapped.append(
            DataRow(
                row_id=f"pasted-{uuid4().hex}",
                source_row=row.source_row,
                values=values,
                display_values=display,
            )
        )
    return dataset.with_rows(dataset.rows + tuple(remapped))


def create_manual_dataset(column_labels: tuple[str, ...]) -> TabularDataset:
    """Create an empty local dataset with explicitly named columns."""

    columns: list[Column] = []
    seen: set[str] = set()
    for label in column_labels:
        column_id = normalize_column_id(label)
        if not column_id:
            raise ClipboardImportError("import.manual.blank_header")
        if column_id in seen:
            raise ClipboardImportError("import.manual.duplicate_header")
        seen.add(column_id)
        columns.append(Column(column_id, label.strip()))
    if not columns:
        raise ClipboardImportError("import.manual.no_columns")
    fingerprint = "\x1f".join(column.label for column in columns).encode("utf-8")
    source = SourceSnapshot(
        kind="manual",
        label="Untitled table",
        path=None,
        sha256=sha256(fingerprint).hexdigest(),
        imported_at=datetime.now(timezone.utc),
        options={},
    )
    return TabularDataset(tuple(columns), (), source)


def _read_clipboard_rows(text: str, delimiter: str) -> tuple[tuple[str, ...], ...]:
    if not text or "\x00" in text:
        raise ClipboardImportError("import.clipboard.empty_or_invalid")
    try:
        return tuple(
            tuple(row)
            for row in csv.reader(
                io.StringIO(text, newline=""),
                delimiter=delimiter,
                strict=True,
            )
        )
    except csv.Error as error:
        raise ClipboardImportError("import.clipboard.malformed") from error
