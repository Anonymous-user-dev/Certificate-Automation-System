"""Offline support package controls with visible sensitive-file consent."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QLabel, QListWidget, QMessageBox,
    QPushButton, QVBoxLayout,
)

from certificate_automation.diagnostics import DiagnosticBundleService, DiagnosticContext, DiagnosticError
from certificate_automation.i18n import CatalogSet


class SupportDialog(QDialog):
    def __init__(
        self, catalogs: CatalogSet, service: DiagnosticBundleService,
        context: DiagnosticContext, parent=None,
    ) -> None:
        super().__init__(parent)
        self.catalogs = catalogs
        self.service = service
        self.context = context
        self._sensitive_files: list[Path] = []
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.attachments_label = QLabel()
        self.attachments_list = QListWidget()
        self.include_sensitive = QCheckBox()
        self.add_button = QPushButton()
        self.create_button = QPushButton()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        for widget in (
            self.explanation, self.attachments_label, self.attachments_list,
            self.include_sensitive, self.add_button, self.create_button, self.status_label,
        ):
            layout.addWidget(widget)
        self.include_sensitive.setChecked(False)
        self.add_button.clicked.connect(self._choose_sensitive_files)
        self.create_button.clicked.connect(self._choose_destination)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def add_sensitive_file(self, path: Path) -> None:
        path = Path(path)
        if path not in self._sensitive_files:
            self._sensitive_files.append(path)
            self.attachments_list.addItem(str(path))

    def _choose_sensitive_files(self) -> None:
        files, _filter = QFileDialog.getOpenFileNames(
            self, self.catalogs.text("diagnostic.choose_sensitive"), "",
            self.catalogs.text("diagnostic.file_filter"),
        )
        for path in files:
            self.add_sensitive_file(Path(path))

    def _choose_destination(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, self.catalogs.text("diagnostic.save_title"), "support.zip",
            self.catalogs.text("diagnostic.zip_filter"),
        )
        if path:
            self.create_bundle(Path(path))

    def create_bundle(self, destination: Path) -> Path | None:
        attachments: tuple[Path, ...] = ()
        if self.include_sensitive.isChecked() and self._sensitive_files:
            names = "\n".join(str(path) for path in self._sensitive_files)
            message = self.catalogs.text("diagnostic.confirm_sensitive", files=names)
            answer = QMessageBox.question(
                self, self.catalogs.text("diagnostic.confirm_title"), message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                self.status_label.setText(self.catalogs.text("diagnostic.cancelled"))
                return None
            attachments = tuple(self._sensitive_files)
        try:
            path = self.service.create(self.context, Path(destination), sensitive_files=attachments)
        except DiagnosticError as error:
            self.status_label.setText(self.catalogs.text(error.code))
            return None
        self.status_label.setText(self.catalogs.text("diagnostic.saved", path=str(path)))
        return path

    def retranslate(self) -> None:
        self.setWindowTitle(self.catalogs.text("diagnostic.title"))
        self.explanation.setText(self.catalogs.text("diagnostic.explanation"))
        self.attachments_label.setText(self.catalogs.text("diagnostic.attachments"))
        for control, key in (
            (self.include_sensitive, "diagnostic.include_sensitive"),
            (self.add_button, "diagnostic.add_file"),
            (self.create_button, "diagnostic.create"),
        ):
            control.setText(self.catalogs.text(key))
            control.setAccessibleName(control.text())
        self.attachments_list.setAccessibleName(self.attachments_label.text())
