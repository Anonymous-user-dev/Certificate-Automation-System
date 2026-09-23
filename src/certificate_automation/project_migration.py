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
            source_state = self._source_fingerprint(path)
            source_snapshot = self._temporary(path)
            self._snapshot_source(path, source_snapshot)
            self._assert_source_unchanged(path, source_state)
            if self._file_digest(source_snapshot) != source_state[0] or (
                self._file_digest(Path(f"{source_snapshot}-wal")) != source_state[1]
            ):
                raise ProjectMigrationError("project.migration_source_changed")
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
            self._remove_temporary(source_snapshot)
            source_snapshot = None
            self._publish(migrated_temp, path, source_state)
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
                        try:
                            Path(f"{temporary}{suffix}").unlink(missing_ok=True)
                        except OSError:
                            pass

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
    def _remove_temporary(path: Path) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _file_digest(path: Path) -> str | None:
        try:
            with path.open("rb") as source:
                digest = sha256()
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                return digest.hexdigest()
        except FileNotFoundError:
            return None

    @classmethod
    def _source_fingerprint(cls, path: Path) -> tuple[str | None, str | None, str | None]:
        return tuple(cls._file_digest(Path(f"{path}{suffix}")) for suffix in ("", "-wal", "-shm"))

    @classmethod
    def _assert_source_unchanged(
        cls, path: Path, expected: tuple[str | None, str | None, str | None]
    ) -> None:
        if cls._source_fingerprint(path) != expected:
            raise ProjectMigrationError("project.migration_source_changed")

    def _publish(
        self, migrated: Path, path: Path,
        expected: tuple[str | None, str | None, str | None],
    ) -> None:
        self._assert_source_unchanged(path, expected)
        quarantined: list[tuple[Path, Path, str]] = []
        moved: list[tuple[Path, Path, str]] = []
        published = False
        restored = False
        try:
            for suffix, digest in zip(("-wal", "-shm"), expected[1:], strict=True):
                if digest is None:
                    continue
                sidecar = Path(f"{path}{suffix}")
                stash = self._temporary(path)
                quarantined.append((sidecar, stash, digest))
                self._files.replace(sidecar, stash)
                moved.append((sidecar, stash, digest))
            if self._file_digest(path) != expected[0] or any(
                self._file_digest(Path(f"{path}{suffix}")) is not None
                for suffix in ("-wal", "-shm")
            ) or any(
                self._file_digest(stash) != digest
                for _, stash, digest in moved
            ):
                raise ProjectMigrationError("project.migration_source_changed")
            self._files.replace(migrated, path)
            published = True
        except Exception:
            for sidecar, stash, _ in reversed(moved):
                if sidecar.exists():
                    raise ProjectMigrationError("project.migration_rollback_failed")
                try:
                    os.replace(stash, sidecar)
                except OSError as error:
                    raise ProjectMigrationError("project.migration_rollback_failed") from error
            restored = True
            raise
        finally:
            if published or restored or not moved:
                for _, stash, _ in quarantined:
                    try:
                        stash.unlink(missing_ok=True)
                    except OSError:
                        pass

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
