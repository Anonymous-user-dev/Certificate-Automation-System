"""Batch progress and result page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from certificate_automation.domain import BatchResult, BatchState


class GenerationPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.result: BatchResult | None = None
        self.status_label = QLabel("Waiting to start.")
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.cancel_button = QPushButton("Cancel after current document")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Generate certificate batch"))
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self.cancel_requested)

    def start(self) -> None:
        self.result = None
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Starting secure batch generation…")
        self.cancel_button.setEnabled(True)

    def update_progress(self, event) -> None:
        self.progress_bar.setRange(0, max(event.total, 1))
        self.progress_bar.setValue(event.current)
        self.status_label.setText(event.message)

    def set_result(self, result: BatchResult) -> None:
        self.result = result
        self.cancel_button.setEnabled(False)
        if result.state is BatchState.PUBLISHED:
            self.status_label.setText(
                f"Success. Generated {result.generated_count} verified certificate(s) "
                f"in {result.output_dir}."
            )
            self.progress_bar.setValue(self.progress_bar.maximum())
        elif result.state is BatchState.CANCELLED:
            self.status_label.setText("Cancelled safely. No official batch was published.")

    def set_error(self, message: str) -> None:
        self.result = BatchResult(BatchState.FAILED)
        self.cancel_button.setEnabled(False)
        self.status_label.setText(f"Generation failed safely. {message}")

