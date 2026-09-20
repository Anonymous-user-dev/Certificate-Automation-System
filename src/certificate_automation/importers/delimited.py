"""Lossless CSV and TSV inspection and import."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
from pathlib import Path
from types import MappingProxyType
from typing import Iterable

from certificate_automation.dataset import (
    Column,
    DataRow,
    SourceSnapshot,
    TabularDataset,
    normalize_column_id,
)


SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "cp1251", "gb18030")
SUPPORTED_DELIMITERS = (",", "\t", ";")


class DelimitedImportError(ValueError):
    """Delimited text cannot be imported without losing or guessing data."""

    def __init__(
        self,
        code: str,
        *,
        row_number: int | None = None,
        parameters: dict[str, str | int] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.row_number = row_number
        self.parameters = MappingProxyType(dict(parameters or {}))


@dataclass(frozen=True, slots=True)
class DelimitedInspection:
    encoding_candidates: tuple[str, ...]
    delimiter_candidates: tuple[str, ...]
    encoding: str | None
    delimiter: str | None
    preview_rows: tuple[tuple[str, ...], ...]
    requires_choice: bool


def inspect_delimited(path: Path) -> DelimitedInspection:
    """Inspect encoding and delimiter while preserving ambiguous choices."""

    path = Path(path)
    raw = path.read_bytes()
    if not raw:
        raise DelimitedImportError("import.delimited.empty")
    if b"\x00" in raw and not (raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff")):
        raise DelimitedImportError("import.delimited.nul_byte")

    decoded = _decode_candidates(raw)
    encoding_candidates = tuple(encoding for encoding, _text in decoded)
    delimiter_candidates = _delimiter_candidates(
        tuple(text for _encoding, text in decoded),
        preferred="\t" if path.suffix.casefold() == ".tsv" else ",",
    )
    delimiter = _select_delimiter(delimiter_candidates, path.suffix.casefold())
    encoding = _select_encoding(decoded, delimiter)
    preview_text = _text_for_encoding(decoded, encoding) if encoding else decoded[0][1]
    preview_delimiter = delimiter or (delimiter_candidates[0] if delimiter_candidates else None)
    preview = (
        _read_rows(preview_text, preview_delimiter)[:10]
        if preview_delimiter is not None
        else tuple((line,) for line in preview_text.splitlines()[:10])
    )
    return DelimitedInspection(
        encoding_candidates=encoding_candidates,
        delimiter_candidates=delimiter_candidates,
        encoding=encoding,
        delimiter=delimiter,
        preview_rows=preview,
        requires_choice=encoding is None or delimiter is None,
    )


def import_delimited(
    path: Path,
    encoding: str | None,
    delimiter: str | None,
) -> TabularDataset:
    """Decode and import using choices that are explicit and reversible."""

    if encoding not in SUPPORTED_ENCODINGS or delimiter not in SUPPORTED_DELIMITERS:
        raise DelimitedImportError("import.delimited.choice_required")
    path = Path(path)
    raw = path.read_bytes()
    if not raw:
        raise DelimitedImportError("import.delimited.empty")
    if b"\x00" in raw and encoding != "utf-16":
        raise DelimitedImportError("import.delimited.nul_byte")
    try:
        text = raw.decode(encoding, errors="strict")
    except UnicodeDecodeError as error:
        raise DelimitedImportError(
            "import.delimited.decode_failed",
            parameters={"encoding": encoding},
        ) from error
    if "\x00" in text:
        raise DelimitedImportError("import.delimited.nul_byte")
    rows = _read_rows(text, delimiter)
    source = SourceSnapshot(
        kind="delimited",
        label=path.name,
        path=path,
        sha256=sha256(raw).hexdigest(),
        imported_at=datetime.now(timezone.utc),
        options={"encoding": encoding, "delimiter": delimiter},
    )
    return dataset_from_rectangular_rows(rows, source)


def dataset_from_rectangular_rows(
    rows: Iterable[tuple[str, ...] | list[str]],
    source: SourceSnapshot,
) -> TabularDataset:
    """Build a canonical dataset from already decoded table rows."""

    materialized = tuple(tuple(str(value) for value in row) for row in rows)
    if not materialized:
        raise DelimitedImportError("import.delimited.empty")
    width = len(materialized[0])
    if width == 0:
        raise DelimitedImportError("import.delimited.empty")
    for row_number, row in enumerate(materialized, start=1):
        if len(row) != width:
            raise DelimitedImportError(
                "import.delimited.inconsistent_width",
                row_number=row_number,
                parameters={
                    "row": row_number,
                    "expected": width,
                    "actual": len(row),
                },
            )

    columns: list[Column] = []
    seen: set[str] = set()
    for index, raw_label in enumerate(materialized[0], start=1):
        label = raw_label.strip()
        column_id = normalize_column_id(label)
        if not column_id:
            raise DelimitedImportError(
                "import.delimited.blank_header",
                parameters={"column": index},
            )
        if column_id in seen:
            raise DelimitedImportError(
                "import.delimited.duplicate_header",
                parameters={"header": label},
            )
        seen.add(column_id)
        columns.append(Column(column_id, label))

    data_rows: list[DataRow] = []
    for source_row, raw_row in enumerate(materialized[1:], start=2):
        if all(not value.strip() for value in raw_row):
            continue
        display_values = {
            column.column_id: raw_row[index]
            for index, column in enumerate(columns)
        }
        normalized_values = {
            column_id: value.strip()
            for column_id, value in display_values.items()
        }
        data_rows.append(
            DataRow(
                row_id=f"row-{source_row}",
                source_row=source_row,
                values=normalized_values,
                display_values=display_values,
            )
        )
    return TabularDataset(tuple(columns), tuple(data_rows), source)


def _decode_candidates(raw: bytes) -> tuple[tuple[str, str], ...]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return (("utf-8-sig", raw.decode("utf-8-sig", errors="strict")),)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return (("utf-16", raw.decode("utf-16", errors="strict")),)
    try:
        return (("utf-8", raw.decode("utf-8", errors="strict")),)
    except UnicodeDecodeError:
        candidates: list[tuple[str, str]] = []
        for encoding in ("cp1251", "gb18030"):
            try:
                candidates.append((encoding, raw.decode(encoding, errors="strict")))
            except UnicodeDecodeError:
                continue
        if not candidates:
            raise DelimitedImportError(
                "import.delimited.decode_failed",
                parameters={"encoding": "UTF-8, Windows-1251, GB18030"},
            )
        return tuple(candidates)


def _read_rows(text: str, delimiter: str) -> tuple[tuple[str, ...], ...]:
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
        raise DelimitedImportError("import.delimited.malformed_csv") from error


def _is_rectangular_multicolumn(text: str, delimiter: str) -> bool:
    try:
        rows = _read_rows(text, delimiter)
    except DelimitedImportError:
        return False
    return bool(rows) and len(rows[0]) > 1 and all(len(row) == len(rows[0]) for row in rows)


def _delimiter_candidates(
    texts: tuple[str, ...],
    *,
    preferred: str,
) -> tuple[str, ...]:
    found = [
        delimiter
        for delimiter in SUPPORTED_DELIMITERS
        if any(_is_rectangular_multicolumn(text, delimiter) for text in texts)
    ]
    if preferred in found:
        found.remove(preferred)
        found.insert(0, preferred)
    return tuple(found)


def _select_delimiter(candidates: tuple[str, ...], suffix: str) -> str | None:
    preferred = "\t" if suffix == ".tsv" else ","
    if preferred in candidates:
        return preferred
    return candidates[0] if len(candidates) == 1 else None


def _select_encoding(
    decoded: tuple[tuple[str, str], ...],
    delimiter: str | None,
) -> str | None:
    if len(decoded) == 1:
        return decoded[0][0]
    if delimiter is None:
        return None
    gb_text = next((text for encoding, text in decoded if encoding == "gb18030"), "")
    if sum("\u3400" <= character <= "\u9fff" for character in gb_text) >= 2:
        return "gb18030"
    cp_text = next((text for encoding, text in decoded if encoding == "cp1251"), "")
    if sum("\u0400" <= character <= "\u04ff" for character in cp_text) >= 3:
        return "cp1251"
    return None


def _text_for_encoding(
    decoded: tuple[tuple[str, str], ...],
    encoding: str | None,
) -> str:
    for candidate, text in decoded:
        if candidate == encoding:
            return text
    raise DelimitedImportError("import.delimited.choice_required")
