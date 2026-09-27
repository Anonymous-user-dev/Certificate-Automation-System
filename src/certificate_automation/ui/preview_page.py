"""Preview status page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
from certificate_automation.i18n import CatalogSet, package_root


class PreviewPage(QWidget):
    back_requested = Signal()
    generate_requested = Signal()

    def __init__(self, parent=None, *, catalogs: CatalogSet | None = None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs or CatalogSet.load(package_root())
        self._catalogs.subscribe(lambda _locale: self.retranslate())
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.back_button = QPushButton()
        self.generate_button = QPushButton()
        layout = QVBoxLayout(self)
        self.title = QLabel()
        layout.addWidget(self.title)
        layout.addWidget(self.status_label)
        layout.addStretch()
        layout.addWidget(self.back_button)
        layout.addWidget(self.generate_button)
        self.back_button.clicked.connect(self.back_requested)
        self.generate_button.clicked.connect(self.generate_requested)
        self.retranslate()

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("legacy.preview.title"))
        self.status_label.setText(self._catalogs.text("legacy.preview.waiting"))
        self.back_button.setText(self._catalogs.text("legacy.preview.back"))
        self.generate_button.setText(self._catalogs.text("action.generate"))
        for control in (self.back_button, self.generate_button):
            control.setAccessibleName(control.text())
