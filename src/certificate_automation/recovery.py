"""Discover and safely remove incomplete diagnostic batch directories."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import shutil

from certificate_automation.batch_journal import read_publish_intents


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


class RecoveryScanError(RuntimeError):
    """A scan is incomplete; carry safe discoveries without claiming completeness."""

    def __init__(
        self, records: tuple[IncompleteBatch, ...] = (),
        unavailable_paths: tuple[Path, ...] = (), *, root_unavailable: bool = False,
    ) -> None:
        super().__init__("recovery.scan_unavailable")
        self.code = "recovery.scan_unavailable"
        self.records = records
        self.unavailable_paths = unavailable_paths
        self.root_unavailable = root_unavailable


class RecoveryService:
    def find_incomplete(self, destination: Path) -> tuple[IncompleteBatch, ...]:
        destination = Path(destination)
        try:
            root_stat = destination.stat()
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise RecoveryScanError(unavailable_paths=(destination,), root_unavailable=True) from error
        if not stat.S_ISDIR(root_stat.st_mode):
            return ()
        try:
            with os.scandir(destination) as scan:
                children = tuple(sorted((destination / entry.name for entry in scan), key=lambda item: item.name.casefold()))
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise RecoveryScanError(unavailable_paths=(destination,), root_unavailable=True) from error
        records: list[IncompleteBatch] = []
        unavailable: list[Path] = []
        root_unavailable = False
        try:
            intents = read_publish_intents(destination)
        except OSError:
            intents = ()
            root_unavailable = True
            unavailable.append(destination)
        consumed_intents: set[Path] = set()
        for path in children:
            try:
                entry_stat = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                unavailable.append(path)
                continue
            is_symlink = stat.S_ISLNK(entry_stat.st_mode)
            is_directory = stat.S_ISDIR(entry_stat.st_mode)
            if is_directory and not is_symlink and path.name.startswith(INCOMPLETE_PREFIX):
                records.append(
                    IncompleteBatch(
                        path.name[len(INCOMPLETE_PREFIX) :],
                        path,
                        path / "diagnostic.json",
                    )
                )
                continue
            if not is_directory or is_symlink or "-revision-" not in path.name:
                continue
            journal = path / "batch_journal.json"
            marker = path / ".certificate-publication-failed.json"
            try:
                journal_stat = journal.stat(follow_symlinks=False)
                if not stat.S_ISREG(journal_stat.st_mode):
                    continue
                payload = json.loads(journal.read_text("utf-8"))
                if (
                    payload.get("schema_version") != 1
                    or not isinstance(payload.get("batch_id"), str)
                ):
                    continue
                batch_id = payload["batch_id"]
            except FileNotFoundError:
                continue
            except OSError:
                unavailable.append(path)
                continue
            except (KeyError, ValueError, TypeError):
                continue
            intent = next(
                (
                    candidate
                    for candidate in intents
                    if type(payload.get("revision")) is int
                    and candidate.final_name == path.name
                    and candidate.batch_id == batch_id
                    and candidate.approval_digest == payload.get("approval_digest")
                    and candidate.revision == payload.get("revision")
                ),
                None,
            )
            interrupted = payload.get("state") == "ready_to_publish"
            if payload.get("state") == "published":
                from certificate_automation.integrity import IntegrityService
                try:
                    try:
                        marker_stat = marker.stat(follow_symlinks=False)
                        marker_exists = stat.S_ISREG(marker_stat.st_mode)
                    except FileNotFoundError:
                        marker_exists = False
                    interrupted = (
                        intent is not None
                        or marker_exists
                        or not IntegrityService().verify_revision(path).valid
                    )
                except OSError:
                    unavailable.append(path)
                    continue
            if interrupted:
                if intent is not None:
                    consumed_intents.add(intent.path)
                try:
                    try:
                        marker_stat = marker.stat(follow_symlinks=False)
                        has_marker = stat.S_ISREG(marker_stat.st_mode)
                    except FileNotFoundError:
                        has_marker = False
                except OSError:
                    unavailable.append(path)
                    continue
                diagnostic = marker if has_marker else intent.path if intent is not None else journal
                records.append(IncompleteBatch(batch_id, path, diagnostic, True))

        for intent in intents:
            if intent.path in consumed_intents:
                continue
            records.append(
                IncompleteBatch(
                    intent.batch_id,
                    destination / intent.final_name,
                    intent.path,
                    True,
                )
            )
        if unavailable:
            raise RecoveryScanError(
                tuple(records), tuple(dict.fromkeys(unavailable)), root_unavailable=root_unavailable,
            )
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
