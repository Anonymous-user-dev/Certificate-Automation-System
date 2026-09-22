"""Explicit, typed template-field mapping page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

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
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
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
        self.column_label = QLabel()
        self.fixed_label = QLabel()
        self.date_help = QLabel()
        self.date_help.setWordWrap(True)
        self.input_format_label = QLabel()
        self.output_format_label = QLabel()
        layout = QFormLayout(self)
        layout.addRow(self.label, self.type_combo)
        layout.addRow(self.help_label)
        layout.addRow(self.column_label, self.column_combo)
        layout.addRow(self.fixed_label, self.fixed_input)
        layout.addRow(self.date_help)
        layout.addRow(self.input_format_label, self.input_format)
        layout.addRow(self.output_format_label, self.output_format)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.column_combo.currentIndexChanged.connect(self.changed)
        self.fixed_input.textChanged.connect(self.changed)
        self.input_format.textChanged.connect(self.changed)
        self.output_format.textChanged.connect(self.changed)
        self.retranslate()
        self._update_visibility()

    def retranslate(self) -> None:
        keys = (
            "mapping.unresolved",
            "mapping.column",
            "mapping.fixed",
            "mapping.sequence",
            "mapping.source_row",
            "mapping.formatted_date",
            "mapping.join",
        )
        for index, key in enumerate(keys):
            self.type_combo.setItemText(index, self.catalogs.text(key))
        self.help_label.setText(
            self.catalogs.text("mapping.field_help", field=self.placeholder)
        )
        self.column_label.setText(self.catalogs.text("mapping.column"))
        self.fixed_label.setText(self.catalogs.text("mapping.fixed"))
        self.date_help.setText(self.catalogs.text("mapping.date_help"))
        self.input_format_label.setText(self.catalogs.text("mapping.input_format"))
        self.output_format_label.setText(self.catalogs.text("mapping.output_format"))
        self.type_combo.setAccessibleName(self.label.text())
        self.column_combo.setAccessibleName(self.column_label.text())
        self.fixed_input.setAccessibleName(self.fixed_label.text())
        self.input_format.setAccessibleName(self.input_format_label.text())
        self.output_format.setAccessibleName(self.output_format_label.text())

    def _type_changed(self) -> None:
        self._update_visibility()
        self.changed.emit()

    def _update_visibility(self) -> None:
        kind = self.type_combo.currentData()
        uses_column = kind in {"column", "formatted_date"}
        is_fixed = kind == "fixed"
        is_date = kind == "formatted_date"
        for widget in (self.column_label, self.column_combo):
            widget.setVisible(uses_column)
        for widget in (self.fixed_label, self.fixed_input):
            widget.setVisible(is_fixed)
        for widget in (
            self.date_help,
            self.input_format_label,
            self.input_format,
            self.output_format_label,
            self.output_format,
        ):
            widget.setVisible(is_date)

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
        for card in self.cards.values():
            card.retranslate()
        self.continue_button.setText(self._catalogs.text("action.continue"))
        self.continue_button.setAccessibleName(self.continue_button.text())

    def _changed(self) -> None:
        plan = self.mapping_plan()
        complete = bool(self.cards) and not plan.unresolved(tuple(self.cards))
        self.continue_button.setEnabled(complete)
        self.plan_changed.emit(plan)
