"""Aggregate all issues that must be resolved before generation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType
from typing import Mapping
import unicodedata

from certificate_automation.dataset import TabularDataset
from certificate_automation.domain import Issue, Severity
from certificate_automation.filenames import RESERVED_NAMES, safe_stem
from certificate_automation.history import DuplicatePolicy, HistoryIndex, HistoryStatus, normalize_identity
from certificate_automation.mapping import (
    ColumnValue,
    FormattedDateValue,
    JoinValue,
    MappingEvaluationError,
    MappingPlan,
    MappingSelection,
    evaluate_plan,
)
from certificate_automation.output_options import OutputOptions
from certificate_automation.template import TemplateInspection
from certificate_automation.workbook import WorkbookData, normalize_field_name


MAX_VALUE_LENGTH = 500
MINIMUM_WORKING_SPACE = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Complete preflight result, including the deterministic filename plan."""

    issues: tuple[Issue, ...]
    filename_stems: Mapping[int | str, str]
    estimated_bytes: int
    dataset_revision: int = -1
    template_sha256: str = ""
    warning_digest: str = ""

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
    workbook: WorkbookData | TabularDataset,
    template: TemplateInspection,
    mappings: MappingSelection | MappingPlan,
    destination: Path | OutputOptions,
    *,
    duplicate_policy: DuplicatePolicy | None = None,
    history_index: HistoryIndex | None = None,
) -> ValidationReport:
    """Return every actionable issue without creating certificate outputs."""

    if isinstance(workbook, TabularDataset):
        if not isinstance(mappings, MappingPlan) or not isinstance(destination, OutputOptions):
            raise TypeError("TabularDataset validation requires MappingPlan and OutputOptions")
        return _validate_dataset(
            workbook, template, mappings, destination,
            duplicate_policy or DuplicatePolicy(), history_index,
        )
    if not isinstance(mappings, MappingSelection) or isinstance(destination, OutputOptions):
        raise TypeError("WorkbookData validation requires MappingSelection and destination")
    return _validate_legacy(workbook, template, mappings, Path(destination))


def _validate_legacy(
    workbook: WorkbookData,
    template: TemplateInspection,
    mappings: MappingSelection,
    destination: Path,
) -> ValidationReport:
    """Compatibility preflight for the original workbook-only workflow."""

    issues: list[Issue] = []
    destination = Path(destination)

    if not workbook.recipients:
        issues.append(_error("validation.no_recipients", "workbook"))
    if not template.placeholders:
        issues.append(
            _error(
                "validation.no_placeholders",
                "template",
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
                    "validation.unresolved_placeholder",
                    "mapping",
                    {"placeholder": placeholder},
                )
            )
            continue
        if column is not None and column not in header_names:
            issues.append(
                _error(
                    "validation.unknown_workbook_column",
                    "mapping",
                    {"column": column},
                )
            )
            continue
        resolved_placeholders.add(placeholder)

    for placeholder in set(mappings.columns) | set(mappings.fixed_values):
        if placeholder not in placeholder_names:
            issues.append(
                _error(
                    "validation.mapping_not_in_template",
                    "mapping",
                    {"placeholder": placeholder},
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
                        "validation.blank_mapped_value",
                        "workbook",
                        {"row": recipient.source_row, "placeholder": placeholder},
                        row_id=f"source-row-{recipient.source_row}",
                    )
                )
            elif len(value) > MAX_VALUE_LENGTH:
                issues.append(
                    _error(
                        "validation.value_too_long",
                        "workbook",
                        {
                            "row": recipient.source_row,
                            "maximum": MAX_VALUE_LENGTH,
                            "placeholder": placeholder,
                        },
                        row_id=f"source-row-{recipient.source_row}",
                    )
                )
            normalized_record.append(value.casefold())

        record_key = tuple(normalized_record)
        if record_is_complete and record_key in seen_records:
            first_row = seen_records[record_key]
            issues.append(
                _error(
                    "validation.duplicate_recipient",
                    "workbook",
                    {"row": recipient.source_row, "first_row": first_row},
                    row_id=f"source-row-{recipient.source_row}",
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
                    "validation.duplicate_output_filename",
                    "workbook",
                    {
                        "first_row": first_row,
                        "row": recipient.source_row,
                        "filename": stem,
                    },
                    row_id=f"source-row-{recipient.source_row}",
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


def _validate_dataset(
    dataset: TabularDataset,
    template: TemplateInspection,
    plan: MappingPlan,
    options: OutputOptions,
    duplicate_policy: DuplicatePolicy,
    history_index: HistoryIndex | None,
) -> ValidationReport:
    """Validate the complete immutable dataset before any official output exists."""

    issues: list[Issue] = []
    template_hash = _file_sha256(template.path)
    if not dataset.rows:
        issues.append(_error("validation.no_recipients", "dataset"))
    if not template.placeholders:
        issues.append(_error("validation.no_placeholders", "template"))

    template_names = set(template.names)
    for placeholder in plan.unresolved(template.names):
        issues.append(
            _error(
                "validation.unresolved_placeholder",
                "mapping",
                {"placeholder": placeholder},
            )
        )
    for placeholder in plan.sources:
        if placeholder not in template_names:
            issues.append(
                _error(
                    "validation.mapping_not_in_template",
                    "mapping",
                    {"placeholder": placeholder},
                )
            )

    dataset_ids = {row.row_id for row in dataset.rows}
    option_ids = set(options.row_ids)
    for row_id in options.row_ids:
        if row_id not in dataset_ids:
            issues.append(
                _error("output.unknown_row", "output", {"row_id": row_id}, row_id=row_id)
            )
    for row_id in dataset.order:
        if row_id not in option_ids:
            issues.append(
                _error("output.row_omitted", "output", {"row_id": row_id}, row_id=row_id)
            )

    filename_stems: dict[str, str] = {}
    resolved_records: dict[tuple[str, ...], str] = {}
    collision_groups: dict[str, list[str]] = {}
    full_name_placeholder = next(
        (name for name in template.names if normalize_field_name(name) == "full_name"),
        None,
    )
    column_ids = {column.column_id for column in dataset.columns}
    identity_columns = duplicate_policy.identity_columns
    missing_identity = tuple(column for column in identity_columns if column not in column_ids)
    for column in missing_identity:
        issues.append(_error("validation.unknown_identity_column", "dataset", {"column": column}, column_id=column))
    certificate_column = duplicate_policy.certificate_id_column
    if certificate_column is not None and certificate_column not in column_ids:
        issues.append(_error("validation.unknown_certificate_id_column", "dataset", {"column": certificate_column}, column_id=certificate_column))
    if duplicate_policy.check_history and not identity_columns and certificate_column is None:
        issues.append(_error("validation.history_identity_required", "dataset"))
    seen_identities: dict[tuple[str, ...], str] = {}
    certificate_groups: dict[str, list[str]] = {}
    history_unavailable_reported = False
    history_facts: list[object] = []

    for placeholder, source in plan.sources.items():
        referenced = _referenced_columns(source)
        for column_id in referenced:
            if column_id not in column_ids:
                issues.append(
                    _error(
                        "validation.unknown_workbook_column",
                        "mapping",
                        {"column": column_id},
                        column_id=column_id,
                    )
                )

    for row_id in options.row_ids:
        if row_id not in dataset_ids:
            continue
        row = dataset.row(row_id)
        display_row = row.source_row if row.source_row is not None else dataset.order.index(row_id) + 1
        selected_identity: tuple[str, ...] = ()
        if identity_columns and not missing_identity:
            selected_identity = tuple(normalize_identity(row.value(column)) for column in identity_columns)
            if all(selected_identity):
                first_id = seen_identities.get(selected_identity)
                if first_id is not None:
                    issues.append(_warning(
                        "validation.identity_duplicate", "dataset",
                        {"row": display_row, "first_row": _display_row(dataset, first_id)},
                        row_id=row_id,
                    ))
                else:
                    seen_identities[selected_identity] = row_id
            else:
                for column, value in zip(identity_columns, selected_identity):
                    if not value:
                        issues.append(_error(
                            "validation.blank_identity", "dataset",
                            {"row": display_row, "column": column},
                            row_id=row_id, column_id=column,
                        ))
        certificate_id: str | None = None
        if certificate_column is not None and certificate_column in column_ids:
            certificate_id = normalize_identity(row.value(certificate_column))
            if certificate_id:
                certificate_groups.setdefault(certificate_id, []).append(row_id)
            else:
                issues.append(_error(
                    "validation.blank_certificate_id", "dataset", {"row": display_row},
                    row_id=row_id, column_id=certificate_column,
                ))
        if duplicate_policy.check_history:
            if history_index is None:
                history_facts.append((row_id, "unavailable"))
                if not history_unavailable_reported:
                    issues.append(_warning("history.unavailable", "history"))
                    history_unavailable_reported = True
            elif (selected_identity and all(selected_identity)) or certificate_id:
                check = history_index.check(selected_identity, certificate_id=certificate_id)
                history_facts.append((
                    row_id, check.status.value,
                    tuple((match.kind, match.batch_id, match.revision,
                           match.completed_at.isoformat(), str(match.folder))
                          for match in check.matches),
                ))
                if check.status is HistoryStatus.UNAVAILABLE:
                    if not history_unavailable_reported:
                        issues.append(_warning("history.unavailable", "history"))
                        history_unavailable_reported = True
                else:
                    for match in check.matches:
                        issues.append(_warning(
                            "validation.history_duplicate", "history",
                            {"row": display_row, "batch": match.batch_id},
                            row_id=row_id,
                        ))
        replacements: dict[str, str] = {}
        for placeholder, source in plan.sources.items():
            try:
                replacements.update(
                    evaluate_plan(MappingPlan({placeholder: source}), dataset, row_id)
                )
            except MappingEvaluationError as error:
                issues.append(
                    _error(
                        error.code,
                        "mapping",
                        {"row": display_row},
                        row_id=error.row_id or row_id,
                        column_id=error.column_id,
                    )
                )

        normalized_record: list[str] = []
        complete = True
        for placeholder in template.names:
            if placeholder not in plan.sources:
                complete = False
                continue
            value = replacements.get(placeholder, "").strip()
            if not value:
                complete = False
                issues.append(
                    _error(
                        "validation.blank_mapped_value",
                        "dataset",
                        {"row": display_row, "placeholder": placeholder},
                        row_id=row_id,
                        column_id=_primary_column(plan.sources[placeholder]),
                    )
                )
            elif len(value) > MAX_VALUE_LENGTH:
                issues.append(
                    _error(
                        "validation.value_too_long",
                        "dataset",
                        {
                            "row": display_row,
                            "maximum": MAX_VALUE_LENGTH,
                            "placeholder": placeholder,
                        },
                        row_id=row_id,
                        column_id=_primary_column(plan.sources[placeholder]),
                    )
                )
            normalized_record.append(unicodedata.normalize("NFC", value).casefold())

        record_key = tuple(normalized_record)
        if complete and record_key in resolved_records:
            first_id = resolved_records[record_key]
            issues.append(
                _error(
                    "validation.duplicate_recipient",
                    "dataset",
                    {"row": display_row, "first_row": _display_row(dataset, first_id)},
                    row_id=row_id,
                )
            )
        elif complete:
            resolved_records[record_key] = row_id

        filename_value = (
            replacements.get(full_name_placeholder, "")
            if full_name_placeholder is not None
            else f"certificate-row-{display_row}"
        )
        stem = safe_stem(filename_value)
        filename_stems[row_id] = stem
        collision_key = unicodedata.normalize("NFC", stem).casefold()
        collision_groups.setdefault(collision_key, []).append(row_id)

        raw_base = str(filename_value).strip().split(".", maxsplit=1)[0].casefold()
        if raw_base in RESERVED_NAMES:
            issues.append(
                _error(
                    "output.reserved_filename",
                    "output",
                    {"filename": filename_value},
                    row_id=row_id,
                    column_id=_primary_column(plan.sources.get(full_name_placeholder)),
                )
            )
        extensions = ([".docx"] if options.docx else []) + (
            [".pdf"] if options.individual_pdf else []
        )
        if any(len(str(options.destination / f"{stem}{extension}")) > 240 for extension in extensions):
            issues.append(
                _error(
                    "output.path_too_long",
                    "output",
                    {"filename": stem},
                    row_id=row_id,
                )
            )

    for row_ids in collision_groups.values():
        if len(row_ids) < 2:
            continue
        filename = filename_stems[row_ids[0]]
        for row_id in row_ids:
            issues.append(
                _error(
                    "output.filename_collision",
                    "output",
                    {"filename": filename},
                    row_id=row_id,
                    column_id=_primary_column(plan.sources.get(full_name_placeholder)),
                )
            )

    for row_ids in certificate_groups.values():
        if len(row_ids) < 2:
            continue
        for row_id in row_ids:
            issues.append(_error(
                "validation.certificate_id_collision", "dataset",
                {"row": _display_row(dataset, row_id)},
                row_id=row_id, column_id=certificate_column,
            ))

    estimated_bytes = _estimate_dataset_working_space(dataset, template, options)
    source_paths = tuple(
        path
        for path in (dataset.source.path, template.path)
        if path is not None
    )
    issues.extend(_validate_destination(options.destination, source_paths, estimated_bytes))
    warnings = tuple(issue for issue in issues if issue.severity is Severity.WARNING)
    warning_digest = ""
    if warnings:
        context = {
            "dataset": dataset.canonical_sha256(),
            "template": template_hash,
            "mapping": plan.to_json(),
            "policy": duplicate_policy.to_json(),
            "history": history_facts,
            "warnings": [
                (issue.code, issue.row_id, issue.column_id, dict(issue.parameters))
                for issue in warnings
            ],
        }
        warning_digest = sha256(json.dumps(
            context, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
    return ValidationReport(
        tuple(issues),
        filename_stems,
        estimated_bytes,
        dataset.revision,
        template_hash,
        warning_digest,
    )


def _referenced_columns(source: object) -> tuple[str, ...]:
    if isinstance(source, ColumnValue):
        return (source.column_id,)
    if isinstance(source, FormattedDateValue):
        return (source.source.column_id,)
    if isinstance(source, JoinValue):
        return source.column_ids
    return ()


def _primary_column(source: object) -> str | None:
    columns = _referenced_columns(source)
    return columns[0] if columns else None


def _display_row(dataset: TabularDataset, row_id: str) -> int:
    row = dataset.row(row_id)
    return row.source_row if row.source_row is not None else dataset.order.index(row_id) + 1


def _file_sha256(path: Path) -> str:
    digest = sha256()
    try:
        with Path(path).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def _estimate_dataset_working_space(
    dataset: TabularDataset,
    template: TemplateInspection,
    options: OutputOptions,
) -> int:
    template_size = template.path.stat().st_size if template.path.exists() else 0
    copies = int(options.docx) + int(options.individual_pdf or options.combined_pdf) * 2
    return max(MINIMUM_WORKING_SPACE, template_size * max(len(dataset.rows), 1) * max(copies, 1))


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
                "validation.destination_is_source",
                "destination",
            )
        ]
    if destination.exists() and not destination.is_dir():
        return [
            _error(
                "validation.destination_not_directory",
                "destination",
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
                "validation.destination_not_writable",
                "destination",
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
                "validation.disk_space_unknown",
            )
        )
    else:
        if free_bytes < estimated_bytes:
            issues.append(
                _error(
                    "validation.insufficient_disk_space",
                    "destination",
                )
            )
    return issues


def _error(
    code: str,
    source: str,
    parameters: Mapping[str, str | int] | None = None,
    *,
    row_id: str | None = None,
    column_id: str | None = None,
) -> Issue:
    return Issue(
        Severity.ERROR,
        source,
        code,
        parameters or {},
        row_id=row_id,
        column_id=column_id,
    )


def _warning(
    code: str,
    source: str,
    parameters: Mapping[str, str | int] | None = None,
    *,
    row_id: str | None = None,
) -> Issue:
    return Issue(Severity.WARNING, source, code, parameters or {}, row_id=row_id)
