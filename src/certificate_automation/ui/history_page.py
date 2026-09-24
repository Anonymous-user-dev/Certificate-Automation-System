"""Local history of published and recoverable certificate batches."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import stat

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from certificate_automation.history import HistoryError, HistoryIndex
from certificate_automation.i18n import CatalogSet
from certificate_automation.integrity import IntegrityService
from certificate_automation.recovery import IncompleteBatch, RecoveryScanError, RecoveryService


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    path: Path
    batch_id: str
    revision: int | None
    status: str
    incomplete: IncompleteBatch | None = None


class HistoryPage(QWidget):
    open_path_requested = Signal(Path)
    correction_requested = Signal(Path)
    back_requested = Signal()

    _ACTIONS = (
        ("open_folder", "history.open_folder"),
        ("open_combined", "history.open_combined"),
        ("open_audit", "history.open_audit"),
        ("verify", "history.verify"),
        ("correct", "history.correct"),
        ("remove", "history.remove_incomplete"),
    )

    def __init__(
        self, catalogs: CatalogSet, *, history_index: HistoryIndex | None = None,
        recovery: RecoveryService | None = None, integrity: IntegrityService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.catalogs = catalogs
        self.history_index = history_index
        self.recovery = recovery or RecoveryService()
        self.integrity = integrity or IntegrityService()
        self.records: tuple[HistoryRecord, ...] = ()
        self._destination: Path | None = None
        self._published_paths: tuple[Path, ...] = ()
        self._scan_unavailable = False
        self._rows: list[tuple[QLabel, dict[str, QPushButton]]] = []
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.back_button = QPushButton()
        self.back_button.clicked.connect(self.back_requested)
        self.row_container = QWidget()
        self.row_layout = QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.row_container)
        layout = QVBoxLayout(self)
        for widget in (self.title, self.explanation, self.status_label, self.back_button, scroll):
            layout.addWidget(widget)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def load(self, destination: Path, *, published_paths: tuple[Path, ...] = ()) -> None:
        self._destination = Path(destination)
        self._published_paths = tuple(Path(path) for path in published_paths)
        self._scan_unavailable = False
        unavailable_paths: set[Path] = set()
        root_unavailable = False
        candidates: dict[Path, tuple[str, int | None]] = {}
        if self.history_index is not None:
            try:
                for batch in self.history_index.list_batches():
                    candidates[batch.folder] = (batch.batch_id, batch.revision)
            except HistoryError:
                self.status_label.setText(self.catalogs.text("history.unavailable"))
        for path in self._published_paths:
            candidates.setdefault(path, (path.name, None))
        try:
            root_stat = self._destination.stat()
            if not stat.S_ISDIR(root_stat.st_mode):
                children = ()
            else:
                with os.scandir(self._destination) as scan:
                    children = tuple(self._destination / entry.name for entry in scan)
        except OSError as error:
            children = ()
            if error.errno not in (errno.ENOENT, errno.ENOTDIR):
                root_unavailable = True
        for path in children:
            match = re.search(r"-revision-(\d+)$", path.name, re.IGNORECASE)
            if match is None:
                continue
            try:
                folder_stat = path.stat(follow_symlinks=False)
                if stat.S_ISLNK(folder_stat.st_mode) or not stat.S_ISDIR(folder_stat.st_mode):
                    continue
                visible = True
                for name in ("manifest.json", "batch_journal.json"):
                    try:
                        child_stat = (path / name).stat(follow_symlinks=False)
                    except OSError as error:
                        if error.errno in (errno.ENOENT, errno.ENOTDIR):
                            visible = False
                            break
                        raise
                    if not stat.S_ISREG(child_stat.st_mode):
                        visible = False
                        break
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ENOTDIR):
                    unavailable_paths.add(path)
                    candidates.setdefault(path, (path.name, int(match.group(1))))
                continue
            if visible:
                candidates.setdefault(path, (path.name, int(match.group(1))))
        try:
            incomplete_records = self.recovery.find_incomplete(self._destination)
        except RecoveryScanError as error:
            incomplete_records = error.records
            root_unavailable |= error.root_unavailable
            unavailable_paths.update(error.unavailable_paths)
        self._scan_unavailable = root_unavailable or bool(unavailable_paths)
        if self._scan_unavailable:
            self.status_label.setText(self.catalogs.text("history.scan_unavailable"))
        records = []
        for path, (batch_id, revision) in candidates.items():
            if path in unavailable_paths or root_unavailable and path.parent == self._destination:
                status = "unavailable"
            else:
                try:
                    folder_stat = path.stat(follow_symlinks=False)
                    if not stat.S_ISDIR(folder_stat.st_mode) or stat.S_ISLNK(folder_stat.st_mode):
                        status = "missing"
                    else:
                        status = "completed" if self.integrity.verify_revision(path).valid else "damaged"
                except OSError as error:
                    if error.errno in (errno.ENOENT, errno.ENOTDIR):
                        status = "missing"
                    else:
                        status = "unavailable"
                        self._scan_unavailable = True
                        self.status_label.setText(self.catalogs.text("history.scan_unavailable"))
            records.append(HistoryRecord(path, batch_id, revision, status))
        for incomplete in incomplete_records:
            records = [record for record in records if record.path != incomplete.path]
            status = "unavailable" if root_unavailable or incomplete.path in unavailable_paths else "incomplete"
            records.append(HistoryRecord(
                incomplete.path, incomplete.batch_id, None, status, incomplete,
            ))
        self.records = tuple(sorted(records, key=lambda record: (record.path.name.casefold(), record.status)))
        self._render_rows()

    def action_button(self, index: int, action: str) -> QPushButton:
        return self._rows[index][1][action]

    def _render_rows(self) -> None:
        while self.row_layout.count():
            item = self.row_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._rows.clear()
        for record in self.records:
            card = QFrame()
            card.setProperty("role", "surface")
            card_layout = QVBoxLayout(card)
            title = QLabel()
            title.setWordWrap(True)
            card_layout.addWidget(title)
            buttons: dict[str, QPushButton] = {}
            button_layout = QHBoxLayout()
            for action, _key in self._ACTIONS:
                button = QPushButton()
                button.clicked.connect(lambda _checked=False, selected=record, name=action: self._act(selected, name))
                buttons[action] = button
                button_layout.addWidget(button)
            card_layout.addLayout(button_layout)
            self.row_layout.addWidget(card)
            self._rows.append((title, buttons))
            card.show()
        self.row_layout.addStretch(1)
        self.retranslate()

    def _act(self, record: HistoryRecord, action: str) -> None:
        if action == "open_folder" and record.status != "unavailable":
            try:
                if record.path.is_dir():
                    self.open_path_requested.emit(record.path)
            except OSError:
                self.status_label.setText(self.catalogs.text("history.scan_unavailable"))
        elif action == "verify":
            report = self.integrity.verify_revision(record.path)
            self.status_label.setText(
                self.catalogs.text("history.integrity_valid") if report.valid
                else self.catalogs.text("history.integrity_invalid", issues=", ".join(report.issues))
            )
        elif action == "open_combined" and record.status == "completed":
            path = self.integrity.verified_artifact(record.path, "combined")
            if path is not None:
                self.open_path_requested.emit(path)
        elif action == "open_audit" and record.status == "completed":
            path = self.integrity.verified_artifact(record.path, "audit")
            if path is not None:
                self.open_path_requested.emit(path)
        elif action == "correct" and record.status == "completed":
            self.correction_requested.emit(record.path)
        elif action == "remove" and record.status == "incomplete" and record.incomplete is not None and not record.incomplete.publication_interrupted:
            answer = QMessageBox.question(
                self, self.catalogs.text("history.remove_title"),
                self.catalogs.text("history.remove_confirm", path=str(record.path)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is QMessageBox.StandardButton.Yes:
                try:
                    self.recovery.remove(record.incomplete)
                except (OSError, ValueError):
                    self.status_label.setText(self.catalogs.text("history.remove_failed"))
                else:
                    self.load(self._destination, published_paths=self._published_paths)

    def retranslate(self) -> None:
        self.title.setText(self.catalogs.text("history.center_title"))
        self.explanation.setText(self.catalogs.text("history.center_explanation"))
        self.back_button.setText(self.catalogs.text("action.back"))
        self.back_button.setAccessibleName(self.back_button.text())
        if self._scan_unavailable:
            self.status_label.setText(self.catalogs.text("history.scan_unavailable"))
        for record, (label, buttons) in zip(self.records, self._rows, strict=True):
            label.setText(self.catalogs.text(
                "history.record_label", name=record.path.name,
                status=self.catalogs.text(f"history.status.{record.status}"),
            ))
            for action, key in self._ACTIONS:
                control = buttons[action]
                control.setText(self.catalogs.text(key))
                control.setAccessibleName(f"{control.text()}: {record.path.name}")
            try:
                record_stat = record.path.stat(follow_symlinks=False)
                available = (record.status != "unavailable" and stat.S_ISDIR(record_stat.st_mode)
                             and not stat.S_ISLNK(record_stat.st_mode))
            except OSError:
                available = False
            buttons["open_folder"].setEnabled(available)
            buttons["verify"].setEnabled(available and record.incomplete is None)
            buttons["open_audit"].setEnabled(record.status == "completed" and
                                                self.integrity.verified_artifact(record.path, "audit") is not None)
            buttons["open_combined"].setEnabled(record.status == "completed" and
                                                   self.integrity.verified_artifact(record.path, "combined") is not None)
            buttons["correct"].setEnabled(record.status == "completed")
            buttons["remove"].setEnabled(
                record.status == "incomplete" and record.incomplete is not None and not record.incomplete.publication_interrupted
            )
