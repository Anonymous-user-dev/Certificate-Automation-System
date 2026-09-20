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


class FilesPage(QWidget):
    continue_requested = Signal()
    workbook_selected = Signal(str)
    destination_selected = Signal(str)
    view_recovery_requested = Signal()
    remove_recovery_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = QSettings()
        title = QLabel("Choose your certificate files")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Select the Excel recipient list, official Word template, and output folder."
        )
        description.setWordWrap(True)
        self.workbook_input = QLineEdit()
        self.template_input = QLineEdit()
        self.destination_input = QLineEdit()
        self.worksheet_combo = QComboBox()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName("File selection error")
        self.recovery_panel = QWidget()
        recovery_layout = QHBoxLayout(self.recovery_panel)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        self.recovery_label = QLabel()
        self.recovery_label.setWordWrap(True)
        self.view_recovery_button = QPushButton("View diagnostic")
        self.remove_recovery_button = QPushButton("Remove incomplete files")
        recovery_layout.addWidget(self.recovery_label, 1)
        recovery_layout.addWidget(self.view_recovery_button)
        recovery_layout.addWidget(self.remove_recovery_button)
        self.recovery_panel.hide()
        self.continue_button = QPushButton("Continue to field mapping")
        self.continue_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Excel workbook", self._picker_row(self.workbook_input, "workbook"))
        form.addRow("Worksheet", self.worksheet_combo)
        form.addRow("Word template", self._picker_row(self.template_input, "template"))
        form.addRow("Output folder", self._picker_row(self.destination_input, "destination"))
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(description)
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

    def _picker_row(self, field: QLineEdit, kind: str) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…")
        button.setAccessibleName(f"Browse for {kind}")
        button.clicked.connect(lambda: self._browse(field, kind))
        row.addWidget(field)
        row.addWidget(button)
        return container

    def _browse(self, field: QLineEdit, kind: str) -> None:
        initial = self._settings.value(f"recent/{kind}", str(Path.home()))
        if kind == "workbook":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select Excel workbook",
                initial,
                "Excel workbooks (*.xlsx)",
            )
        elif kind == "template":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select Word template",
                initial,
                "Word documents (*.docx)",
            )
        else:
            selected = QFileDialog.getExistingDirectory(
                self,
                "Select output folder",
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
        self.error_label.setText(f"Error: {message}" if message else "")

    def set_incomplete_batches(self, records) -> None:
        self.incomplete_batches = tuple(records)
        if not self.incomplete_batches:
            self.recovery_label.clear()
            self.recovery_panel.hide()
            return
        first = self.incomplete_batches[0]
        count = len(self.incomplete_batches)
        self.recovery_label.setText(
            f"Recovery notice: found {count} incomplete batch record(s). "
            f"Current batch ID: {first.batch_id}."
        )
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
