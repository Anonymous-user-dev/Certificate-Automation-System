"""Transactional, local-only draft project persistence."""

from __future__ import annotations

from contextlib import closing
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
from types import MappingProxyType

from PySide6.QtCore import QObject, QTimer, Signal

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset


SCHEMA_VERSION = 1
BACKUP_COUNT = 3


class ProjectError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProjectSaveError(ProjectError):
    """A draft save did not commit."""


class ProjectCorruptError(ProjectError):
    """No hash-valid project revision can be loaded."""


@dataclass(frozen=True, slots=True)
class ProjectState:
    """Everything required to resume a reviewed operator workflow."""

    revision: int
    dataset: TabularDataset
    mapping_plan: Mapping[str, object] | None = None
    template_path: Path | None = None
    template_sha256: str | None = None
    template_inspection: Mapping[str, object] | None = None
    output_options: Mapping[str, object] | None = None
    locale: str = "en"
    acknowledgements: tuple[str, ...] = ()
    active_step: str = "data"
    preview_revision: int | None = None

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ProjectError("project.invalid_revision")
        object.__setattr__(
            self,
            "mapping_plan",
            _frozen_json_mapping(self.mapping_plan),
        )
        object.__setattr__(
            self,
            "template_inspection",
            _frozen_json_mapping(self.template_inspection),
        )
        object.__setattr__(
            self,
            "output_options",
            _frozen_json_mapping(self.output_options),
        )
        object.__setattr__(
            self,
            "template_path",
            Path(self.template_path) if self.template_path else None,
        )
        object.__setattr__(self, "acknowledgements", tuple(self.acknowledgements))

    def reconcile_template(self) -> "ProjectState":
        """Invalidate every downstream decision when referenced bytes changed."""

        current_hash = (
            _sha256_file(self.template_path)
            if self.template_path and self.template_path.is_file()
            else None
        )
        if current_hash == self.template_sha256:
            return self
        return replace(
            self,
            revision=self.revision + 1,
            template_sha256=current_hash,
            template_inspection=None,
            mapping_plan=None,
            acknowledgements=(),
            active_step="template",
            preview_revision=None,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "dataset": self.dataset.to_json(),
            "mapping_plan": _plain_json(self.mapping_plan),
            "template_path": str(self.template_path) if self.template_path else None,
            "template_sha256": self.template_sha256,
            "template_inspection": _plain_json(self.template_inspection),
            "output_options": _plain_json(self.output_options),
            "locale": self.locale,
            "acknowledgements": list(self.acknowledgements),
            "active_step": self.active_step,
            "preview_revision": self.preview_revision,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ProjectState":
        return cls(
            revision=int(payload["revision"]),
            dataset=_dataset_from_json(payload["dataset"]),
            mapping_plan=payload.get("mapping_plan"),
            template_path=payload.get("template_path"),
            template_sha256=payload.get("template_sha256"),
            template_inspection=payload.get("template_inspection"),
            output_options=payload.get("output_options"),
            locale=str(payload.get("locale", "en")),
            acknowledgements=tuple(payload.get("acknowledgements", ())),
            active_step=str(payload.get("active_step", "data")),
            preview_revision=payload.get("preview_revision"),
        )


class ProjectStore:
    """SQLite revision store with hash verification and rotating backups."""

    def __init__(
        self,
        path: Path,
        *,
        read_only: bool = False,
        issue_code: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.read_only = read_only
        self.issue_code = issue_code

    @classmethod
    def create(cls, path: Path) -> "ProjectStore":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size:
            raise ProjectSaveError("project.already_exists")
        store = cls(path)
        try:
            with closing(store._connect()) as connection, connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute(
                    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    """
                    CREATE TABLE revisions (
                        revision INTEGER PRIMARY KEY,
                        saved_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
        except (OSError, sqlite3.Error) as error:
            raise ProjectSaveError("project.create_failed") from error
        return store

    @classmethod
    def open(cls, path: Path) -> "ProjectStore":
        path = Path(path)
        if not path.is_file():
            raise ProjectCorruptError("project.missing")
        try:
            with closing(sqlite3.connect(path)) as connection, connection:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
        except sqlite3.Error as error:
            raise ProjectCorruptError("project.unreadable") from error
        if row is None:
            raise ProjectCorruptError("project.schema_missing")
        version = int(row[0])
        if version > SCHEMA_VERSION:
            return cls(path, read_only=True, issue_code="project.newer_schema")
        if version < SCHEMA_VERSION:
            return cls(path, read_only=True, issue_code="project.older_schema")
        return cls(path)

    @classmethod
    def open_or_create(cls, path: Path) -> "ProjectStore":
        return cls.open(path) if Path(path).exists() else cls.create(path)

    def save(self, state: ProjectState) -> None:
        if self.read_only:
            raise ProjectSaveError(self.issue_code or "project.read_only")
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._commit(connection, state)
                connection.commit()
        except Exception as error:
            if isinstance(error, ProjectSaveError):
                raise
            raise ProjectSaveError("project.save_failed") from error
        self.backup()

    def _commit(self, connection: sqlite3.Connection, state: ProjectState) -> None:
        payload_text = json.dumps(
            state.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = sha256(payload_text.encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT OR REPLACE INTO revisions
                (revision, saved_at, payload_json, payload_sha256)
            VALUES (?, ?, ?, ?)
            """,
            (
                state.revision,
                datetime.now(timezone.utc).isoformat(),
                payload_text,
                digest,
            ),
        )
        connection.execute(
            """
            DELETE FROM revisions
            WHERE revision NOT IN (
                SELECT revision FROM revisions ORDER BY revision DESC LIMIT 3
            )
            """
        )

    def load(self) -> ProjectState:
        try:
            with closing(self._connect()) as connection, connection:
                rows = connection.execute(
                    "SELECT payload_json, payload_sha256 FROM revisions ORDER BY revision DESC"
                ).fetchall()
        except sqlite3.Error as error:
            raise ProjectCorruptError("project.unreadable") from error
        for payload_text, expected_hash in rows:
            actual_hash = sha256(payload_text.encode("utf-8")).hexdigest()
            if actual_hash != expected_hash:
                continue
            try:
                payload = json.loads(payload_text)
                return ProjectState.from_payload(payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        raise ProjectCorruptError("project.no_valid_revision")

    def backup(self) -> Path:
        if not self.path.is_file():
            raise ProjectSaveError("project.missing")
        paths = self.backup_paths(include_missing=True)
        try:
            paths[-1].unlink(missing_ok=True)
            for source, destination in zip(
                reversed(paths[:-1]),
                reversed(paths[1:]),
                strict=True,
            ):
                if source.exists():
                    os.replace(source, destination)
            with closing(sqlite3.connect(self.path)) as source_connection, source_connection:
                with (
                    closing(sqlite3.connect(paths[0])) as destination_connection,
                    destination_connection,
                ):
                    source_connection.backup(destination_connection)
        except (OSError, sqlite3.Error) as error:
            raise ProjectSaveError("project.backup_failed") from error
        return paths[0]

    def backup_paths(self, *, include_missing: bool = False) -> tuple[Path, ...]:
        paths = tuple(Path(f"{self.path}.bak{index}") for index in range(1, BACKUP_COUNT + 1))
        return paths if include_missing else tuple(path for path in paths if path.is_file())

    @classmethod
    def recover_latest(cls, path: Path) -> ProjectState:
        path = Path(path)
        candidates = (path,) + tuple(
            Path(f"{path}.bak{index}") for index in range(1, BACKUP_COUNT + 1)
        )
        recovered: list[ProjectState] = []
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                recovered.append(cls.open(candidate).load())
            except ProjectError:
                continue
        if not recovered:
            raise ProjectCorruptError("project.no_valid_backup")
        return max(recovered, key=lambda state: state.revision)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


class ProjectCoordinator(QObject):
    """Debounce UI changes and retain failed saves for explicit retry."""

    save_failed = Signal(object)
    saved = Signal(int)

    def __init__(
        self,
        store: ProjectStore,
        parent=None,
        *,
        debounce_ms: int = 750,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._pending: ProjectState | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self.flush)

    @property
    def has_pending(self) -> bool:
        return self._pending is not None

    def mark_dirty(self, state: ProjectState) -> None:
        self._pending = state
        self._timer.start()

    def flush(self) -> bool:
        if self._pending is None:
            return True
        state = self._pending
        try:
            self._store.save(state)
        except ProjectSaveError as error:
            self.save_failed.emit(error)
            return False
        self._pending = None
        self.saved.emit(state.revision)
        return True


def _dataset_from_json(value: object) -> TabularDataset:
    if not isinstance(value, Mapping):
        raise ProjectCorruptError("project.invalid_dataset")
    source_value = value["source"]
    source = SourceSnapshot(
        kind=str(source_value["kind"]),
        label=str(source_value["label"]),
        path=source_value.get("path"),
        sha256=str(source_value["sha256"]),
        imported_at=datetime.fromisoformat(str(source_value["imported_at"])),
        options=source_value.get("options", {}),
    )
    columns = tuple(
        Column(str(item["column_id"]), str(item["label"]))
        for item in value["columns"]
    )
    rows = tuple(
        DataRow(
            str(item["row_id"]),
            item.get("source_row"),
            item["values"],
            item.get("display_values"),
        )
        for item in value["rows"]
    )
    return TabularDataset(
        columns,
        rows,
        source,
        revision=int(value.get("revision", 0)),
        order=tuple(value.get("order", ())),
    )


def _frozen_json_mapping(value: Mapping[str, object] | None):
    if value is None:
        return None
    return MappingProxyType(_plain_json(value))


def _plain_json(value: object) -> object:
    """Return a detached JSON-compatible value, including mapping proxies."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    serializer = getattr(value, "to_json", None)
    if callable(serializer):
        return _plain_json(serializer())
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    raise TypeError(f"Unsupported project value: {type(value).__name__}")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
