"""Flexible placeholder-to-column mapping page."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from certificate_automation.mapping import MappingSelection
from certificate_automation.workbook import WorkbookData


@dataclass(slots=True)
class MappingRow:
    column_combo: QComboBox
    fixed_input: QLineEdit


class MappingPage(QWidget):
    back_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: dict[str, MappingRow] = {}
        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_widget)
        self.back_button = QPushButton("Back")
        self.continue_button = QPushButton("Validate complete batch")
        self.continue_button.setEnabled(False)
        actions = QGridLayout()
        actions.addWidget(self.back_button, 0, 0)
        actions.addWidget(self.continue_button, 0, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Map template fields"))
        explanation = QLabel(
            "Review automatic matches. Choose an Excel column or enter one fixed value "
            "for every placeholder."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(scroll)
        layout.addLayout(actions)
        self.back_button.clicked.connect(self.back_requested)
        self.continue_button.clicked.connect(self.continue_requested)

    def configure(
        self,
        workbook: WorkbookData,
        placeholders: tuple[str, ...],
        suggestions: MappingSelection,
    ) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows.clear()
        self._grid.addWidget(QLabel("Template placeholder"), 0, 0)
        self._grid.addWidget(QLabel("Excel column"), 0, 1)
        self._grid.addWidget(QLabel("Or fixed value"), 0, 2)
        for row_number, placeholder in enumerate(placeholders, start=1):
            label = QLabel(f"{{{{{placeholder}}}}}")
            combo = QComboBox()
            combo.addItem("No column selected", None)
            for header in workbook.headers:
                combo.addItem(workbook.display_headers[header], header)
            suggested = suggestions.columns.get(placeholder)
            if suggested is not None:
                index = combo.findData(suggested)
                combo.setCurrentIndex(index)
            fixed = QLineEdit()
            fixed.setPlaceholderText("Optional fixed value")
            fixed.setEnabled(combo.currentData() is None)
            combo.currentIndexChanged.connect(
                lambda _index, selected=combo, entry=fixed: self._mapping_changed(
                    selected,
                    entry,
                )
            )
            fixed.textChanged.connect(self._update_ready)
            self._grid.addWidget(label, row_number, 0)
            self._grid.addWidget(combo, row_number, 1)
            self._grid.addWidget(fixed, row_number, 2)
            self.rows[placeholder] = MappingRow(combo, fixed)
        self._update_ready()

    def _mapping_changed(self, combo: QComboBox, fixed: QLineEdit) -> None:
        fixed.setEnabled(combo.currentData() is None)
        self._update_ready()

    def selection(self) -> MappingSelection:
        columns = {
            placeholder: row.column_combo.currentData()
            for placeholder, row in self.rows.items()
        }
        fixed_values = {
            placeholder: row.fixed_input.text().strip()
            for placeholder, row in self.rows.items()
            if row.column_combo.currentData() is None and row.fixed_input.text().strip()
        }
        return MappingSelection(columns, fixed_values)

    def _update_ready(self) -> None:
        ready = bool(self.rows) and all(
            row.column_combo.currentData() is not None
            or bool(row.fixed_input.text().strip())
            for row in self.rows.values()
        )
        self.continue_button.setEnabled(ready)

