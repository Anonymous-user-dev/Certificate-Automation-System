"""Generation progress and safely published result actions."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from certificate_automation.i18n import CatalogSet


class ResultsPage(QWidget):
    generate_requested = Signal()
    cancel_requested = Signal()
    open_output_requested = Signal()
    open_combined_requested = Signal()
    open_summary_requested = Signal()
    open_manifest_requested = Signal()

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self.state = "ready"
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.generate_button = QPushButton()
        self.generate_button.setProperty("role", "primary")
        self.cancel_button = QPushButton()
        self.open_output_button = QPushButton()
        self.open_combined_button = QPushButton()
        self.open_summary_button = QPushButton()
        self.open_manifest_button = QPushButton()
        layout = QVBoxLayout(self)
        for widget in (
            self.title,
            self.status_label,
            self.progress,
            self.generate_button,
            self.cancel_button,
            self.open_output_button,
            self.open_combined_button,
            self.open_summary_button,
            self.open_manifest_button,
        ):
            layout.addWidget(widget)
        self.generate_button.clicked.connect(self.generate_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.open_output_button.clicked.connect(self.open_output_requested)
        self.open_combined_button.clicked.connect(self.open_combined_requested)
        self.open_summary_button.clicked.connect(self.open_summary_requested)
        self.open_manifest_button.clicked.connect(self.open_manifest_requested)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.set_ready()
        self.retranslate()

    def set_ready(self) -> None:
        self.state = "ready"
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._enable_results(False)

    def set_running(self) -> None:
        self.state = "running"
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._enable_results(False)
        self.status_label.setText(self._catalogs.text("generation.running"))

    def update_progress(self, event) -> None:
        self.progress.setMaximum(max(int(event.total), 1))
        self.progress.setValue(int(event.current))
        self.status_label.setText(str(event.message))

    def set_published(self, result) -> None:
        self.state = "published"
        self.result = result
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        output_dir = result.output_dir
        self.open_output_button.setEnabled(bool(output_dir and output_dir.is_dir()))
        self.open_combined_button.setEnabled(
            bool(output_dir and any(output_dir.glob("*.pdf")))
        )
        self.open_summary_button.setEnabled(
            bool(output_dir and (output_dir / "batch_summary.html").is_file())
        )
        self.open_manifest_button.setEnabled(
            bool(output_dir and (output_dir / "manifest.json").is_file())
        )
        self.status_label.setText(self._catalogs.text("generation.published"))

    def set_failed(self, error) -> None:
        self.state = "failed"
        self.error = error
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._enable_results(False)
        self.status_label.setText(str(error))

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("results.title"))
        controls = (
            (self.generate_button, "results.generate"),
            (self.cancel_button, "action.cancel"),
            (self.open_output_button, "results.open_output"),
            (self.open_combined_button, "results.open_combined"),
            (self.open_summary_button, "results.open_summary"),
            (self.open_manifest_button, "results.open_manifest"),
        )
        for control, key in controls:
            control.setText(self._catalogs.text(key))
            control.setAccessibleName(control.text())

    def _enable_results(self, enabled: bool) -> None:
        for control in (
            self.open_output_button,
            self.open_combined_button,
            self.open_summary_button,
            self.open_manifest_button,
        ):
            control.setEnabled(enabled)
