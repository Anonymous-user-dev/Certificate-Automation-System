from __future__ import annotations

import json

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
