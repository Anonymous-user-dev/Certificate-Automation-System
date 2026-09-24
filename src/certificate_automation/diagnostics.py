"""Create local support bundles without copying recipient data by default."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile


class DiagnosticError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    application_version: str = "unknown"
    project_path: Path | None = None
    issue_codes: tuple[str, ...] = ()
    exception_text: str | None = None
    configuration: Mapping[str, object] = field(default_factory=dict)
    manifest: Mapping[str, object] = field(default_factory=dict)
    platform_report: Mapping[str, object] = field(default_factory=dict)
    crash_journal: Mapping[str, object] = field(default_factory=dict)


def _shape(value: object) -> object:
    """Preserve configuration structure, never its free-form leaf values."""
    if isinstance(value, Mapping):
        return {"type": "object", "field_count": len(value),
                "fields": [_shape(item) for item in value.values()]}
    if isinstance(value, (list, tuple)):
        return {"type": "list", "count": len(value)}
    return type(value).__name__


def _trace_shape(text: str | None) -> list[dict[str, object]]:
    if not text:
        return []
    frames = []
    for match in re.finditer(r'File ["\x27].+?["\x27], line (\d+), in ([A-Za-z_][A-Za-z_0-9]*)', text):
        frames.append({"file": "<redacted>", "line": int(match.group(1)), "function": match.group(2)})
    return frames


def _manifest_facts(manifest: Mapping[str, object]) -> dict[str, object]:
    facts: dict[str, object] = {}
    for key in ("schema_version", "revision", "status", "export_status"):
        value = manifest.get(key)
        if isinstance(value, (int, bool)) or value in ("published", "verified", "not_exported"):
            facts[key] = value
    counts = manifest.get("counts")
    if isinstance(counts, Mapping):
        facts["counts"] = {key: value for key, value in counts.items()
                           if isinstance(key, str) and type(value) is int and value >= 0}
    hashes: list[str] = []
    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(key, str) and key.endswith("sha256") and isinstance(item, str) and re.fullmatch(r"[0-9a-fA-F]{64}", item):
                    hashes.append(item.lower())
                elif isinstance(item, (Mapping, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(manifest)
    facts["sha256"] = hashes
    return facts


def _journal_facts(journal: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in journal.items()
        if key in {"schema_version", "state", "last_verified_checkpoint"}
        and (type(value) is int or value is None or isinstance(value, str) and
             value in {"created", "rendering", "verifying", "ready_to_publish", "published"})
    }


def _platform_facts(report: Mapping[str, object]) -> dict[str, object]:
    """Accept known platform facts, never caller-provided arbitrary paths."""
    facts: dict[str, object] = {}
    for key in ("fixed", "cloud", "unc"):
        if type(report.get(key)) is bool:
            facts[key] = report[key]
    allowed = {
        "filesystem": r"(?:NTFS|exFAT|FAT32|ReFS|unknown)",
        "volume_kind": r"(?:fixed|removable|network|unknown)",
        "evidence": r"(?:windows_volume|unsupported_platform|injected)",
        "application_version": r"[0-9][0-9A-Za-z.+-]*|unknown",
        "python_version": r"[0-9][0-9A-Za-z.+-]*|unknown",
        "qt_version": r"[0-9][0-9A-Za-z.+-]*|unknown|unavailable",
        "windows_release": r"[0-9][0-9A-Za-z.+-]*|unsupported",
        "windows_build": r"[0-9][0-9A-Za-z.+-]*|unsupported",
        "word_version": r"[0-9][0-9.]*",
        "converter_version": r"(?:Word|Microsoft Word|LibreOffice) [0-9][0-9.]*",
    }
    for key, pattern in allowed.items():
        value = report.get(key)
        if value is None or isinstance(value, str) and re.fullmatch(pattern, value):
            facts[key] = value
    return facts


class DiagnosticBundleService:
    """Build an allowlisted ZIP in memory and publish it without overwrite."""

    @staticmethod
    def validate_entry_name(name: str) -> None:
        if (
            not isinstance(name, str) or not name or name.startswith("/")
            or "\\" in name or ":" in name or "\0" in name
            or any(part in ("", ".", "..") for part in name.split("/"))
        ):
            raise DiagnosticError("diagnostic.unsafe_name")

    def create(
        self, context: DiagnosticContext, destination: Path,
        *, sensitive_files: tuple[Path, ...] = (),
    ) -> Path:
        destination = Path(destination)
        if destination.exists():
            raise DiagnosticError("diagnostic.destination_exists")
        if destination.parent.is_symlink() or not destination.parent.is_dir():
            raise DiagnosticError("diagnostic.destination_invalid")
        if not isinstance(sensitive_files, tuple):
            raise DiagnosticError("diagnostic.unsafe_attachment")
        normalized: list[Path] = []
        for source in sensitive_files:
            source = Path(source)
            if source.is_symlink() or not source.is_file():
                raise DiagnosticError("diagnostic.unsafe_attachment")
            resolved = source.resolve()
            if resolved in normalized:
                raise DiagnosticError("diagnostic.duplicate_attachment")
            normalized.append(resolved)
        diagnostic = {
            "schema_version": 1,
            "application_version": context.application_version,
            "issue_codes": [code for code in context.issue_codes if re.fullmatch(r"[a-z][a-z0-9_.-]*", code)],
            "trace_frames": _trace_shape(context.exception_text),
            "configuration_shape": _shape(context.configuration),
            "manifest_facts": _manifest_facts(context.manifest),
            "platform": _platform_facts(context.platform_report),
            "crash_journal": _journal_facts(context.crash_journal),
            "sensitive_attachment_count": len(normalized),
        }
        entries: list[tuple[str, bytes]] = [
            ("diagnostic.json", (json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")),
            ("support.log", ("certificate_automation_support_log=1\n"
                             f"issue_count={len(diagnostic['issue_codes'])}\n"
                             f"sensitive_attachment_count={len(normalized)}\n").encode("utf-8")),
        ]
        for index, source in enumerate(normalized, start=1):
            entries.append((f"sensitive/{index:04d}.bin", source.read_bytes()))
        for name, _data in entries:
            self.validate_entry_name(name)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".support-", suffix=".tmp", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
                    for name, data in entries:
                        archive.writestr(name, data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise DiagnosticError("diagnostic.destination_exists") from error
            except OSError as error:
                raise DiagnosticError("diagnostic.write_failed") from error
        finally:
            temporary.unlink(missing_ok=True)
        return destination
