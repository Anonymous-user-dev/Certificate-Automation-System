"""Immutable, validated output choices for one certificate batch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from certificate_automation.filenames import is_safe_windows_stem


class OutputOptionsError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OutputOptions:
    docx: bool
    individual_pdf: bool
    combined_pdf: bool
    destination: Path
    batch_name: str
    row_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (self.docx or self.individual_pdf or self.combined_pdf):
            raise OutputOptionsError("output.none_selected")
        if self.destination is None or not str(self.destination).strip():
            raise OutputOptionsError("output.destination_missing")
        destination = Path(self.destination)
        row_ids = tuple(str(row_id) for row_id in self.row_ids)
        if not row_ids or any(not row_id for row_id in row_ids):
            raise OutputOptionsError("output.row_missing")
        if len(row_ids) != len(set(row_ids)):
            raise OutputOptionsError("output.duplicate_row")
        batch_name = str(self.batch_name).strip()
        if self.combined_pdf and not is_safe_windows_stem(batch_name):
            raise OutputOptionsError("output.invalid_batch_name")
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "batch_name", batch_name)
        object.__setattr__(self, "row_ids", row_ids)

    def to_json(self) -> dict[str, object]:
        return {
            "docx": self.docx,
            "individual_pdf": self.individual_pdf,
            "combined_pdf": self.combined_pdf,
            "destination": str(self.destination),
            "batch_name": self.batch_name,
            "row_ids": list(self.row_ids),
        }

    @property
    def order(self) -> tuple[str, ...]:
        """Public generation-order alias used by the operator workflow."""

        return self.row_ids

    @classmethod
    def from_json(cls, value: dict[str, object]) -> "OutputOptions":
        return cls(
            docx=bool(value.get("docx")),
            individual_pdf=bool(value.get("individual_pdf")),
            combined_pdf=bool(value.get("combined_pdf")),
            destination=Path(str(value.get("destination", ""))),
            batch_name=str(value.get("batch_name", "")),
            row_ids=tuple(str(item) for item in value.get("row_ids", ())),
        )
