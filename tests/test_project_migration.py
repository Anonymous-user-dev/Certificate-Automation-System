from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

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


def _leave_pending_wal(path):
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
    subprocess.run([sys.executable, "-c", script, str(path)], check=True)


@pytest.mark.parametrize("failure", ["disk_full", "replacement_locked"])
def test_pending_wal_failure_preserves_all_source_bytes(schema1_project, failure):
    _leave_pending_wal(schema1_project)
    wal = schema1_project.with_name(f"{schema1_project.name}-wal")
    shm = schema1_project.with_name(f"{schema1_project.name}-shm")
    assert wal.is_file() and wal.stat().st_size > 0
    before = {path: path.read_bytes() if path.exists() else None for path in (schema1_project, wal, shm)}

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=FaultFiles(failure)).migrate(schema1_project)

    assert caught.value.code.startswith("project.")
    assert {path: path.read_bytes() if path.exists() else None for path in before} == before
    assert not list(schema1_project.parent.glob(".source.certproject.*.tmp"))
    if failure == "replacement_locked":
        backup = schema1_project.with_name(f"{schema1_project.name}.pre-v2-backup")
        with sqlite3.connect(backup) as connection:
            saved_at = connection.execute(
                "SELECT saved_at FROM revisions WHERE revision=2"
            ).fetchone()[0]
        assert saved_at == "2026-09-23T12:00:00+00:00"


def test_pending_wal_success_publishes_schema2_without_stale_sidecars(schema1_project):
    _leave_pending_wal(schema1_project)
    wal = schema1_project.with_name(f"{schema1_project.name}-wal")
    shm = schema1_project.with_name(f"{schema1_project.name}-shm")
    assert wal.is_file() and shm.is_file()

    result = ProjectMigrationService().migrate(schema1_project)

    assert not wal.exists()
    assert not shm.exists()
    migrated = ProjectStore.open(schema1_project).load()
    assert migrated.schema_version == 2
    assert migrated.revision == 2
    backup = ProjectStore.open(result.backup_path).load()
    assert backup.schema_version == 1
    with sqlite3.connect(result.backup_path) as connection:
        saved_at = connection.execute(
            "SELECT saved_at FROM revisions WHERE revision=2"
        ).fetchone()[0]
    assert saved_at == "2026-09-23T12:00:00+00:00"


@pytest.mark.parametrize("sidecar", ["-wal", "-shm"])
def test_changed_source_sidecar_blocks_publication(schema1_project, sidecar):
    _leave_pending_wal(schema1_project)
    source_sidecar = schema1_project.with_name(f"{schema1_project.name}{sidecar}")
    original_db = schema1_project.read_bytes()
    original_wal = schema1_project.with_name(f"{schema1_project.name}-wal").read_bytes()

    class ChangingFiles(ProjectMigrationFiles):
        def replace(self, source, destination):
            super().replace(source, destination)
            if destination.name.endswith(".pre-v2-backup"):
                source_sidecar.write_bytes(source_sidecar.read_bytes() + b"external-change")

    changed_bytes = source_sidecar.read_bytes() + b"external-change"
    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=ChangingFiles()).migrate(schema1_project)

    assert caught.value.code == "project.migration_source_changed"
    assert schema1_project.read_bytes() == original_db
    assert source_sidecar.read_bytes() == changed_bytes
    if sidecar == "-shm":
        assert schema1_project.with_name(f"{schema1_project.name}-wal").read_bytes() == original_wal


def test_sidecar_change_during_snapshot_blocks_migration(schema1_project):
    _leave_pending_wal(schema1_project)
    shm = schema1_project.with_name(f"{schema1_project.name}-shm")
    original_db = schema1_project.read_bytes()
    original_wal = schema1_project.with_name(f"{schema1_project.name}-wal").read_bytes()

    class ChangingSnapshotService(ProjectMigrationService):
        @staticmethod
        def _snapshot_source(source, destination):
            ProjectMigrationService._snapshot_source(source, destination)
            shm.write_bytes(shm.read_bytes() + b"external-change")

    changed_shm = shm.read_bytes() + b"external-change"
    with pytest.raises(ProjectMigrationError) as caught:
        ChangingSnapshotService().migrate(schema1_project)

    assert caught.value.code == "project.migration_source_changed"
    assert schema1_project.read_bytes() == original_db
    assert schema1_project.with_name(f"{schema1_project.name}-wal").read_bytes() == original_wal
    assert shm.read_bytes() == changed_shm


def test_locked_sidecar_publication_restores_source_without_temp_leaks(schema1_project):
    _leave_pending_wal(schema1_project)
    paths = [schema1_project, Path(f"{schema1_project}-wal"), Path(f"{schema1_project}-shm")]
    before = {path: path.read_bytes() for path in paths}

    class LockedSidecarFiles(ProjectMigrationFiles):
        def replace(self, source, destination):
            if source.name.endswith("-shm"):
                raise PermissionError("sidecar locked")
            return super().replace(source, destination)

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=LockedSidecarFiles()).migrate(schema1_project)

    assert caught.value.code == "project.migration_failed"
    assert {path: path.read_bytes() for path in paths} == before
    assert not list(schema1_project.parent.glob(".source.certproject.*.tmp"))


@pytest.mark.parametrize("sidecar", ["-wal", "-shm"])
def test_sidecar_move_then_raise_restores_all_original_bytes(schema1_project, sidecar):
    _leave_pending_wal(schema1_project)
    paths = [schema1_project, Path(f"{schema1_project}-wal"), Path(f"{schema1_project}-shm")]
    before = {path: path.read_bytes() for path in paths}

    class MoveThenRaiseFiles(ProjectMigrationFiles):
        def replace(self, source, destination):
            if source.name.endswith(sidecar):
                super().replace(source, destination)
                raise PermissionError("moved, then denied")
            return super().replace(source, destination)

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=MoveThenRaiseFiles()).migrate(schema1_project)

    assert caught.value.code == "project.migration_failed"
    assert {path: path.read_bytes() for path in paths} == before
    assert not list(schema1_project.parent.glob(".source.certproject.*.tmp"))


def test_postreplace_shm_failure_restores_original_set(schema1_project):
    _leave_pending_wal(schema1_project)
    paths = [schema1_project, Path(f"{schema1_project}-wal"), Path(f"{schema1_project}-shm")]
    before = {path: path.read_bytes() for path in paths}
    saw_database_replace = False

    class LateShmFailure(ProjectMigrationFiles):
        def replace(self, source, destination):
            nonlocal saw_database_replace
            if destination == schema1_project:
                saw_database_replace = True
            if saw_database_replace and source.name.endswith("-shm"):
                raise PermissionError("late SHM move denied")
            return super().replace(source, destination)

    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=LateShmFailure()).migrate(schema1_project)

    assert saw_database_replace
    assert caught.value.code == "project.migration_failed"
    assert {path: path.read_bytes() for path in paths} == before
    assert not list(schema1_project.parent.glob(".source.certproject.*.tmp"))


@pytest.mark.skipif(sys.platform != "linux", reason="exercises Linux SQLite POSIX locks")
@pytest.mark.parametrize("journal_mode", ["WAL", "DELETE"])
def test_active_sqlite_writer_rejects_migration_without_changing_source(schema1_project, journal_mode):
    script = """
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1], timeout=0)
connection.execute('PRAGMA journal_mode=' + sys.argv[2])
connection.execute('BEGIN IMMEDIATE')
connection.execute("UPDATE revisions SET saved_at='writer-pending' WHERE revision=2")
print('READY', flush=True)
sys.stdin.readline()
connection.rollback()
connection.close()
"""
    writer = subprocess.Popen(
        [sys.executable, "-c", script, str(schema1_project), journal_mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert writer.stdout.readline().strip() == "READY"
        paths = [
            schema1_project, Path(f"{schema1_project}-wal"),
            Path(f"{schema1_project}-shm"), Path(f"{schema1_project}-journal"),
        ]
        before = {path: path.read_bytes() if path.exists() else None for path in paths}

        started = time.monotonic()
        with pytest.raises(ProjectMigrationError) as caught:
            ProjectMigrationService().migrate(schema1_project)
        elapsed = time.monotonic() - started

        assert caught.value.code == "project.migration_source_busy"
        assert elapsed < 2
        assert {path: path.read_bytes() if path.exists() else None for path in paths} == before
    finally:
        writer.stdin.write("\n")
        writer.stdin.flush()
        writer.communicate(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="exercises Linux SQLite POSIX locks")
def test_lease_excludes_writer_at_final_replace(schema1_project):
    from certificate_automation.project_migration import ProjectMigrationLease

    _leave_pending_wal(schema1_project)
    lease_active = False
    writer_blocked = False

    class TrackingLease(ProjectMigrationLease):
        def __enter__(self):
            nonlocal lease_active
            result = super().__enter__()
            lease_active = True
            return result

        def __exit__(self, *args):
            nonlocal lease_active
            lease_active = False
            return super().__exit__(*args)

    class ProbingFiles(ProjectMigrationFiles):
        def replace(self, source, destination):
            nonlocal writer_blocked
            if destination == schema1_project:
                assert lease_active
                probe = subprocess.run(
                    [sys.executable, "-c", "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDWR); fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB,1,120)", f"{schema1_project}-shm"],
                    capture_output=True, text=True, timeout=5,
                )
                writer_blocked = probe.returncode != 0 and "BlockingIOError" in probe.stderr
            return super().replace(source, destination)

    ProjectMigrationService(files=ProbingFiles(), lease_factory=TrackingLease).migrate(schema1_project)

    assert writer_blocked
    assert not lease_active
    assert ProjectStore.open(schema1_project).load().schema_version == 2


@pytest.mark.skipif(sys.platform != "linux", reason="exercises Linux SQLite POSIX locks")
@pytest.mark.parametrize("fail_after_replace", [False, True])
@pytest.mark.parametrize("probe_at", ["snapshot", "final_replace"])
def test_real_sqlite_writer_at_final_replace_preserves_publication(
    schema1_project, fail_after_replace, probe_at,
):
    _leave_pending_wal(schema1_project)
    paths = [schema1_project, Path(f"{schema1_project}-wal"), Path(f"{schema1_project}-shm")]
    before = {path: path.read_bytes() for path in paths}
    probes = []
    script = """
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1], timeout=0)
try:
    connection.execute('BEGIN IMMEDIATE')
except sqlite3.OperationalError as error:
    print(error.sqlite_errorname)
else:
    print('WRITER_ENTERED')
finally:
    connection.close()
"""

    def probe_writer():
        probes.append(subprocess.run(
            [sys.executable, "-c", script, str(schema1_project)],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip())

    class ProbingService(ProjectMigrationService):
        @staticmethod
        def _snapshot_source(source, destination):
            if probe_at == "snapshot":
                probe_writer()
            ProjectMigrationService._snapshot_source(source, destination)

    class ProbingFiles(ProjectMigrationFiles):
        def replace(self, source, destination):
            if destination == schema1_project and probe_at == "final_replace":
                probe_writer()
            if fail_after_replace and source.name.endswith("-shm"):
                raise PermissionError("SHM publication denied")
            return super().replace(source, destination)

    service = ProbingService(files=ProbingFiles())
    if fail_after_replace:
        with pytest.raises(ProjectMigrationError) as caught:
            service.migrate(schema1_project)
        assert caught.value.code == "project.migration_failed"
        assert {path: path.read_bytes() if path.exists() else None for path in paths} == before
    else:
        result = service.migrate(schema1_project)
        assert ProjectStore.open(schema1_project).load().schema_version == 2
        assert ProjectStore.open(result.backup_path).load().schema_version == 1
    assert probes == ["SQLITE_BUSY"]
    assert not list(schema1_project.parent.glob(".source.certproject.*.tmp*"))


@pytest.mark.skipif(sys.platform != "linux", reason="exercises Linux SQLite POSIX locks")
@pytest.mark.parametrize("failure", ["db_moved", "late_shm"])
def test_rollback_restores_leased_database_after_publication_failure(
    schema1_project, monkeypatch, failure,
):
    _leave_pending_wal(schema1_project)
    paths = [schema1_project, Path(f"{schema1_project}-wal"), Path(f"{schema1_project}-shm")]
    before = {path: path.read_bytes() for path in paths}
    original_replace = os.replace
    writer_results = []

    def probe_after_replace(source, destination):
        original_replace(source, destination)
        if destination == schema1_project:
            probe = subprocess.run(
                [sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1], timeout=0); c.execute('BEGIN IMMEDIATE')", str(schema1_project)],
                capture_output=True, text=True, timeout=30,
            )
            writer_results.append(probe.returncode != 0 and "database is locked" in probe.stderr)

    class FailingFiles(ProjectMigrationFiles):
        def replace(self, source, destination):
            if failure == "late_shm" and source.name.endswith("-shm"):
                raise PermissionError("late SHM publication failure")
            super().replace(source, destination)
            if failure == "db_moved" and destination == schema1_project:
                raise PermissionError("database moved, then failure")

    monkeypatch.setattr(os, "replace", probe_after_replace)
    with pytest.raises(ProjectMigrationError) as caught:
        ProjectMigrationService(files=FailingFiles()).migrate(schema1_project)

    assert caught.value.code == "project.migration_failed"
    assert {path: path.read_bytes() if path.exists() else None for path in paths} == before
    assert writer_results == [True, True]  # Both installed and restored DBs stay leased.
    assert not list(schema1_project.parent.glob(".source.certproject.*.tmp*"))


def test_snapshot_cleanup_failure_never_reports_failed_migration_after_publication(
    schema1_project, monkeypatch
):
    _leave_pending_wal(schema1_project)
    paths = [schema1_project, Path(f"{schema1_project}-wal"), Path(f"{schema1_project}-shm")]
    before = {path: path.read_bytes() for path in paths}
    snapshot = None
    original_unlink = Path.unlink

    class CleanupFailService(ProjectMigrationService):
        @staticmethod
        def _temporary(path):
            nonlocal snapshot
            temporary = ProjectMigrationService._temporary(path)
            if snapshot is None:
                snapshot = temporary
            return temporary

    def fail_snapshot_cleanup(path, *args, **kwargs):
        if path == snapshot:
            raise OSError("snapshot locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_snapshot_cleanup)
    with pytest.raises(ProjectMigrationError) as caught:
        CleanupFailService().migrate(schema1_project)

    assert caught.value.code == "project.migration_failed"
    assert {path: path.read_bytes() for path in paths} == before


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
