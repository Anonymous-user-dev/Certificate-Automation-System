from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
import subprocess
import sys

import pytest

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.project import ProjectState, ProjectStore
from certificate_automation.project_migration import (
    ProjectMigrationError,
    ProjectMigrationFiles,
    ProjectMigrationService,
)


@pytest.fixture
def schema1_project(tmp_path):
    path = tmp_path / "source.certproject"
    dataset = TabularDataset(
        (Column("name", "Name"),),
        (DataRow("row-1", 1, {"name": "Ana García"}),),
        SourceSnapshot(
            "manual", "People", None, "a" * 64,
            datetime(2026, 9, 22, tzinfo=timezone.utc), {},
        ),
    )
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '1')")
        connection.execute("CREATE TABLE revisions (revision INTEGER PRIMARY KEY, saved_at TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)")
        for revision, step in ((1, "data"), (2, "review")):
            payload = ProjectState(revision=revision, dataset=dataset, active_step=step).to_payload()
            for field in ("schema_version", "project_name", "profile_path", "approval", "published_revisions", "print_settings"):
                payload.pop(field, None)
            payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?)",
                (revision, "2026-09-22T00:00:00+00:00", payload_text, sha256(payload_text.encode("utf-8")).hexdigest()),
            )
    return path


def test_migration_creates_valid_backup_before_replacing_source(schema1_project):
    result = ProjectMigrationService().migrate(schema1_project)

    assert result.path == schema1_project
    assert result.from_version == 1
    assert result.to_version == 2
    assert result.backup_path == schema1_project.with_name("source.certproject.pre-v2-backup")
    assert result.backup_path.is_file()
    assert ProjectStore.open(result.backup_path).load().schema_version == 1
    migrated = ProjectStore.open(schema1_project).load()
    assert migrated.schema_version == 2
    assert migrated.revision == 2
    assert migrated.dataset.rows[0].value("name") == "Ana García"


class FaultFiles(ProjectMigrationFiles):
    def __init__(self, failure):
        self.failure = failure
        self.copy_calls = 0

    def copy_database(self, source, destination):
        self.copy_calls += 1
        if self.failure == "disk_full":
            raise OSError("disk full")
        if self.failure == "backup_invalid" and self.copy_calls == 1:
            destination.write_bytes(b"not sqlite")
            return
        return super().copy_database(source, destination)

    def replace(self, source, destination):
        if self.failure == "replacement_locked" and destination.suffix == ".certproject":
            raise PermissionError("locked")
        return super().replace(source, destination)


@pytest.mark.parametrize("failure", ["backup_invalid", "disk_full", "replacement_locked"])
def test_migration_failure_keeps_original_bytes(schema1_project, failure):
    before = schema1_project.read_bytes()
    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=FaultFiles(failure)).migrate(schema1_project)

    assert caught.value.code.startswith("project.")
    if failure == "backup_invalid":
        assert caught.value.code == "project.migration_invalid_backup"
    assert schema1_project.read_bytes() == before


def test_truncated_sqlite_fails_without_changing_bytes(tmp_path):
    path = tmp_path / "truncated.certproject"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 20)
    before = path.read_bytes()

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService().migrate(path)

    assert caught.value.code.startswith("project.")
    assert path.read_bytes() == before


def test_wrong_newest_payload_hash_fails_without_changing_bytes(schema1_project):
    with closing(sqlite3.connect(schema1_project)) as connection, connection:
        connection.execute("UPDATE revisions SET payload_sha256='bad' WHERE revision=2")
    before = schema1_project.read_bytes()

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService().migrate(schema1_project)

    assert caught.value.code == "project.migration_invalid_source"
    assert schema1_project.read_bytes() == before


@pytest.mark.parametrize("failure", ["disk_full", "replacement_locked"])
def test_pending_wal_failure_preserves_all_source_bytes(schema1_project, failure):
    script = """
import os
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA journal_mode=WAL')
connection.execute('PRAGMA wal_autocheckpoint=0')
connection.execute("UPDATE revisions SET saved_at='2026-09-23T12:00:00+00:00' WHERE revision=2")
connection.commit()
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(schema1_project)], check=True)
    wal = schema1_project.with_name(f"{schema1_project.name}-wal")
    shm = schema1_project.with_name(f"{schema1_project.name}-shm")
    assert wal.is_file() and wal.stat().st_size > 0
    before = {path: path.read_bytes() if path.exists() else None for path in (schema1_project, wal, shm)}

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=FaultFiles(failure)).migrate(schema1_project)

    assert caught.value.code.startswith("project.")
    assert {path: path.read_bytes() if path.exists() else None for path in before} == before
    if failure == "replacement_locked":
        backup = schema1_project.with_name(f"{schema1_project.name}.pre-v2-backup")
        with sqlite3.connect(backup) as connection:
            saved_at = connection.execute(
                "SELECT saved_at FROM revisions WHERE revision=2"
            ).fetchone()[0]
        assert saved_at == "2026-09-23T12:00:00+00:00"


def test_hash_valid_malformed_revision_has_stable_error(schema1_project):
    with closing(sqlite3.connect(schema1_project)) as connection, connection:
        payload_text = connection.execute(
            "SELECT payload_json FROM revisions WHERE revision=2"
        ).fetchone()[0]
        payload = json.loads(payload_text)
        payload["dataset"]["rows"][0]["values"] = []
        malformed = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "UPDATE revisions SET payload_json=?, payload_sha256=? WHERE revision=2",
            (malformed, sha256(malformed.encode("utf-8")).hexdigest()),
        )
    before = schema1_project.read_bytes()

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService().migrate(schema1_project)

    assert caught.value.code == "project.migration_invalid_source"
    assert schema1_project.read_bytes() == before


def test_migration_accepts_unicode_path(tmp_path, schema1_project):
    path = tmp_path / "项目 Анна.certproject"
    path.write_bytes(schema1_project.read_bytes())

    result = ProjectMigrationService().migrate(path)

    assert result.path == path
    assert ProjectStore.open(path).load().schema_version == 2


def test_migration_accepts_long_path_when_filesystem_supports_it(tmp_path, schema1_project):
    parent = tmp_path / ("segment" * 12) / ("subfolder" * 10) / ("directory" * 10)
    try:
        parent.mkdir(parents=True)
    except OSError:
        pytest.skip("filesystem does not support this path length")
    path = parent / "people.certproject"
    if len(str(path)) <= 260:
        pytest.skip("temporary path did not exceed 260 characters")
    path.write_bytes(schema1_project.read_bytes())

    ProjectMigrationService().migrate(path)

    assert ProjectStore.open(path).load().schema_version == 2
