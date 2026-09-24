"""Selected output formats, destination, and generation order."""

from __future__ import annotations

from pathlib import Path
from decimal import Decimal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from certificate_automation.i18n import CatalogError, CatalogSet
from certificate_automation.output_options import OutputOptions
from certificate_automation.print_readiness import PrintSettings
from certificate_automation.template_health import PageGeometry
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
        self.individual_pdf.setChecked(True)
        self.combined_pdf = QCheckBox()
        self.geometry_help = QLabel()
        self.geometry_help.setWordWrap(True)
        self.print_width_label = QLabel()
        self.print_height_label = QLabel()
        self.separator_every_label = QLabel()
        self.print_width = QDoubleSpinBox()
        self.print_width.setRange(0, 2000)
        self.print_width.setDecimals(2)
        self.print_width.setSuffix(" pt")
        self.print_height = QDoubleSpinBox()
        self.print_height.setRange(0, 2000)
        self.print_height.setDecimals(2)
        self.print_height.setSuffix(" pt")
        self.print_orientation = QComboBox()
        self.print_orientation.addItem("", "portrait")
        self.print_orientation.addItem("", "landscape")
        self.separator_enabled = QCheckBox()
        self.separator_every = QSpinBox()
        self.separator_every.setRange(1, 10000)
        self.separator_every.setValue(25)
        self.separator_every.setEnabled(False)
        self.page_forecast = QLabel()
        self.page_forecast.setWordWrap(True)
        self.printing_note = QLabel()
        self.printing_note.setWordWrap(True)
        self._expected_pages_per_certificate = 1
        self.word_status = QLabel()
        self.word_status.setWordWrap(True)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self._word_availability: WordAvailability | None = None
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
        layout.addWidget(self.geometry_help)
        geometry_row = QHBoxLayout()
        geometry_row.addWidget(self.print_width_label)
        geometry_row.addWidget(self.print_width)
        geometry_row.addWidget(self.print_height_label)
        geometry_row.addWidget(self.print_height)
        geometry_row.addWidget(self.print_orientation)
        layout.addLayout(geometry_row)
        separator_row = QHBoxLayout()
        separator_row.addWidget(self.separator_enabled)
        separator_row.addWidget(self.separator_every_label)
        separator_row.addWidget(self.separator_every)
        layout.addLayout(separator_row)
        layout.addWidget(self.page_forecast)
        layout.addWidget(self.printing_note)
        layout.addWidget(self.word_status)
        layout.addWidget(self.summary_label)
        layout.addLayout(destination_row)
        layout.addWidget(self.batch_name)
        layout.addWidget(self.order_list)
        layout.addWidget(self.error_label)
        layout.addWidget(self.continue_button)
        self.browse_button.clicked.connect(self._browse)
        self.continue_button.clicked.connect(self._accept)
        for control in (self.docx, self.individual_pdf, self.combined_pdf):
            control.toggled.connect(self._update_summary)
        self.combined_pdf.toggled.connect(self._combined_changed)
        self.separator_enabled.toggled.connect(self._separator_changed)
        self.separator_every.valueChanged.connect(self._update_summary)
        for control in (self.print_width, self.print_height):
            control.valueChanged.connect(self._update_summary)
        self.print_orientation.currentIndexChanged.connect(self._update_summary)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self._combined_changed(self.combined_pdf.isChecked())
        self.retranslate()

    def set_order(self, order: tuple[str, ...]) -> None:
        self._order = tuple(order)
        self.order_list.clear()
        self.order_list.addItems(self._order)
        self._update_summary()

    def set_template_geometry(self, geometry: PageGeometry | None) -> None:
        if geometry is None:
            self.print_width.setValue(0)
            self.print_height.setValue(0)
            return
        self.print_width.setValue(geometry.width_points)
        self.print_height.setValue(geometry.height_points)
        self.print_orientation.setCurrentIndex(1 if geometry.orientation == "landscape" else 0)
        self._update_summary()

    def set_expected_pages_per_certificate(self, count: int) -> None:
        self._expected_pages_per_certificate = max(1, int(count))
        self._update_summary()

    def set_options(self, options: OutputOptions) -> None:
        self.set_order(options.row_ids)
        self.docx.setChecked(options.docx)
        self.individual_pdf.setChecked(options.individual_pdf)
        self.combined_pdf.setChecked(options.combined_pdf)
        self.destination.setText(str(options.destination))
        self.batch_name.setText(options.batch_name)
        if options.print_settings is not None:
            settings = options.print_settings
            self.print_width.setValue(float(settings.expected_width_points))
            self.print_height.setValue(float(settings.expected_height_points))
            self.print_orientation.setCurrentIndex(1 if settings.orientation == "landscape" else 0)
            self.separator_enabled.setChecked(settings.separator_every is not None)
            if settings.separator_every is not None:
                self.separator_every.setValue(settings.separator_every)

    def reset_options(self) -> None:
        self.set_order(())
        self.docx.setChecked(True)
        self.individual_pdf.setChecked(True)
        self.combined_pdf.setChecked(False)
        self.separator_enabled.setChecked(False)
        self.print_width.setValue(0)
        self.print_height.setValue(0)
        self.print_orientation.setCurrentIndex(0)
        self._expected_pages_per_certificate = 1
        self.destination.clear()
        self.batch_name.setText(self._catalogs.text("output.default_batch_name"))
        self.error_label.clear()
        self.continue_button.setEnabled(False)

    def options(self, generation_order: tuple[str, ...] | None = None) -> OutputOptions:
        settings = None
        if self.print_width.value() > 0 and self.print_height.value() > 0:
            settings = PrintSettings(
                Decimal(str(self.print_width.value())), Decimal(str(self.print_height.value())),
                self.print_orientation.currentData(),
                self.separator_every.value() if self.separator_enabled.isChecked() else None,
            )
        return OutputOptions(
            self.docx.isChecked(),
            self.individual_pdf.isChecked(),
            self.combined_pdf.isChecked(),
            Path(self.destination.text()),
            self.batch_name.text().strip(),
            tuple(generation_order or self._order),
            settings,
        )

    def _combined_changed(self, selected: bool) -> None:
        if not selected:
            self.separator_enabled.setChecked(False)
        self.separator_enabled.setEnabled(selected)
        self._update_summary()

    def _separator_changed(self, enabled: bool) -> None:
        self.separator_every.setEnabled(enabled and self.combined_pdf.isChecked())
        self._update_summary()

    def set_word_availability(self, availability: WordAvailability) -> None:
        self._word_availability = availability
        for control in (self.individual_pdf, self.combined_pdf):
            control.setEnabled(availability.available)
            control.setToolTip("" if availability.available else availability.message)
            if not availability.available:
                control.setChecked(False)
        self._update_word_status()
        self._update_summary()

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
        self.geometry_help.setText(self._catalogs.text("output.page_geometry_help"))
        self.print_width_label.setText(self._catalogs.text("output.page_width"))
        self.print_height_label.setText(self._catalogs.text("output.page_height"))
        self.separator_every_label.setText(self._catalogs.text("output.separator_every"))
        self.print_width.setAccessibleName(self._catalogs.text("output.page_width"))
        self.print_height.setAccessibleName(self._catalogs.text("output.page_height"))
        self.print_orientation.setItemText(0, self._catalogs.text("output.portrait"))
        self.print_orientation.setItemText(1, self._catalogs.text("output.landscape"))
        self.print_orientation.setAccessibleName(self._catalogs.text("output.orientation"))
        self.separator_enabled.setText(self._catalogs.text("output.separator_enabled"))
        self.separator_enabled.setAccessibleName(self.separator_enabled.text())
        self.separator_every.setAccessibleName(self._catalogs.text("output.separator_every"))
        self.printing_note.setText(self._catalogs.text("output.printing_note"))
        self._update_word_status()
        self._update_summary()

    def _update_word_status(self) -> None:
        availability = self._word_availability
        if availability is None:
            self.word_status.setText(self._catalogs.text("output.word_requirement"))
        elif availability.available:
            self.word_status.setText(self._catalogs.text("output.word_available"))
        else:
            try:
                reason = self._catalogs.text(availability.code)
            except CatalogError:
                reason = availability.message
            reason = reason.rstrip().rstrip(".。")
            self.word_status.setText(
                self._catalogs.text(
                    "output.word_unavailable",
                    reason=reason,
                )
            )

    def _update_summary(self) -> None:
        recipients = len(self._order)
        self.summary_label.setText(
            self._catalogs.text(
                "output.summary",
                docx=recipients if self.docx.isChecked() else 0,
                pdf=recipients if self.individual_pdf.isChecked() else 0,
                combined=1 if self.combined_pdf.isChecked() else 0,
            )
        )
        if self.combined_pdf.isChecked():
            certificate_pages = recipients * self._expected_pages_per_certificate
            separators = ((recipients - 1) // self.separator_every.value()
                          if self.separator_enabled.isChecked() and recipients else 0)
            self.page_forecast.setText(self._catalogs.text(
                "output.page_forecast", certificates=certificate_pages,
                separators=separators, total=certificate_pages + separators,
            ))
        else:
            self.page_forecast.setText(self._catalogs.text("output.no_combined_forecast"))

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
