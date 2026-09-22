"""Shared immutable records used across the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


class Severity(str, Enum):
    """How an issue affects the user's ability to generate a batch."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Issue:
    """A language-neutral validation or processing issue."""

    severity: Severity
    source: str
    code: str
    parameters: Mapping[str, str | int] = field(default_factory=dict)
    row_id: str | None = None
    column_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.ERROR


@dataclass(frozen=True, slots=True)
class Recipient:
    """Normalized values from one source workbook row."""

    source_row: int
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


class BatchState(str, Enum):
    """Externally observable lifecycle state of a certificate batch."""

    PENDING = "pending"
    VALIDATED = "validated"
    GENERATING = "generating"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Final outcome returned by batch generation."""

    state: BatchState
    output_dir: Path | None = None
    generated_count: int = 0
    issues: tuple[Issue, ...] = field(default_factory=tuple)
    combined_pdf_path: Path | None = None
