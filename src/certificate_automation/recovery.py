"""Discover and safely remove incomplete diagnostic batch directories."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil

from certificate_automation.batch_journal import INTENT_PREFIX


INCOMPLETE_PREFIX = ".certificate-incomplete-"


@dataclass(frozen=True, slots=True)
class IncompleteBatch:
    batch_id: str
    path: Path
    diagnostic_path: Path
    publication_interrupted: bool = False


@dataclass(frozen=True, slots=True)
class DraftProjectBackup:
    project_path: Path
    backup_path: Path
    slot: int


class RecoveryService:
    def find_incomplete(self, destination: Path) -> tuple[IncompleteBatch, ...]:
        destination = Path(destination)
        if not destination.is_dir():
            return ()
        records = []
        pending_intents: dict[str, tuple[str, Path, str, int]] = {}
        for intent in destination.glob(f"{INTENT_PREFIX}*.json"):
            if not intent.is_file() or intent.is_symlink():
                continue
            try:
                payload = json.loads(intent.read_text("utf-8"))
                batch_id = payload["batch_id"]
                final_name = payload["final_name"]
                revision = payload["revision"]
                digest = payload["approval_digest"]
                if (
                    payload.get("schema_version") != 1 or payload.get("status") != "pending"
                    or not isinstance(batch_id, str)
                    or intent.name != f"{INTENT_PREFIX}{batch_id}.json"
                    or not isinstance(final_name, str)
                    or Path(final_name).name != final_name
                    or "/" in final_name or "\\" in final_name
                    or not isinstance(revision, int) or revision < 1
                    or not final_name.endswith(f"-revision-{revision}")
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                ):
                    continue
                pending_intents[final_name] = (batch_id, intent, digest, revision)
            except (OSError, KeyError, ValueError, TypeError):
                continue
        for path in sorted(destination.iterdir(), key=lambda item: item.name.casefold()):
            if (
                path.is_dir()
                and not path.is_symlink()
                and path.name.startswith(INCOMPLETE_PREFIX)
            ):
                records.append(
                    IncompleteBatch(
                        path.name[len(INCOMPLETE_PREFIX) :],
                        path,
                        path / "diagnostic.json",
                    )
                )
            elif path.is_dir() and not path.is_symlink() and "-revision-" in path.name:
                journal = path / "batch_journal.json"
                marker = path / ".certificate-publication-failed.json"
                if not journal.is_file() or journal.is_symlink():
                    continue
                try:
                    payload = json.loads(journal.read_text("utf-8"))
                    if payload.get("schema_version") != 1:
                        continue
                    batch_id = str(payload["batch_id"])
                except (OSError, KeyError, ValueError, TypeError):
                    continue
                intent = pending_intents.get(path.name)
                if intent is not None and (
                    intent[0] != batch_id
                    or intent[2] != payload.get("approval_digest")
                    or intent[3] != payload.get("revision")
                ):
                    intent = None
                interrupted = payload.get("state") == "ready_to_publish"
                if not interrupted and payload.get("state") == "published":
                    from certificate_automation.integrity import IntegrityService
                    interrupted = intent is not None or marker.is_file() or not IntegrityService().verify_revision(path).valid
                if interrupted:
                    diagnostic = marker if marker.is_file() else intent[1] if intent is not None else journal
                    records.append(IncompleteBatch(batch_id, path, diagnostic, True))
        return tuple(records)

    def find_project_backups(self, directory: Path) -> tuple[DraftProjectBackup, ...]:
        """List draft backups without mixing them with output recovery records."""

        directory = Path(directory)
        if not directory.is_dir():
            return ()
        records: list[DraftProjectBackup] = []
        for slot in range(1, 4):
            suffix = f".certproject.bak{slot}"
            for backup in sorted(directory.glob(f"*{suffix}"), key=lambda item: item.name.casefold()):
                if backup.is_file() and not backup.is_symlink():
                    project = Path(str(backup)[: -len(f".bak{slot}")])
                    records.append(DraftProjectBackup(project, backup, slot))
        return tuple(
            sorted(records, key=lambda record: (record.project_path.name.casefold(), record.slot))
        )

    def remove(self, record: IncompleteBatch) -> None:
        path = Path(record.path)
        if (
            not path.name.startswith(INCOMPLETE_PREFIX)
            or path.name == INCOMPLETE_PREFIX
            or path.is_symlink()
            or not path.is_dir()
        ):
            raise ValueError("Only an exact incomplete batch directory can be removed.")
        diagnostic = Path(record.diagnostic_path)
        if diagnostic.parent.resolve() != path.resolve():
            raise ValueError("The diagnostic file is outside the incomplete batch directory.")
        shutil.rmtree(path)
