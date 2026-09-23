"""Privacy-minimal recent project metadata, separate from project contents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from certificate_automation.project import ProjectCorruptError, ProjectState, ProjectStore


_MAX_ENTRIES = 12


class ProjectHealth(str, Enum):
    READY = "ready"
    MISSING = "missing"
    UNREADABLE = "unreadable"
    NEWER_SCHEMA = "newer_schema"


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    path: Path
    last_saved_at: datetime | None
    recipient_count: int | None
    active_step: str | None
    template_name: str | None
    health: ProjectHealth


class ProjectCatalog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def remember(self, path: Path, state: ProjectState) -> None:
        path = Path(path)
        saved_at = None
        if path.is_file():
            try:
                with sqlite3.connect(path) as connection:
                    row = connection.execute(
                        "SELECT saved_at FROM revisions WHERE revision=?", (state.revision,)
                    ).fetchone()
                saved_at = row[0] if row else None
            except sqlite3.Error:
                pass
        entry = {
            "path": str(path),
            "last_saved_at": saved_at,
            "recipient_count": len(state.dataset.rows),
            "active_step": state.active_step,
            "template_name": state.template_path.name if state.template_path else None,
            "schema_version": getattr(state, "schema_version", 1),
        }
        self._remember_entry(entry)

    def remember_path(self, path: Path) -> None:
        path = Path(path)
        try:
            state = ProjectStore.open(path).load()
        except ProjectCorruptError:
            state = None
        if state is not None:
            self.remember(path, state)
            return
        self._remember_entry({
            "path": str(path),
            "last_saved_at": None,
            "recipient_count": None,
            "active_step": None,
            "template_name": None,
            "schema_version": None,
        })

    def list(self) -> tuple[ProjectSummary, ...]:
        summaries = []
        for entry in self._entries():
            path = Path(entry["path"])
            if not path.is_file():
                health = ProjectHealth.MISSING
            else:
                try:
                    store = ProjectStore.open(path)
                    if store.issue_code == "project.newer_schema":
                        health = ProjectHealth.NEWER_SCHEMA
                    else:
                        store.load()
                        health = ProjectHealth.READY
                except (ProjectCorruptError, OSError, ValueError):
                    health = ProjectHealth.UNREADABLE
            saved = entry.get("last_saved_at")
            summaries.append(ProjectSummary(
                path=path,
                last_saved_at=datetime.fromisoformat(saved) if saved else None,
                recipient_count=entry.get("recipient_count"),
                active_step=entry.get("active_step"),
                template_name=entry.get("template_name"),
                health=health,
            ))
        return tuple(summaries)

    def forget(self, path: Path) -> None:
        target = str(Path(path))
        self._write([entry for entry in self._entries() if entry["path"] != target])

    def _remember_entry(self, entry: dict[str, object]) -> None:
        entries = [existing for existing in self._entries() if existing["path"] != entry["path"]]
        self._write([entry, *entries][:_MAX_ENTRIES])

    def _entries(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        return json.loads(self.path.read_text("utf-8"))

    def _write(self, entries: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(entries, output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
