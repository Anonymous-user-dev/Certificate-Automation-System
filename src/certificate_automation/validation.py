"""Aggregate all issues that must be resolved before generation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType
from typing import Mapping

from certificate_automation.domain import Issue, Severity
from certificate_automation.filenames import safe_stem
from certificate_automation.mapping import MappingSelection
from certificate_automation.template import TemplateInspection
from certificate_automation.workbook import WorkbookData, normalize_field_name


MAX_VALUE_LENGTH = 500
MINIMUM_WORKING_SPACE = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Complete preflight result, including the deterministic filename plan."""

    issues: tuple[Issue, ...]
    filename_stems: Mapping[int, str]
    estimated_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "filename_stems",
            MappingProxyType(dict(self.filename_stems)),
        )

    @property
    def ready(self) -> bool:
        return not any(issue.blocking for issue in self.issues)


def validate_preflight(
    workbook: WorkbookData,
    template: TemplateInspection,
    mappings: MappingSelection,
    destination: Path,
) -> ValidationReport:
    """Return every actionable issue without creating certificate outputs."""

    issues: list[Issue] = []
    destination = Path(destination)

    if not workbook.recipients:
        issues.append(
            _error("no_recipients", "workbook", "The worksheet has no recipient rows.")
        )
    if not template.placeholders:
        issues.append(
            _error(
                "no_placeholders",
                "template",
                "The Word template does not contain any {{PLACEHOLDER}} fields.",
            )
        )

    placeholder_names = set(template.names)
    header_names = set(workbook.headers)
    resolved_placeholders: set[str] = set()
    for placeholder in template.names:
        column = mappings.columns.get(placeholder)
        fixed_value = mappings.fixed_values.get(placeholder)
        if column is None and (fixed_value is None or not fixed_value.strip()):
            issues.append(
                _error(
                    "unresolved_placeholder",
                    "mapping",
                    f"Choose an Excel column or fixed value for {{{{{placeholder}}}}}.",
                )
            )
            continue
        if column is not None and column not in header_names:
            issues.append(
                _error(
                    "unknown_workbook_column",
                    "mapping",
                    f"The mapped Excel column '{column}' does not exist.",
                )
            )
            continue
        resolved_placeholders.add(placeholder)

    for placeholder in set(mappings.columns) | set(mappings.fixed_values):
        if placeholder not in placeholder_names:
            issues.append(
                _error(
                    "mapping_not_in_template",
                    "mapping",
                    f"The mapping for {{{{{placeholder}}}}} is not used by the template.",
                )
            )

    filename_stems: dict[int, str] = {}
    seen_records: dict[tuple[str, ...], int] = {}
    seen_filenames: dict[str, int] = {}
    full_name_placeholder = next(
        (
            name
            for name in template.names
            if normalize_field_name(name) == "full_name"
        ),
        None,
    )

    for recipient in workbook.recipients:
        replacements = mappings.replacements_for(recipient)
        normalized_record: list[str] = []
        record_is_complete = True
        for placeholder in template.names:
            if placeholder not in resolved_placeholders:
                record_is_complete = False
                continue
            value = replacements.get(placeholder, "").strip()
            if not value:
                record_is_complete = False
                issues.append(
                    _error(
                        "blank_mapped_value",
                        "workbook",
                        f"Row {recipient.source_row} has no value for "
                        f"{{{{{placeholder}}}}}.",
                        row_number=recipient.source_row,
                    )
                )
            elif len(value) > MAX_VALUE_LENGTH:
                issues.append(
                    _error(
                        "value_too_long",
                        "workbook",
                        f"Row {recipient.source_row} has a value longer than "
                        f"{MAX_VALUE_LENGTH} characters for {{{{{placeholder}}}}}.",
                        row_number=recipient.source_row,
                    )
                )
            normalized_record.append(value.casefold())

        record_key = tuple(normalized_record)
        if record_is_complete and record_key in seen_records:
            first_row = seen_records[record_key]
            issues.append(
                _error(
                    "duplicate_recipient",
                    "workbook",
                    f"Row {recipient.source_row} duplicates the mapped values from "
                    f"row {first_row}.",
                    row_number=recipient.source_row,
                )
            )
        elif record_is_complete:
            seen_records[record_key] = recipient.source_row

        filename_value = (
            replacements.get(full_name_placeholder, "")
            if full_name_placeholder is not None
            else f"certificate-row-{recipient.source_row}"
        )
        stem = safe_stem(filename_value)
        filename_stems[recipient.source_row] = stem
        collision_key = stem.casefold()
        if collision_key in seen_filenames:
            first_row = seen_filenames[collision_key]
            issues.append(
                _error(
                    "duplicate_output_filename",
                    "workbook",
                    f"Rows {first_row} and {recipient.source_row} would create the "
                    f"same output filename '{stem}'.",
                    row_number=recipient.source_row,
                )
            )
        else:
            seen_filenames[collision_key] = recipient.source_row

    estimated_bytes = _estimate_working_space(workbook, template)
    issues.extend(
        _validate_destination(
            destination,
            (workbook.path, template.path),
            estimated_bytes,
        )
    )
    return ValidationReport(tuple(issues), filename_stems, estimated_bytes)


def _estimate_working_space(
    workbook: WorkbookData,
    template: TemplateInspection,
) -> int:
    source_size = sum(
        path.stat().st_size for path in (workbook.path, template.path) if path.exists()
    )
    return max(
        MINIMUM_WORKING_SPACE,
        source_size * max(len(workbook.recipients), 1) * 3,
    )


def _validate_destination(
    destination: Path,
    source_paths: tuple[Path, ...],
    estimated_bytes: int,
) -> list[Issue]:
    issues: list[Issue] = []
    resolved_destination = destination.resolve()
    if any(resolved_destination == path.resolve() for path in source_paths):
        return [
            _error(
                "destination_is_source",
                "destination",
                "The output destination cannot be the Excel file or Word template.",
            )
        ]
    if destination.exists() and not destination.is_dir():
        return [
            _error(
                "destination_not_directory",
                "destination",
                "Choose a folder for generated certificate batches.",
            )
        ]

    probe_directory = destination if destination.exists() else destination.parent
    while not probe_directory.exists() and probe_directory != probe_directory.parent:
        probe_directory = probe_directory.parent
    try:
        with tempfile.NamedTemporaryFile(
            dir=probe_directory,
            prefix=".certificate-write-check-",
            delete=True,
        ):
            pass
    except OSError:
        issues.append(
            _error(
                "destination_not_writable",
                "destination",
                "The selected output folder is not writable.",
            )
        )
        return issues

    try:
        free_bytes = shutil.disk_usage(probe_directory).free
    except OSError:
        issues.append(
            Issue(
                Severity.WARNING,
                "destination",
                "Available disk space could not be checked.",
                code="disk_space_unknown",
            )
        )
    else:
        if free_bytes < estimated_bytes:
            issues.append(
                _error(
                    "insufficient_disk_space",
                    "destination",
                    "The selected drive does not have enough free space for this batch.",
                )
            )
    return issues


def _error(
    code: str,
    source: str,
    message: str,
    *,
    row_number: int | None = None,
) -> Issue:
    return Issue(
        Severity.ERROR,
        source,
        message,
        code=code,
        row_number=row_number,
    )
