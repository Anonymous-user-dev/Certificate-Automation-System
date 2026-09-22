"""Explicit, typed template-field mapping page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from certificate_automation.dataset import TabularDataset
from certificate_automation.i18n import CatalogSet
from certificate_automation.mapping import (
    ColumnValue,
    FixedValue,
    FormattedDateValue,
    JoinValue,
    MappingPlan,
    SequenceValue,
    SourceRowValue,
)


class MappingCard(QWidget):
    changed = Signal()

    def __init__(self, placeholder: str, dataset: TabularDataset, catalogs: CatalogSet, parent=None):
        super().__init__(parent)
        self.placeholder = placeholder
        self.dataset = dataset
        self.catalogs = catalogs
        self.label = QLabel(f"{{{{{placeholder}}}}}")
        self.type_combo = QComboBox()
        self.type_combo.addItem(catalogs.text("mapping.unresolved"), "unresolved")
        self.type_combo.addItem(catalogs.text("mapping.column"), "column")
        self.type_combo.addItem(catalogs.text("mapping.fixed"), "fixed")
        self.type_combo.addItem(catalogs.text("mapping.sequence"), "sequence")
        self.type_combo.addItem(catalogs.text("mapping.source_row"), "source_row")
        self.type_combo.addItem(catalogs.text("mapping.formatted_date"), "formatted_date")
        self.type_combo.addItem(catalogs.text("mapping.join"), "join")
        self.column_combo = QComboBox()
        for column in dataset.columns:
            self.column_combo.addItem(column.label, column.column_id)
        self.fixed_input = QLineEdit()
        self.input_format = QLineEdit("%Y-%m-%d")
        self.output_format = QLineEdit("%d %B %Y")
        layout = QFormLayout(self)
        layout.addRow(self.label, self.type_combo)
        layout.addRow(catalogs.text("mapping.column"), self.column_combo)
        layout.addRow(catalogs.text("mapping.fixed"), self.fixed_input)
        layout.addRow(catalogs.text("mapping.input_format"), self.input_format)
        layout.addRow(catalogs.text("mapping.output_format"), self.output_format)
        self.type_combo.currentIndexChanged.connect(self.changed)
        self.column_combo.currentIndexChanged.connect(self.changed)
        self.fixed_input.textChanged.connect(self.changed)
        self.input_format.textChanged.connect(self.changed)
        self.output_format.textChanged.connect(self.changed)
        self.type_combo.setAccessibleName(self.label.text())
        self.column_combo.setAccessibleName(catalogs.text("mapping.column"))
        self.fixed_input.setAccessibleName(catalogs.text("mapping.fixed"))
        self.input_format.setAccessibleName(catalogs.text("mapping.input_format"))
        self.output_format.setAccessibleName(catalogs.text("mapping.output_format"))

    def set_column(self, column_id_or_label: str) -> None:
        for index in range(self.column_combo.count()):
            if column_id_or_label in {
                self.column_combo.itemData(index),
                self.column_combo.itemText(index),
            }:
                self.column_combo.setCurrentIndex(index)
                self.type_combo.setCurrentIndex(self.type_combo.findData("column"))
                return

    def mapping_source(self):
        kind = self.type_combo.currentData()
        if kind == "column":
            return ColumnValue(str(self.column_combo.currentData()))
        if kind == "fixed":
            return FixedValue(self.fixed_input.text())
        if kind == "sequence":
            return SequenceValue()
        if kind == "source_row":
            return SourceRowValue()
        if kind == "formatted_date":
            return FormattedDateValue(
                ColumnValue(str(self.column_combo.currentData())),
                self.input_format.text(),
                self.output_format.text(),
            )
        if kind == "join":
            return JoinValue(tuple(column.column_id for column in self.dataset.columns), " ")
        return None


class MatchPage(QWidget):
    plan_changed = Signal(object)
    plan_accepted = Signal(object)

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._dataset = None
        self.cards: dict[str, MappingCard] = {}
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.cards_widget)
        self.continue_button = QPushButton()
        self.continue_button.setProperty("role", "primary")
        self.continue_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.explanation)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.continue_button)
        self.continue_button.clicked.connect(lambda: self.plan_accepted.emit(self.mapping_plan()))
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_context(self, dataset: TabularDataset, placeholders: tuple[str, ...]) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = {}
        self._dataset = dataset
        for placeholder in placeholders:
            card = MappingCard(placeholder, dataset, self._catalogs)
            card.changed.connect(self._changed)
            self.cards[placeholder] = card
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)
        self._changed()

    def mapping_plan(self) -> MappingPlan:
        return MappingPlan(
            {
                placeholder: source
                for placeholder, card in self.cards.items()
                if (source := card.mapping_source()) is not None
            }
        )

    def focus_placeholder(self, name: str) -> None:
        card = self.cards[name]
        card.setFocus()
        self.scroll.ensureWidgetVisible(card)

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("mapping.title"))
        self.explanation.setText(self._catalogs.text("mapping.explanation"))
        self.continue_button.setText(self._catalogs.text("action.continue"))
        self.continue_button.setAccessibleName(self.continue_button.text())

    def _changed(self) -> None:
        plan = self.mapping_plan()
        complete = bool(self.cards) and not plan.unresolved(tuple(self.cards))
        self.continue_button.setEnabled(complete)
        self.plan_changed.emit(plan)
