"""Privacy-minimal local index for checking previously issued certificates."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
import unicodedata

from certificate_automation.windows_protection import ByteProtector, ProtectionError


SCHEMA_VERSION = 1
KEY_PURPOSE = "history-key"
KEY_TEST = b"certificate-automation-history-v1"
_WRITE_LOCK = RLock()


def _serialized_write(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with _WRITE_LOCK:
            return method(self, *args, **kwargs)
    return wrapper


class HistoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HistoryStatus(str, Enum):
    CLEAN = "clean"
    MATCH = "match"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DuplicatePolicy:
    certificate_id_column: str | None = None
    identity_columns: tuple[str, ...] = ()
    check_history: bool = False

    def __post_init__(self) -> None:
        columns = self.identity_columns
        if (
            not isinstance(columns, (tuple, list))
            or any(not isinstance(column, str) or not column.strip() for column in columns)
            or len(set(columns)) != len(columns)
            or self.certificate_id_column is not None
            and (not isinstance(self.certificate_id_column, str) or not self.certificate_id_column.strip())
            or type(self.check_history) is not bool
        ):
            raise HistoryError("history.invalid_policy")
        object.__setattr__(self, "identity_columns", tuple(columns))

    def to_json(self) -> dict[str, object]:
        return {
            "certificate_id_column": self.certificate_id_column,
            "identity_columns": list(self.identity_columns),
            "check_history": self.check_history,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "DuplicatePolicy":
        if not isinstance(payload, dict) or not isinstance(
            payload.get("identity_columns", ()), (list, tuple)
        ):
            raise HistoryError("history.invalid_policy")
        return cls(
            certificate_id_column=payload.get("certificate_id_column"),
            identity_columns=tuple(payload.get("identity_columns", ())),
            check_history=payload.get("check_history", False),
        )


@dataclass(frozen=True, slots=True)
class PublishedBatch:
    batch_id: str
    revision: int
    completed_at: datetime
    folder: Path

    def __post_init__(self) -> None:
        if not self.batch_id or self.revision < 0 or self.completed_at.tzinfo is None:
            raise HistoryError("history.invalid_batch")
        object.__setattr__(self, "folder", Path(self.folder))


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    identities: tuple[str, ...]
    certificate_id: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    kind: str
    batch_id: str
    revision: int
    completed_at: datetime
    folder: Path


@dataclass(frozen=True, slots=True)
class HistoryCheck:
    status: HistoryStatus
    matches: tuple[DuplicateMatch, ...] = ()
    issue_code: str | None = None


def normalize_identity(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(value)).strip().casefold().split())


def _digest(key: bytes, kind: str, values: tuple[str, ...]) -> str:
    canonical = json.dumps(
        [kind, *[normalize_identity(value) for value in values]],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


class HistoryIndex:
    """SQLite index containing keyed hashes and non-recipient batch metadata only."""

    def __init__(self, path: Path, protector: ByteProtector) -> None:
        self.path = Path(path)
        self.protector = protector

    def _connect(self, *, create_missing: bool = True) -> sqlite3.Connection:
        target = self.path if create_missing else f"{self.path.resolve().as_uri()}?mode=rw"
        connection = sqlite3.connect(target, timeout=15, uri=not create_missing)
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _key(self, connection: sqlite3.Connection, *, create: bool) -> bytes:
        try:
            rows = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        except sqlite3.Error as error:
            raise HistoryError("history.unavailable") from error
        if rows.get("schema_version") != str(SCHEMA_VERSION).encode("ascii"):
            raise HistoryError("history.unavailable")
        protected = rows.get("protected_key")
        verifier = rows.get("key_verifier")
        if protected is None and verifier is None and create:
            key = os.urandom(32)
            try:
                protected = self.protector.protect(key, purpose=KEY_PURPOSE)
            except ProtectionError as error:
                raise HistoryError("history.protection_unavailable") from error
            verifier = hmac.new(key, KEY_TEST, hashlib.sha256).digest()
            connection.execute("INSERT INTO metadata(key, value) VALUES('protected_key', ?)", (protected,))
            connection.execute("INSERT INTO metadata(key, value) VALUES('key_verifier', ?)", (verifier,))
            return key
        if protected is None or verifier is None:
            raise HistoryError("history.unavailable")
        try:
            key = self.protector.unprotect(protected, purpose=KEY_PURPOSE)
        except ProtectionError as error:
            raise HistoryError("history.protection_unavailable") from error
        if len(key) != 32 or not hmac.compare_digest(
            hmac.new(key, KEY_TEST, hashlib.sha256).digest(), verifier
        ):
            raise HistoryError("history.unavailable")
        return key

    def _prepare(self, connection: sqlite3.Connection, *, new_file: bool) -> None:
        if not new_file:
            return
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        connection.execute(
            """CREATE TABLE records (
                identity_hash TEXT,
                certificate_hash TEXT,
                batch_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                folder TEXT NOT NULL,
                CHECK (identity_hash IS NOT NULL OR certificate_hash IS NOT NULL)
            )"""
        )
        connection.execute("CREATE INDEX records_identity ON records(identity_hash)")
        connection.execute("CREATE INDEX records_certificate ON records(certificate_hash)")
        connection.execute(
            """CREATE UNIQUE INDEX records_batch_entry ON records(
                batch_id, revision, COALESCE(identity_hash, ''), COALESCE(certificate_hash, '')
            )"""
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION).encode("ascii"),),
        )

    def _open_write(self, *, create_missing: bool = True) -> tuple[sqlite3.Connection, bool]:
        if not create_missing and not self.path.is_file():
            raise HistoryError("history.unavailable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = create_missing and not self.path.exists()
        connection = self._connect(create_missing=create_missing)
        try:
            connection.execute("BEGIN IMMEDIATE")
            # A second writer may have initialized the database while we waited.
            if new_file:
                existing = connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='metadata'"
                ).fetchone()
                new_file = existing is None
            self._prepare(connection, new_file=new_file)
            return connection, new_file
        except Exception:
            connection.rollback()
            connection.close()
            raise

    def check(self, identities: tuple[str, ...], *, certificate_id: str | None = None) -> HistoryCheck:
        if (identities and not all(normalize_identity(value) for value in identities)) or (
            not identities and not certificate_id
        ) or (certificate_id is not None and not normalize_identity(certificate_id)):
            return HistoryCheck(HistoryStatus.UNAVAILABLE, (), "history.unavailable")
        if not self.path.is_file():
            return HistoryCheck(HistoryStatus.UNAVAILABLE, (), "history.unavailable")
        try:
            with closing(sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True
            )) as connection:
                key = self._key(connection, create=False)
                matches: list[DuplicateMatch] = []
                queries: list[tuple[str, str]] = []
                if identities and all(normalize_identity(value) for value in identities):
                    queries.append(("identity", _digest(key, "identity", tuple(identities))))
                if certificate_id and normalize_identity(certificate_id):
                    queries.append(("certificate_id", _digest(key, "certificate_id", (certificate_id,))))
                for kind, digest in queries:
                    column = "identity_hash" if kind == "identity" else "certificate_hash"
                    for batch_id, revision, completed_at, folder in connection.execute(
                        f"SELECT batch_id, revision, completed_at, folder FROM records WHERE {column}=?",
                        (digest,),
                    ):
                        matches.append(DuplicateMatch(
                            kind, batch_id, revision,
                            datetime.fromisoformat(completed_at), Path(folder),
                        ))
                status = HistoryStatus.MATCH if matches else HistoryStatus.CLEAN
                return HistoryCheck(status, tuple(matches))
        except (OSError, sqlite3.Error, HistoryError, ValueError, TypeError):
            return HistoryCheck(HistoryStatus.UNAVAILABLE, (), "history.unavailable")

    def record(
        self, batch: PublishedBatch, identities: tuple[str, ...], *, certificate_id: str | None = None
    ) -> None:
        self.record_batch(batch, (HistoryEntry(tuple(identities), certificate_id),))

    @_serialized_write
    def record_batch(self, batch: PublishedBatch, entries: tuple[HistoryEntry, ...]) -> None:
        """Index every published recipient in one durable transaction."""
        if not entries:
            raise HistoryError("history.missing_identity")
        try:
            connection, new_file = self._open_write()
            with closing(connection), connection:
                key = self._key(connection, create=new_file)
                completion = batch.completed_at.astimezone(timezone.utc).isoformat()
                for entry in entries:
                    if (
                        entry.identities and not all(normalize_identity(value) for value in entry.identities)
                    ) or (
                        entry.certificate_id is not None
                        and not normalize_identity(entry.certificate_id)
                    ):
                        raise HistoryError("history.missing_identity")
                    identity_hash = (
                        _digest(key, "identity", tuple(entry.identities))
                        if entry.identities and all(normalize_identity(value) for value in entry.identities)
                        else None
                    )
                    certificate_hash = (
                        _digest(key, "certificate_id", (entry.certificate_id,))
                        if entry.certificate_id and normalize_identity(entry.certificate_id)
                        else None
                    )
                    if identity_hash is None and certificate_hash is None:
                        raise HistoryError("history.missing_identity")
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO records
                        (identity_hash, certificate_hash, batch_id, revision, completed_at, folder)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            identity_hash, certificate_hash, batch.batch_id,
                            batch.revision, completion, str(batch.folder),
                        ),
                    )
                    if cursor.rowcount == 0:
                        old = connection.execute(
                            """SELECT completed_at, folder FROM records
                            WHERE batch_id=? AND revision=?
                            AND identity_hash IS ? AND certificate_hash IS ?""",
                            (batch.batch_id, batch.revision, identity_hash, certificate_hash),
                        ).fetchone()
                        if old != (completion, str(batch.folder)):
                            raise HistoryError("history.conflicting_batch")
        except (OSError, sqlite3.Error) as error:
            raise HistoryError("history.record_failed") from error

    @_serialized_write
    def clear(self) -> None:
        try:
            connection, new_file = self._open_write(create_missing=False)
            with closing(connection), connection:
                self._key(connection, create=new_file)
                connection.execute("DELETE FROM records")
        except (OSError, sqlite3.Error) as error:
            raise HistoryError("history.clear_failed") from error
