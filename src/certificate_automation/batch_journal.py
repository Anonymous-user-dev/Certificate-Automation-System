"""Durable, monotonic record of an official batch publication."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from uuid import uuid4


class JournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class JournalState(str, Enum):
    CREATED = "created"
    RENDERING = "rendering"
    VERIFYING = "verifying"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"


_ORDER = tuple(JournalState)
INTENT_PREFIX = ".certificate-publish-intent-"


def approval_facts_digest(approval_digest: str, intended_counts: dict[str, int], row_ids: tuple[str, ...] | list[str]) -> str:
    """Bind the journal's public output intent to the frozen approval identity."""

    facts = {
        "approval_digest": approval_digest,
        "intended_counts": intended_counts,
        "approved_row_ids": list(row_ids),
    }
    return sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class BatchJournal:
    def __init__(self, path: Path, payload: dict[str, object]) -> None:
        self.path = Path(path)
        self._payload = payload

    @property
    def state(self) -> JournalState:
        return JournalState(self._payload["state"])

    @property
    def batch_id(self) -> str:
        return str(self._payload["batch_id"])

    @classmethod
    def create(cls, staging: Path, request: dict[str, object]) -> "BatchJournal":
        staging = Path(staging)
        if not staging.is_dir():
            raise JournalError("journal.staging_missing")
        path = staging / "batch_journal.json"
        if path.exists():
            raise JournalError("journal.already_exists")
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": 1, **request, "state": JournalState.CREATED.value,
            "created_at": now, "updated_at": now, "last_verified_checkpoint": None,
        }
        if "approved_row_ids" in request and "intended_counts" in request:
            payload["approval_facts_sha256"] = approval_facts_digest(
                str(request["approval_digest"]), dict(request["intended_counts"]), list(request["approved_row_ids"])
            )
        try:
            _atomic_json(path, payload)
        except OSError as error:
            raise JournalError("journal.write_failed") from error
        return cls(path, payload)

    @classmethod
    def open(cls, path: Path) -> "BatchJournal":
        try:
            payload = json.loads(Path(path).read_text("utf-8"))
            if payload["schema_version"] != 1:
                raise ValueError("schema")
            JournalState(payload["state"])
            return cls(Path(path), payload)
        except (OSError, KeyError, ValueError, TypeError) as error:
            raise JournalError("journal.invalid") from error

    def transition(self, state: JournalState, **facts: object) -> None:
        state = JournalState(state)
        if _ORDER.index(state) != _ORDER.index(self.state) + 1:
            raise JournalError("journal.invalid_transition")
        payload = dict(self._payload)
        payload.update(facts)
        payload["state"] = state.value
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if state in (JournalState.VERIFYING, JournalState.READY_TO_PUBLISH):
            payload["last_verified_checkpoint"] = state.value
        try:
            _atomic_json(self.path, payload)
        except OSError as error:
            raise JournalError("journal.write_failed") from error
        self._payload = payload

    @staticmethod
    def mark_stranded(folder: Path, batch_id: str) -> Path:
        """Durably flag a revision-looking folder whose rollback was blocked."""

        folder = Path(folder)
        if not folder.is_dir() or folder.is_symlink() or "-revision-" not in folder.name:
            raise JournalError("journal.invalid_recovery_target")
        marker = folder / ".certificate-publication-failed.json"
        try:
            _atomic_json(marker, {
                "schema_version": 1,
                "batch_id": batch_id,
                "status": "publication_ambiguous",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except OSError as error:
            raise JournalError("journal.recovery_marker_failed") from error
        return marker

    @staticmethod
    def create_publish_intent(
        destination: Path, batch_id: str, final_name: str,
        approval_digest: str, revision: int,
    ) -> Path:
        """Persist the exact final target before the irreversible rename window."""

        destination = Path(destination)
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id)
            or Path(final_name).name != final_name
            or "/" in final_name or "\\" in final_name
            or not final_name.endswith(f"-revision-{revision}")
        ):
            raise JournalError("journal.invalid_publication_intent")
        path = destination / f"{INTENT_PREFIX}{batch_id}.json"
        if path.exists():
            raise JournalError("journal.publication_intent_exists")
        try:
            _atomic_json(path, {
                "schema_version": 1,
                "status": "pending",
                "batch_id": batch_id,
                "final_name": final_name,
                "approval_digest": approval_digest,
                "revision": revision,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except OSError as error:
            raise JournalError("journal.publication_intent_failed") from error
        return path

    @staticmethod
    def clear_publish_intent(path: Path) -> None:
        path = Path(path)
        if not path.name.startswith(INTENT_PREFIX) or path.suffix != ".json" or path.is_symlink():
            raise JournalError("journal.invalid_publication_intent")
        try:
            path.unlink(missing_ok=True)
            _sync_directory(path.parent)
        except OSError as error:
            raise JournalError("journal.publication_intent_clear_failed") from error
