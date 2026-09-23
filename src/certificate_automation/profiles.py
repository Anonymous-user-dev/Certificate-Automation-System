"""Versioned local mapping profiles; no recipient data or executable formats."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Mapping

from certificate_automation import __version__
from certificate_automation.dataset import Column, normalize_column_id
from certificate_automation.mapping import (
    ColumnValue, FixedValue, FormattedDateValue, JoinValue, MappingPlan,
    MappingPlanError, MappingSource, mapping_source_from_json,
)


PROFILE_SCHEMA = 1
_PAYLOAD_FIELDS = frozenset({"schema_version", "application_version", "name", "description", "expected_placeholders", "mappings", "column_labels", "template_sha256", "defaults"})
_SOURCE_FIELDS = {
    "column": frozenset({"type", "column_id"}),
    "fixed": frozenset({"type", "value"}),
    "sequence": frozenset({"type", "start", "step", "width", "prefix", "suffix"}),
    "source_row": frozenset({"type"}),
    "formatted_date": frozenset({"type", "source", "input_format", "output_format"}),
    "join": frozenset({"type", "column_ids", "separator"}),
}
_DEFAULT_FIELDS = frozenset({"docx", "individual_pdf", "combined_pdf", "batch_name", "filename_pattern"})


class ProfileError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProfileMatchStatus(str, Enum):
    EXACT = "exact"
    REVIEW_REQUIRED = "review_required"
    MISSING = "missing"
    UNUSED = "unused"


@dataclass(frozen=True, slots=True)
class ProfileMatch:
    status: ProfileMatchStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProfileComparison:
    matches: Mapping[str, ProfileMatch]
    applied_plan: MappingPlan


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    name: str
    path: Path
    description: str


@dataclass(frozen=True, slots=True)
class MappingProfile:
    schema_version: int
    name: str
    description: str
    expected_placeholders: tuple[str, ...]
    mappings: Mapping[str, object]
    column_labels: Mapping[str, str]
    template_sha256: str | None = None
    defaults: Mapping[str, object] = field(default_factory=dict)
    application_version: str = __version__

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != PROFILE_SCHEMA:
            raise ProfileError("profile.invalid_schema")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ProfileError("profile.invalid_name")
        if not isinstance(self.description, str) or len(self.description) > 1000:
            raise ProfileError("profile.invalid_schema")
        if not isinstance(self.application_version, str) or not self.application_version:
            raise ProfileError("profile.invalid_schema")
        placeholders = self.expected_placeholders
        if not isinstance(placeholders, (tuple, list)) or not all(isinstance(p, str) and p.strip() for p in placeholders) or len(set(placeholders)) != len(placeholders):
            raise ProfileError("profile.invalid_schema")
        if not isinstance(self.mappings, Mapping) or not isinstance(self.column_labels, Mapping) or not isinstance(self.defaults, Mapping):
            raise ProfileError("profile.invalid_schema")
        if not set(self.mappings) <= set(placeholders) or not all(isinstance(k, str) for k in self.mappings):
            raise ProfileError("profile.invalid_schema")
        if not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in self.column_labels.items()):
            raise ProfileError("profile.invalid_schema")
        if not set(self.defaults) <= _DEFAULT_FIELDS or any(not isinstance(k, str) for k in self.defaults):
            raise ProfileError("profile.invalid_schema")
        for key, value in self.defaults.items():
            if key in {"docx", "individual_pdf", "combined_pdf"} and type(value) is not bool:
                raise ProfileError("profile.invalid_schema")
            if key in {"batch_name", "filename_pattern"} and (not isinstance(value, str) or len(value) > 200):
                raise ProfileError("profile.invalid_schema")
        if self.template_sha256 is not None and (not isinstance(self.template_sha256, str) or len(self.template_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.template_sha256)):
            raise ProfileError("profile.invalid_schema")
        validated = {}
        for key, record in self.mappings.items():
            if not isinstance(record, Mapping) or not isinstance(record.get("type"), str) or set(record) != _SOURCE_FIELDS.get(record["type"]):
                raise ProfileError("profile.invalid_schema")
            kind = record["type"]
            if kind == "column" and not isinstance(record["column_id"], str):
                raise ProfileError("profile.invalid_schema")
            if kind == "sequence" and (
                any(type(record[name]) is not int for name in ("start", "step", "width"))
                or any(not isinstance(record[name], str) for name in ("prefix", "suffix"))
                or not (-1_000_000_000 <= record["start"] <= 1_000_000_000)
                or not (-1_000_000_000 <= record["step"] <= 1_000_000_000)
                or not (1 <= record["width"] <= 100)
            ):
                raise ProfileError("profile.invalid_schema")
            if kind == "join" and (
                not isinstance(record["column_ids"], list)
                or not all(isinstance(item, str) for item in record["column_ids"])
                or not isinstance(record["separator"], str)
            ):
                raise ProfileError("profile.invalid_schema")
            if record["type"] == "formatted_date" and (not isinstance(record["source"], Mapping) or set(record["source"]) != _SOURCE_FIELDS["column"] or record["source"].get("type") != "column"):
                raise ProfileError("profile.invalid_schema")
            if kind == "formatted_date" and (
                not isinstance(record["source"]["column_id"], str)
                or not isinstance(record["input_format"], str)
                or not isinstance(record["output_format"], str)
            ):
                raise ProfileError("profile.invalid_schema")
            try:
                source = mapping_source_from_json(record)
            except (MappingPlanError, TypeError, ValueError) as error:
                raise ProfileError("profile.invalid_schema") from error
            if isinstance(source, FixedValue) and not isinstance(record["value"], str):
                raise ProfileError("profile.invalid_schema")
            validated[key] = {"type": source.kind, **source.parameters()}
        referenced = set()
        for record in validated.values():
            source = mapping_source_from_json(record)
            referenced.update(_source_column_ids(source))
        if not set(self.column_labels) <= referenced:
            raise ProfileError("profile.invalid_schema")
        object.__setattr__(self, "expected_placeholders", tuple(placeholders))
        object.__setattr__(self, "mappings", MappingProxyType({key: _freeze(value) for key, value in validated.items()}))
        object.__setattr__(self, "column_labels", MappingProxyType(dict(self.column_labels)))
        object.__setattr__(self, "defaults", MappingProxyType(dict(self.defaults)))

    @classmethod
    def from_plan(cls, name: str, plan: MappingPlan, placeholders: tuple[str, ...], columns: tuple[Column, ...], *, description: str = "", template_sha256: str | None = None, defaults: Mapping[str, object] | None = None) -> "MappingProfile":
        references = {id for source in plan.sources.values() for id in _source_column_ids(source)}
        labels = {column.column_id: column.label for column in columns if column.column_id in references}
        return cls(PROFILE_SCHEMA, name, description, tuple(placeholders), plan.to_json(), labels, template_sha256, defaults or {})

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "application_version": self.application_version,
            "name": self.name, "description": self.description,
            "expected_placeholders": list(self.expected_placeholders),
            "mappings": {k: _plain(v) for k, v in self.mappings.items()},
            "column_labels": dict(self.column_labels), "template_sha256": self.template_sha256,
            "defaults": dict(self.defaults),
        }


def _source_column_ids(source: MappingSource) -> tuple[str, ...]:
    if isinstance(source, ColumnValue):
        return (source.column_id,)
    if isinstance(source, FormattedDateValue):
        return (source.source.column_id,)
    if isinstance(source, JoinValue):
        return source.column_ids
    return ()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("profile.invalid_schema")
        result[key] = value
    return result


def _reject_nonstandard_json() -> object:
    raise ProfileError("profile.invalid_schema")


class ProfileStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def save(self, profile: MappingProfile, *, allow_fixed_values: bool = False) -> Path:
        if not allow_fixed_values and any(record["type"] == "fixed" for record in profile.mappings.values()):
            raise ProfileError("profile.sensitive_fixed_value")
        stem = normalize_column_id(profile.name)
        if not stem or stem in {"con", "prn", "aux", "nul"} or stem.startswith(("com", "lpt")) and stem[3:].isdigit():
            raise ProfileError("profile.invalid_name")
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{stem}.certprofile"
        payload = profile.payload()
        record = {"payload": payload, "payload_sha256": sha256(_canonical(payload)).hexdigest()}
        serialized = _canonical(record) + b"\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".certprofile-", suffix=".tmp", dir=self.directory, delete=False) as file:
                temporary = Path(file.name)
                file.write(serialized)
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary, destination)
        except FileExistsError as error:
            raise ProfileError("profile.already_exists") from error
        except OSError as error:
            raise ProfileError("profile.save_failed") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination

    def load(self, path: Path) -> MappingProfile:
        path = Path(path)
        if (
            path.absolute().parent != self.directory.absolute()
            or path.resolve().parent != self.directory.resolve()
            or path.is_symlink()
            or path.suffix.lower() != ".certprofile"
        ):
            raise ProfileError("profile.path_outside_store")
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ProfileError("profile.invalid_schema")
            record = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys,
                parse_constant=lambda _value: _reject_nonstandard_json(),
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProfileError("profile.unreadable") from error
        if not isinstance(record, dict) or set(record) != {"payload", "payload_sha256"} or not isinstance(record["payload"], dict) or set(record["payload"]) != _PAYLOAD_FIELDS:
            raise ProfileError("profile.invalid_schema")
        if not isinstance(record["payload_sha256"], str) or sha256(_canonical(record["payload"])).hexdigest() != record["payload_sha256"]:
            raise ProfileError("profile.hash_mismatch")
        payload = record["payload"]
        return MappingProfile(**payload)

    def list(self) -> tuple[ProfileSummary, ...]:
        if not self.directory.is_dir():
            return ()
        found = []
        for path in sorted(self.directory.glob("*.certprofile")):
            try:
                profile = self.load(path)
            except ProfileError:
                continue
            found.append(ProfileSummary(profile.name, path, profile.description))
        return tuple(found)


def compare_profile(profile: MappingProfile, columns: tuple[Column, ...], placeholders: tuple[str, ...]) -> ProfileComparison:
    ids: dict[str, list[str]] = {}
    for column in columns:
        ids.setdefault(normalize_column_id(column.column_id), []).append(column.column_id)
    labels: dict[str, list[str]] = {}
    for column in columns:
        labels.setdefault(column.label.casefold().strip(), []).append(column.column_id)
    matches: dict[str, ProfileMatch] = {}
    applied: dict[str, MappingSource] = {}
    for placeholder in placeholders:
        record = profile.mappings.get(placeholder)
        if record is None:
            matches[placeholder] = ProfileMatch(ProfileMatchStatus.MISSING)
            continue
        source = mapping_source_from_json(record)
        replacements: dict[str, str] = {}
        suggestion = ""
        for old_id in _source_column_ids(source):
            normalized = normalize_column_id(old_id)
            if len(ids.get(normalized, ())) == 1:
                replacements[old_id] = ids[normalized][0]
                continue
            if len(ids.get(normalized, ())) > 1:
                break
            same_label = labels.get(profile.column_labels.get(old_id, "").casefold().strip(), ())
            if len(same_label) == 1:
                replacements[old_id] = same_label[0]
                continue
            candidates = get_close_matches(profile.column_labels.get(old_id, old_id).casefold(), labels, n=1, cutoff=0.5)
            suggestion = labels[candidates[0]][0] if candidates and len(labels[candidates[0]]) == 1 else ""
            break
        if len(replacements) != len(_source_column_ids(source)):
            matches[placeholder] = ProfileMatch(ProfileMatchStatus.REVIEW_REQUIRED, suggestion)
            continue
        if isinstance(source, ColumnValue):
            source = ColumnValue(replacements[source.column_id])
        elif isinstance(source, FormattedDateValue):
            source = FormattedDateValue(ColumnValue(replacements[source.source.column_id]), source.input_format, source.output_format)
        elif isinstance(source, JoinValue):
            source = JoinValue(tuple(replacements[id] for id in source.column_ids), source.separator)
        applied[placeholder] = source
        matches[placeholder] = ProfileMatch(ProfileMatchStatus.EXACT)
    for placeholder in profile.expected_placeholders:
        if placeholder not in placeholders:
            matches[placeholder] = ProfileMatch(ProfileMatchStatus.UNUSED)
    return ProfileComparison(MappingProxyType(matches), MappingPlan(applied))
