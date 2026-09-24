from __future__ import annotations

import json

import pytest

from certificate_automation.batch_journal import BatchJournal, JournalError, JournalState


def _request():
    return {
        "batch_id": "batch-1", "approval_digest": "a" * 64,
        "destination": "/official", "revision": 1, "intended_counts": {"recipients": 2},
    }


def test_journal_persists_monotonic_state_and_checkpoint(tmp_path):
    journal = BatchJournal.create(tmp_path, _request())
    assert BatchJournal.open(journal.path).state is JournalState.CREATED
    for state in (JournalState.RENDERING, JournalState.VERIFYING, JournalState.READY_TO_PUBLISH, JournalState.PUBLISHED):
        journal.transition(state)
        assert BatchJournal.open(journal.path).state is state
    payload = json.loads(journal.path.read_text("utf-8"))
    assert payload["approval_digest"] == "a" * 64
    assert payload["revision"] == 1


@pytest.mark.parametrize("current,next_state", [
    (JournalState.CREATED, JournalState.VERIFYING),
    (JournalState.RENDERING, JournalState.CREATED),
    (JournalState.PUBLISHED, JournalState.VERIFYING),
])
def test_journal_rejects_skipped_or_backward_transition(tmp_path, current, next_state):
    journal = BatchJournal.create(tmp_path, _request())
    for state in (JournalState.RENDERING, JournalState.VERIFYING, JournalState.READY_TO_PUBLISH, JournalState.PUBLISHED):
        if state is current:
            journal.transition(state)
            break
        journal.transition(state)
    with pytest.raises(JournalError, match="journal.invalid_transition"):
        journal.transition(next_state)


def test_failed_atomic_replace_preserves_last_valid_record(tmp_path, monkeypatch):
    journal = BatchJournal.create(tmp_path, _request())
    import certificate_automation.batch_journal as module
    def fail_replace(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(JournalError):
        journal.transition(JournalState.RENDERING)
    assert BatchJournal.open(journal.path).state is JournalState.CREATED
