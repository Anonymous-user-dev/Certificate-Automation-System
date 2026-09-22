"""Selected output formats, destination, and generation order."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget

from certificate_automation.i18n import CatalogSet
from certificate_automation.output_options import OutputOptions
from certificate_automation.word import WordAvailability


class OutputPage(QWidget):
    options_accepted = Signal(object)

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._order: tuple[str, ...] = ()
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.docx = QCheckBox()
        self.docx.setChecked(True)
        self.individual_pdf = QCheckBox()
        self.combined_pdf = QCheckBox()
        self.destination = QLineEdit()
        self.browse_button = QPushButton()
        self.batch_name = QLineEdit()
        self._last_default_batch_name = ""
        self.order_list = QListWidget()
        self.error_label = QLabel()
        self.error_label.setProperty("state", "error")
        self.continue_button = QPushButton()
        self.continue_button.setProperty("role", "primary")
        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(self.browse_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.docx)
        layout.addWidget(self.individual_pdf)
        layout.addWidget(self.combined_pdf)
        layout.addLayout(destination_row)
        layout.addWidget(self.batch_name)
        layout.addWidget(self.order_list)
        layout.addWidget(self.error_label)
        layout.addWidget(self.continue_button)
        self.browse_button.clicked.connect(self._browse)
        self.continue_button.clicked.connect(self._accept)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_order(self, order: tuple[str, ...]) -> None:
        self._order = tuple(order)
        self.order_list.clear()
        self.order_list.addItems(self._order)

    def options(self, generation_order: tuple[str, ...] | None = None) -> OutputOptions:
        return OutputOptions(
            self.docx.isChecked(),
            self.individual_pdf.isChecked(),
            self.combined_pdf.isChecked(),
            Path(self.destination.text()),
            self.batch_name.text().strip(),
            tuple(generation_order or self._order),
        )

    def set_word_availability(self, availability: WordAvailability) -> None:
        for control in (self.individual_pdf, self.combined_pdf):
            control.setEnabled(availability.available)
            control.setToolTip("" if availability.available else availability.message)

    def retranslate(self) -> None:
        previous_default = self._last_default_batch_name
        translated_default = self._catalogs.text("output.default_batch_name")
        if not self.batch_name.text() or self.batch_name.text() == previous_default:
            self.batch_name.setText(translated_default)
        self._last_default_batch_name = translated_default
        self.title.setText(self._catalogs.text("output.title"))
        controls = (
            (self.docx, "output.docx"),
            (self.individual_pdf, "output.individual_pdf"),
            (self.combined_pdf, "output.combined_pdf"),
            (self.browse_button, "output.choose_destination"),
            (self.continue_button, "action.continue"),
        )
        for control, key in controls:
            control.setText(self._catalogs.text(key))
            control.setAccessibleName(control.text())
        self.destination.setPlaceholderText(self._catalogs.text("output.destination"))
        self.destination.setAccessibleName(self._catalogs.text("output.destination"))
        self.batch_name.setAccessibleName(self._catalogs.text("output.batch_name"))
        self.order_list.setAccessibleName(self._catalogs.text("output.order"))

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._catalogs.text("output.destination"))
        if selected:
            self.destination.setText(selected)

    def _accept(self) -> None:
        try:
            options = self.options()
        except Exception as error:
            code = getattr(error, "code", "output.invalid")
            self.error_label.setText(self._catalogs.text(code))
            return
        self.error_label.clear()
        self.options_accepted.emit(options)
