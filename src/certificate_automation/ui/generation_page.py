"""Batch progress and result page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from certificate_automation.domain import BatchResult, BatchState
from certificate_automation.i18n import CatalogSet, package_root


class GenerationPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None, *, catalogs: CatalogSet | None = None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs or CatalogSet.load(package_root())
        self._catalogs.subscribe(lambda _locale: self.retranslate())
        self.result: BatchResult | None = None
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.cancel_button = QPushButton()
        layout = QVBoxLayout(self)
        self.title = QLabel()
        layout.addWidget(self.title)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.retranslate()

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("nav.generate"))
        if self.result is None:
            self.status_label.setText(self._catalogs.text("legacy.generation.waiting"))
        self.cancel_button.setText(self._catalogs.text("legacy.generation.cancel"))
        self.cancel_button.setAccessibleName(self.cancel_button.text())

    def start(self) -> None:
        self.result = None
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(self._catalogs.text("generation.running"))
        self.cancel_button.setEnabled(True)

    def update_progress(self, event) -> None:
        self.progress_bar.setRange(0, max(event.total, 1))
        self.progress_bar.setValue(event.current)
        self.status_label.setText(event.message)

    def set_result(self, result: BatchResult) -> None:
        self.result = result
        self.cancel_button.setEnabled(False)
        if result.state is BatchState.PUBLISHED:
            self.status_label.setText(self._catalogs.text(
                "legacy.generation.published", count=result.generated_count,
                destination=result.output_dir,
            ))
            self.progress_bar.setValue(self.progress_bar.maximum())
        elif result.state is BatchState.CANCELLED:
            self.status_label.setText(self._catalogs.text("legacy.generation.cancelled"))

    def set_error(self, message: str) -> None:
        self.result = BatchResult(BatchState.FAILED)
        self.cancel_button.setEnabled(False)
        self.status_label.setText(self._catalogs.text("legacy.generation.failed", detail=message))
