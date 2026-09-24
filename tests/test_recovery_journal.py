from __future__ import annotations

import json
from pathlib import Path

import pytest

from certificate_automation.recovery import RecoveryService


def test_recovery_discovers_interrupted_rename_without_promoting_it(tmp_path):
    final = tmp_path / "Awards-revision-1"
    final.mkdir()
    (final / "batch_journal.json").write_text(json.dumps({
        "schema_version": 1, "batch_id": "batch-1", "state": "ready_to_publish",
    }), encoding="utf-8")
    records = RecoveryService().find_incomplete(tmp_path)
    assert len(records) == 1
    assert records[0].path == final
    assert records[0].publication_interrupted is True
    assert final.exists()


def test_recovery_lists_valid_orphan_publication_intent(tmp_path):
    from certificate_automation.batch_journal import BatchJournal

    intent = BatchJournal.create_publish_intent(
        tmp_path, "batch-orphan", "Awards-revision-3", "a" * 64, 3,
    )
    records = RecoveryService().find_incomplete(tmp_path)

    assert any(
        record.batch_id == "batch-orphan"
        and record.path == tmp_path / "Awards-revision-3"
        and record.diagnostic_path == intent
        and record.publication_interrupted
        for record in records
    )


def test_recovery_rejects_malformed_and_traversal_publish_intents(tmp_path):
    prefix = ".certificate-publish-intent-"
    payload = {
        "schema_version": 1,
        "status": "pending",
        "approval_digest": "a" * 64,
        "revision": 2,
        "created_at": "2026-09-24T00:00:00Z",
    }
    traversal = dict(payload, batch_id="traversal", final_name="../outside-revision-2")
    malformed = dict(payload, batch_id="malformed", final_name="Awards-revision-2", revision=True)
    (tmp_path / f"{prefix}traversal.json").write_text(json.dumps(traversal), encoding="utf-8")
    (tmp_path / f"{prefix}malformed.json").write_text(json.dumps(malformed), encoding="utf-8")

    assert RecoveryService().find_incomplete(tmp_path) == ()


def test_recovery_glob_denial_reports_uncertain_root_without_deleting(tmp_path, monkeypatch):
    from certificate_automation.recovery import RecoveryScanError
    incomplete = tmp_path / ".certificate-incomplete-safe"
    incomplete.mkdir()
    original_glob = Path.glob

    def denied(self, pattern):
        if self == tmp_path:
            raise PermissionError("glob denied")
        return original_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", denied)
    with pytest.raises(RecoveryScanError) as caught:
        RecoveryService().find_incomplete(tmp_path)
    assert caught.value.code == "recovery.scan_unavailable"
    assert caught.value.root_unavailable
    assert incomplete.is_dir()


def test_recovery_journal_open_denial_keeps_partial_safe_records(tmp_path, monkeypatch):
    from certificate_automation.recovery import RecoveryScanError
    incomplete = tmp_path / ".certificate-incomplete-safe"
    incomplete.mkdir()
    revision = tmp_path / "Awards-revision-1"
    revision.mkdir()
    journal = revision / "batch_journal.json"
    journal.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def denied(self, *args, **kwargs):
        if self == journal:
            raise PermissionError("journal locked")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(RecoveryScanError) as caught:
        RecoveryService().find_incomplete(tmp_path)
    assert any(record.path == incomplete for record in caught.value.records)
    assert revision in caught.value.unavailable_paths
    assert incomplete.is_dir() and revision.is_dir()


def test_recovery_definite_disappearing_entry_is_skipped(tmp_path, monkeypatch):
    disappearing = tmp_path / ".certificate-incomplete-vanished"
    disappearing.mkdir()
    original_stat = Path.stat

    def vanished(self, *args, **kwargs):
        if self == disappearing:
            raise FileNotFoundError(2, "moved during scan", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", vanished)
    assert RecoveryService().find_incomplete(tmp_path) == ()


def test_recovery_root_permission_stat_error_is_unavailable(tmp_path, monkeypatch):
    from certificate_automation.recovery import RecoveryScanError
    import errno

    original_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self == tmp_path:
            raise PermissionError(errno.EACCES, "access denied", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(RecoveryScanError) as caught:
        RecoveryService().find_incomplete(tmp_path)
    assert caught.value.root_unavailable


def test_recovery_entry_permission_stat_error_is_unavailable(tmp_path, monkeypatch):
    from certificate_automation.recovery import RecoveryScanError
    import errno

    incomplete = tmp_path / ".certificate-incomplete-locked"
    incomplete.mkdir()
    original_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self == incomplete:
            raise PermissionError(errno.EPERM, "operation not permitted", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(RecoveryScanError) as caught:
        RecoveryService().find_incomplete(tmp_path)
    assert incomplete in caught.value.unavailable_paths


def test_recovery_missing_root_or_entry_is_skipped(tmp_path, monkeypatch):
    missing = tmp_path / ".certificate-incomplete-gone"
    original_stat = Path.stat

    def vanished(self, *args, **kwargs):
        if self == missing:
            raise FileNotFoundError(2, "not found", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", vanished)
    assert RecoveryService().find_incomplete(tmp_path) == ()
    assert RecoveryService().find_incomplete(tmp_path / "absent-root") == ()


def test_unreadable_publish_intent_cannot_be_silently_ignored(tmp_path, monkeypatch):
    from certificate_automation.batch_journal import BatchJournal
    from certificate_automation.recovery import RecoveryScanError
    intent = BatchJournal.create_publish_intent(
        tmp_path, "batch-locked", "Awards-revision-1", "a" * 64, 1,
    )
    original_read_text = Path.read_text

    def denied(self, *args, **kwargs):
        if self == intent:
            raise PermissionError("intent locked")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(RecoveryScanError) as caught:
        RecoveryService().find_incomplete(tmp_path)
    assert caught.value.root_unavailable
    assert intent.exists()
