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
