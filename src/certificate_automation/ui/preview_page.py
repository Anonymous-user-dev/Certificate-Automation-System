"""Preview status page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class PreviewPage(QWidget):
    back_requested = Signal()
    generate_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.status_label = QLabel("Preview has not been generated.")
        self.status_label.setWordWrap(True)
        self.back_button = QPushButton("Back to validation")
        self.generate_button = QPushButton("Generate official batch")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Certificate preview"))
        layout.addWidget(self.status_label)
        layout.addStretch()
        layout.addWidget(self.back_button)
        layout.addWidget(self.generate_button)
        self.back_button.clicked.connect(self.back_requested)
        self.generate_button.clicked.connect(self.generate_requested)

