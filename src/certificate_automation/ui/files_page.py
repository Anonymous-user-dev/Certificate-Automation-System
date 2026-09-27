"""File and worksheet selection page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from certificate_automation.i18n import CatalogSet, package_root


class FilesPage(QWidget):
    continue_requested = Signal()
    workbook_selected = Signal(str)
    destination_selected = Signal(str)
    view_recovery_requested = Signal()
    remove_recovery_requested = Signal()

    def __init__(self, parent=None, *, catalogs: CatalogSet | None = None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs or CatalogSet.load(package_root())
        self._catalogs.subscribe(lambda _locale: self.retranslate())
        self._settings = QSettings()
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.workbook_input = QLineEdit()
        self.template_input = QLineEdit()
        self.destination_input = QLineEdit()
        self.worksheet_combo = QComboBox()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.recovery_panel = QWidget()
        recovery_layout = QHBoxLayout(self.recovery_panel)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        self.recovery_label = QLabel()
        self.recovery_label.setWordWrap(True)
        self.view_recovery_button = QPushButton()
        self.remove_recovery_button = QPushButton()
        recovery_layout.addWidget(self.recovery_label, 1)
        recovery_layout.addWidget(self.view_recovery_button)
        recovery_layout.addWidget(self.remove_recovery_button)
        self.recovery_panel.hide()
        self.continue_button = QPushButton()
        self.continue_button.setEnabled(False)

        form = QFormLayout()
        self.workbook_row = self._picker_row(self.workbook_input, "workbook")
        self.template_row = self._picker_row(self.template_input, "template")
        self.destination_row = self._picker_row(self.destination_input, "destination")
        form.addRow(self._catalogs.text("legacy.files.workbook"), self.workbook_row)
        form.addRow(self._catalogs.text("legacy.files.worksheet"), self.worksheet_combo)
        form.addRow(self._catalogs.text("legacy.files.template"), self.template_row)
        form.addRow(self._catalogs.text("legacy.files.destination"), self.destination_row)
        self._form = form
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.recovery_panel)
        layout.addStretch()
        layout.addWidget(self.continue_button)

        for control in (
            self.workbook_input,
            self.template_input,
            self.destination_input,
        ):
            control.textChanged.connect(self._update_ready)
        self.worksheet_combo.currentIndexChanged.connect(self._update_ready)
        self.continue_button.clicked.connect(self.continue_requested)
        self.workbook_input.editingFinished.connect(
            lambda: self.workbook_selected.emit(self.workbook_input.text().strip())
        )
        self.destination_input.editingFinished.connect(
            lambda: self.destination_selected.emit(self.destination_input.text().strip())
        )
        self.view_recovery_button.clicked.connect(self.view_recovery_requested)
        self.remove_recovery_button.clicked.connect(self.remove_recovery_requested)
        self.retranslate()

    def _picker_row(self, field: QLineEdit, kind: str) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        button = QPushButton()
        button.setProperty("pickerKind", kind)
        button.clicked.connect(lambda: self._browse(field, kind))
        row.addWidget(field)
        row.addWidget(button)
        return container

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("legacy.files.title"))
        self.description.setText(self._catalogs.text("legacy.files.explanation"))
        self.error_label.setAccessibleName(self._catalogs.text("legacy.files.error"))
        self.view_recovery_button.setText(self._catalogs.text("legacy.files.view_diagnostic"))
        self.remove_recovery_button.setText(self._catalogs.text("legacy.files.remove_incomplete"))
        self.continue_button.setText(self._catalogs.text("legacy.files.continue"))
        labels = (
            "legacy.files.workbook", "legacy.files.worksheet",
            "legacy.files.template", "legacy.files.destination",
        )
        for row, key in enumerate(labels):
            label = self._form.labelForField(self._form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget())
            if label is not None:
                label.setText(self._catalogs.text(key))
        for button in self.findChildren(QPushButton):
            kind = button.property("pickerKind")
            if kind:
                button.setText(self._catalogs.text("legacy.files.browse"))
                button.setAccessibleName(self._catalogs.text("legacy.files.browse_for", kind=self._catalogs.text(f"legacy.files.{kind}")))
            elif button.text():
                button.setAccessibleName(button.text())

    def _browse(self, field: QLineEdit, kind: str) -> None:
        initial = self._settings.value(f"recent/{kind}", str(Path.home()))
        if kind == "workbook":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                self._catalogs.text("legacy.files.select_workbook"),
                initial,
                "Excel workbooks (*.xlsx)",
            )
        elif kind == "template":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                self._catalogs.text("legacy.files.select_template"),
                initial,
                "Word documents (*.docx)",
            )
        else:
            selected = QFileDialog.getExistingDirectory(
                self,
                self._catalogs.text("legacy.files.select_destination"),
                initial,
            )
        if not selected:
            return
        field.setText(selected)
        self._settings.setValue(f"recent/{kind}", str(Path(selected).parent))
        if kind == "workbook":
            self.workbook_selected.emit(selected)
        elif kind == "destination":
            self.destination_selected.emit(selected)

    def set_worksheets(self, names: tuple[str, ...]) -> None:
        current = self.worksheet_combo.currentText()
        self.worksheet_combo.clear()
        self.worksheet_combo.addItems(names)
        if current in names:
            self.worksheet_combo.setCurrentText(current)
        self._update_ready()

    def show_error(self, message: str) -> None:
        self.error_label.setText(self._catalogs.text("legacy.files.error_detail", detail=message) if message else "")

    def set_incomplete_batches(self, records, *, unavailable_message: str | None = None) -> None:
        self.incomplete_batches = tuple(records)
        if unavailable_message is not None:
            first_line = unavailable_message
            if self.incomplete_batches:
                first = self.incomplete_batches[0]
                first_line += "\n" + self._catalogs.text("legacy.files.recovery", count=len(self.incomplete_batches), batch_id=first.batch_id)
            self.recovery_label.setText(first_line)
            self.view_recovery_button.setEnabled(False)
            self.remove_recovery_button.setEnabled(False)
            self.recovery_panel.show()
            return
        self.remove_recovery_button.setEnabled(bool(self.incomplete_batches))
        if not self.incomplete_batches:
            self.recovery_label.clear()
            self.recovery_panel.hide()
            return
        first = self.incomplete_batches[0]
        count = len(self.incomplete_batches)
        self.recovery_label.setText(self._catalogs.text("legacy.files.recovery", count=count, batch_id=first.batch_id))
        self.view_recovery_button.setEnabled(first.diagnostic_path.is_file())
        self.recovery_panel.show()

    def selected_paths(self) -> tuple[Path, str, Path, Path]:
        return (
            Path(self.workbook_input.text().strip()),
            self.worksheet_combo.currentText(),
            Path(self.template_input.text().strip()),
            Path(self.destination_input.text().strip()),
        )

    def _update_ready(self) -> None:
        self.continue_button.setEnabled(
            bool(self.workbook_input.text().strip())
            and bool(self.template_input.text().strip())
            and bool(self.destination_input.text().strip())
            and self.worksheet_combo.count() > 0
        )
