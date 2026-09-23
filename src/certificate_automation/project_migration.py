"""Validated, backup-first migration of local project databases."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from certificate_automation.project import ProjectError, ProjectState, ProjectStore


class ProjectMigrationError(ProjectError):
    """Migration stopped before replacing the original project."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    path: Path
    backup_path: Path
    from_version: int
    to_version: int


class ProjectMigrationFiles:
    """Narrow filesystem boundary for fault injection and SQLite-safe copying."""

    def copy_database(self, source: Path, destination: Path) -> None:
        with closing(_read_only_connection(source)) as source_connection:
            with closing(sqlite3.connect(destination)) as destination_connection:
                source_connection.backup(destination_connection)
        with destination.open("rb") as copied:
            os.fsync(copied.fileno())

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


class ProjectMigrationService:
    def __init__(self, *, files: ProjectMigrationFiles | None = None) -> None:
        self._files = files or ProjectMigrationFiles()

    def migrate(self, path: Path) -> MigrationResult:
        path = Path(path)
        backup_path = path.with_name(f"{path.name}.pre-v2-backup")
        source_snapshot: Path | None = None
        backup_temp: Path | None = None
        migrated_temp: Path | None = None
        try:
            source_snapshot = self._temporary(path)
            self._snapshot_source(path, source_snapshot)
            self._validate(source_snapshot, version=1)
            backup_temp = self._temporary(path)
            self._files.copy_database(source_snapshot, backup_temp)
            self._validate(backup_temp, version=1, code="project.migration_invalid_backup")
            self._files.replace(backup_temp, backup_path)
            backup_temp = None

            migrated_temp = self._temporary(path)
            self._files.copy_database(backup_path, migrated_temp)
            self._rewrite_schema(migrated_temp)
            self._validate(migrated_temp, version=2, code="project.migration_invalid_staging")
            self._files.replace(migrated_temp, path)
            migrated_temp = None
            return MigrationResult(path, backup_path, 1, 2)
        except ProjectMigrationError:
            raise
        except (OSError, sqlite3.Error, ProjectError, ValueError, TypeError, KeyError) as error:
            raise ProjectMigrationError("project.migration_failed") from error
        finally:
            for temporary in (source_snapshot, backup_temp, migrated_temp):
                if temporary is not None:
                    for suffix in ("", "-wal", "-shm"):
                        Path(f"{temporary}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _temporary(path: Path) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        os.close(descriptor)
        return Path(name)

    @staticmethod
    def _snapshot_source(source: Path, destination: Path) -> None:
        shutil.copyfile(source, destination)
        source_wal = Path(f"{source}-wal")
        if source_wal.is_file():
            shutil.copyfile(source_wal, Path(f"{destination}-wal"))

    @staticmethod
    def _validate(
        path: Path, *, version: int, code: str = "project.migration_invalid_source",
    ) -> None:
        try:
            store = ProjectStore.open(path)
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if row is None or int(row[0]) != version:
                    raise ValueError("unexpected schema version")
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("SQLite integrity check failed")
                revisions = connection.execute(
                    "SELECT payload_json, payload_sha256 FROM revisions ORDER BY revision DESC"
                ).fetchall()
            if not revisions:
                raise ValueError("no project revisions")
            for payload_text, expected_hash in revisions:
                if sha256(payload_text.encode("utf-8")).hexdigest() != expected_hash:
                    raise ValueError("revision hash mismatch")
                state = ProjectState.from_payload(json.loads(payload_text))
                if state.schema_version != version:
                    raise ValueError("payload schema mismatch")
            store.load()
        except (
            OSError, sqlite3.Error, ProjectError, ValueError, TypeError, KeyError,
            AttributeError, IndexError, OverflowError,
        ) as error:
            raise ProjectMigrationError(code) from error

    @staticmethod
    def _rewrite_schema(path: Path) -> None:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                rows = connection.execute("SELECT revision, payload_json FROM revisions").fetchall()
                for revision, payload_text in rows:
                    state = replace(ProjectState.from_payload(json.loads(payload_text)), schema_version=2)
                    migrated_text = json.dumps(
                        state.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    )
                    connection.execute(
                        "UPDATE revisions SET payload_json=?, payload_sha256=? WHERE revision=?",
                        (migrated_text, sha256(migrated_text.encode("utf-8")).hexdigest(), revision),
                    )
                connection.execute(
                    "UPDATE metadata SET value='2' WHERE key='schema_version'"
                )
        with path.open("rb") as migrated:
            os.fsync(migrated.fileno())
