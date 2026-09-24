from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from certificate_automation.history import (
    DuplicatePolicy, HistoryEntry, HistoryError, HistoryIndex, HistoryStatus, PublishedBatch,
)
from certificate_automation.windows_protection import ProtectionError


class MemoryProtector:
    def protect(self, value: bytes, *, purpose: str) -> bytes:
        return purpose.encode() + b":" + value[::-1]

    def unprotect(self, value: bytes, *, purpose: str) -> bytes:
        prefix = purpose.encode() + b":"
        if not value.startswith(prefix):
            raise ProtectionError("history.protection_unavailable")
        return value[len(prefix):][::-1]


class BrokenProtector(MemoryProtector):
    def unprotect(self, value: bytes, *, purpose: str) -> bytes:
        raise ProtectionError("history.protection_unavailable")


def _batch(folder: Path, batch_id: str = "B-1") -> PublishedBatch:
    return PublishedBatch(batch_id, 1, datetime(2026, 9, 22, tzinfo=timezone.utc), folder)


def test_history_matches_normalized_identity_without_plaintext_on_disk(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    index.record(_batch(tmp_path / "official"), identities=("Ana García", "Gold"), certificate_id="CERT-7")

    check = HistoryIndex(index.path, MemoryProtector()).check((" ana garci\u0301a ", "GOLD"))
    assert check.status is HistoryStatus.MATCH
    assert [(match.kind, match.batch_id, match.revision) for match in check.matches] == [
        ("identity", "B-1", 1)
    ]
    assert HistoryIndex(index.path, MemoryProtector()).check(("Someone else",)).status is HistoryStatus.CLEAN
    for path in tmp_path.glob("history.sqlite*"):
        assert b"Ana" not in path.read_bytes()
        assert b"CERT-7" not in path.read_bytes()


def test_certificate_id_match_is_keyed_and_reported(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    index.record(_batch(tmp_path), identities=("Ana",), certificate_id="CERT-7")
    check = index.check(("Other",), certificate_id=" cert-7 ")
    assert check.status is HistoryStatus.MATCH
    assert [(match.kind, match.batch_id) for match in check.matches] == [("certificate_id", "B-1")]


def test_empty_history_query_never_claims_no_duplicates(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    assert index.check(()).status is HistoryStatus.UNAVAILABLE
    assert not index.path.exists()


@pytest.mark.parametrize("mode", ["missing_key", "both_key_fields_missing", "corrupt_ciphertext", "wrong_user", "wrong_but_valid_key"])
def test_key_failure_is_unavailable_never_false_clean(tmp_path, mode):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    index.record(_batch(tmp_path), identities=("Ana",))
    with sqlite3.connect(index.path) as connection:
        if mode == "missing_key":
            connection.execute("DELETE FROM metadata WHERE key='protected_key'")
        elif mode == "both_key_fields_missing":
            connection.execute("DELETE FROM metadata WHERE key IN ('protected_key', 'key_verifier')")
        elif mode == "corrupt_ciphertext":
            connection.execute("UPDATE metadata SET value=? WHERE key='protected_key'", (b"damage",))
        elif mode == "wrong_but_valid_key":
            connection.execute("UPDATE metadata SET value=? WHERE key='protected_key'", (MemoryProtector().protect(b"X" * 32, purpose="history-key"),))
    protector = BrokenProtector() if mode == "wrong_user" else MemoryProtector()
    result = HistoryIndex(index.path, protector).check(("Ana",))
    assert result.status is HistoryStatus.UNAVAILABLE
    assert result.matches == ()
    assert result.issue_code == "history.unavailable"


def test_clear_only_removes_history_and_preserves_official_folder(tmp_path):
    folder = tmp_path / "official"
    folder.mkdir()
    (folder / "certificate.pdf").write_bytes(b"official bytes")
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    index.record(_batch(folder), identities=("Ana",))
    index.clear()
    assert index.check(("Ana",)).status is HistoryStatus.CLEAN
    assert (folder / "certificate.pdf").read_bytes() == b"official bytes"


def test_concurrent_records_keep_both_entries_and_one_key(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda pair: index.record(_batch(tmp_path, pair[0]), identities=(pair[1],)),
                      (("B-1", "Ana"), ("B-2", "Bea"))))
    assert index.check(("Ana",)).status is HistoryStatus.MATCH
    assert index.check(("Bea",)).status is HistoryStatus.MATCH
    with sqlite3.connect(index.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM metadata WHERE key='protected_key'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2


def test_record_batch_rolls_back_all_rows_when_one_is_invalid(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    assert index.check(("Ana",)).status is HistoryStatus.CLEAN


def test_record_batch_rejects_incomplete_selected_identity_even_with_certificate_id(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    assert index.check(("Ana",)).status is HistoryStatus.CLEAN
    with pytest.raises(HistoryError) as caught:
        index.record_batch(_batch(tmp_path), (HistoryEntry(("",), "CERT-1"),))
    assert caught.value.code == "history.missing_identity"
    assert index.check((), certificate_id="CERT-1").status is HistoryStatus.CLEAN
    with pytest.raises(HistoryError):
        index.record_batch(_batch(tmp_path), (
            HistoryEntry(("Ana",), "CERT-1"),
            HistoryEntry((), None),
        ))
    assert index.check(("Ana",)).status is HistoryStatus.CLEAN


def test_repeating_same_published_batch_is_idempotent(tmp_path):
    index = HistoryIndex(tmp_path / "history.sqlite", MemoryProtector())
    batch = _batch(tmp_path)
    index.record_batch(batch, (HistoryEntry(("Ana",), "CERT-1"),))
    index.record_batch(batch, (HistoryEntry(("Ana",), "CERT-1"),))
    assert len(index.check(("Ana",)).matches) == 1


@pytest.mark.parametrize("payload", [
    {"identity_columns": "full_name"},
    {"check_history": "false"},
    {"identity_columns": ["full_name", "full_name"]},
])
def test_malformed_policy_is_rejected_instead_of_silently_changed(payload):
    with pytest.raises(HistoryError):
        DuplicatePolicy.from_json(payload)


def test_policy_json_defaults_are_off_and_round_trip(tmp_path):
    assert DuplicatePolicy.from_json({}) == DuplicatePolicy(None, (), False)
    policy = DuplicatePolicy("certificate_id", ("full_name", "birth_date"), True)
    assert DuplicatePolicy.from_json(policy.to_json()) == policy
