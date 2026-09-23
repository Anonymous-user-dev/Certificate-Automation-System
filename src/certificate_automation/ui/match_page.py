"""Explicit, typed template-field mapping page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
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
    MappingPlanError,
    SequenceValue,
    SourceRowValue,
)
from certificate_automation.profiles import ProfileComparison, ProfileMatchStatus


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
        self.join_columns = QLineEdit(", ".join(column.column_id for column in dataset.columns))
        self.join_separator = QLineEdit(" ")
        self.sequence_start = QSpinBox()
        self.sequence_start.setRange(-1_000_000_000, 1_000_000_000)
        self.sequence_start.setValue(1)
        self.sequence_step = QSpinBox()
        self.sequence_step.setRange(-1_000_000_000, 1_000_000_000)
        self.sequence_step.setValue(1)
        self.sequence_width = QSpinBox()
        self.sequence_width.setRange(1, 100)
        self.sequence_prefix = QLineEdit()
        self.sequence_suffix = QLineEdit()
        self.input_format = QLineEdit("%Y-%m-%d")
        self.output_format = QLineEdit("%d %B %Y")
        self.column_label = QLabel()
        self.fixed_label = QLabel()
        self.join_columns_label = QLabel()
        self.join_separator_label = QLabel()
        self.sequence_start_label = QLabel()
        self.sequence_step_label = QLabel()
        self.sequence_width_label = QLabel()
        self.sequence_prefix_label = QLabel()
        self.sequence_suffix_label = QLabel()
        self.date_help = QLabel()
        self.date_help.setWordWrap(True)
        self.input_format_label = QLabel()
        self.output_format_label = QLabel()
        layout = QFormLayout(self)
        layout.addRow(self.label, self.type_combo)
        layout.addRow(self.help_label)
        layout.addRow(self.column_label, self.column_combo)
        layout.addRow(self.fixed_label, self.fixed_input)
        layout.addRow(self.join_columns_label, self.join_columns)
        layout.addRow(self.join_separator_label, self.join_separator)
        layout.addRow(self.sequence_start_label, self.sequence_start)
        layout.addRow(self.sequence_step_label, self.sequence_step)
        layout.addRow(self.sequence_width_label, self.sequence_width)
        layout.addRow(self.sequence_prefix_label, self.sequence_prefix)
        layout.addRow(self.sequence_suffix_label, self.sequence_suffix)
        layout.addRow(self.date_help)
        layout.addRow(self.input_format_label, self.input_format)
        layout.addRow(self.output_format_label, self.output_format)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.column_combo.currentIndexChanged.connect(self.changed)
        self.fixed_input.textChanged.connect(self.changed)
        self.join_columns.textChanged.connect(self.changed)
        self.join_separator.textChanged.connect(self.changed)
        self.sequence_start.valueChanged.connect(self.changed)
        self.sequence_step.valueChanged.connect(self.changed)
        self.sequence_width.valueChanged.connect(self.changed)
        self.sequence_prefix.textChanged.connect(self.changed)
        self.sequence_suffix.textChanged.connect(self.changed)
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
        self.join_columns_label.setText(self.catalogs.text("mapping.join_columns"))
        self.join_separator_label.setText(self.catalogs.text("mapping.join_separator"))
        for label, control, key in (
            (self.sequence_start_label, self.sequence_start, "mapping.sequence_start"),
            (self.sequence_step_label, self.sequence_step, "mapping.sequence_step"),
            (self.sequence_width_label, self.sequence_width, "mapping.sequence_width"),
            (self.sequence_prefix_label, self.sequence_prefix, "mapping.sequence_prefix"),
            (self.sequence_suffix_label, self.sequence_suffix, "mapping.sequence_suffix"),
        ):
            label.setText(self.catalogs.text(key))
            control.setAccessibleName(label.text())
        self.date_help.setText(self.catalogs.text("mapping.date_help"))
        self.input_format_label.setText(self.catalogs.text("mapping.input_format"))
        self.output_format_label.setText(self.catalogs.text("mapping.output_format"))
        self.type_combo.setAccessibleName(self.label.text())
        self.column_combo.setAccessibleName(self.column_label.text())
        self.fixed_input.setAccessibleName(self.fixed_label.text())
        self.join_columns.setAccessibleName(self.join_columns_label.text())
        self.join_separator.setAccessibleName(self.join_separator_label.text())
        self.input_format.setAccessibleName(self.input_format_label.text())
        self.output_format.setAccessibleName(self.output_format_label.text())

    def _type_changed(self) -> None:
        self._update_visibility()
        self.changed.emit()

    def _update_visibility(self) -> None:
        kind = self.type_combo.currentData()
        uses_column = kind in {"column", "formatted_date"}
        is_fixed = kind == "fixed"
        is_join = kind == "join"
        is_date = kind == "formatted_date"
        is_sequence = kind == "sequence"
        for widget in (self.column_label, self.column_combo):
            widget.setVisible(uses_column)
        for widget in (self.fixed_label, self.fixed_input):
            widget.setVisible(is_fixed)
        for widget in (
            self.join_columns_label, self.join_columns,
            self.join_separator_label, self.join_separator,
        ):
            widget.setVisible(is_join)
        for widget in (
            self.sequence_start_label, self.sequence_start,
            self.sequence_step_label, self.sequence_step,
            self.sequence_width_label, self.sequence_width,
            self.sequence_prefix_label, self.sequence_prefix,
            self.sequence_suffix_label, self.sequence_suffix,
        ):
            widget.setVisible(is_sequence)
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

    def set_mapping_source(self, source) -> None:
        if isinstance(source, ColumnValue):
            if self.column_combo.findData(source.column_id) < 0:
                raise MappingPlanError("mapping.unknown_column")
            self.set_column(source.column_id)
        elif isinstance(source, FixedValue):
            self.fixed_input.setText(source.value)
            self.type_combo.setCurrentIndex(self.type_combo.findData("fixed"))
        elif isinstance(source, SequenceValue):
            self.sequence_start.setValue(source.start)
            self.sequence_step.setValue(source.step)
            self.sequence_width.setValue(source.width)
            self.sequence_prefix.setText(source.prefix)
            self.sequence_suffix.setText(source.suffix)
            self.type_combo.setCurrentIndex(self.type_combo.findData("sequence"))
        elif isinstance(source, SourceRowValue):
            self.type_combo.setCurrentIndex(self.type_combo.findData("source_row"))
        elif isinstance(source, FormattedDateValue):
            if self.column_combo.findData(source.source.column_id) < 0:
                raise MappingPlanError("mapping.unknown_column")
            self.column_combo.setCurrentIndex(self.column_combo.findData(source.source.column_id))
            self.input_format.setText(source.input_format)
            self.output_format.setText(source.output_format)
            self.type_combo.setCurrentIndex(self.type_combo.findData("formatted_date"))
        elif isinstance(source, JoinValue):
            known = {column.column_id for column in self.dataset.columns}
            if any(column_id not in known for column_id in source.column_ids):
                raise MappingPlanError("mapping.unknown_column")
            self.join_columns.setText(", ".join(source.column_ids))
            self.join_separator.setText(source.separator)
            self.type_combo.setCurrentIndex(self.type_combo.findData("join"))
        else:
            raise MappingPlanError("mapping.invalid_json")

    def mapping_source(self):
        kind = self.type_combo.currentData()
        if kind == "column":
            return ColumnValue(str(self.column_combo.currentData()))
        if kind == "fixed":
            return FixedValue(self.fixed_input.text())
        if kind == "sequence":
            return SequenceValue(
                self.sequence_start.value(), self.sequence_step.value(),
                self.sequence_width.value(), self.sequence_prefix.text(),
                self.sequence_suffix.text(),
            )
        if kind == "source_row":
            return SourceRowValue()
        if kind == "formatted_date":
            return FormattedDateValue(
                ColumnValue(str(self.column_combo.currentData())),
                self.input_format.text(),
                self.output_format.text(),
            )
        if kind == "join":
            column_ids = tuple(
                item.strip() for item in self.join_columns.text().split(",") if item.strip()
            )
            known = {column.column_id for column in self.dataset.columns}
            if any(column_id not in known for column_id in column_ids):
                raise MappingPlanError("mapping.unknown_column")
            return JoinValue(column_ids, self.join_separator.text())
        return None


class MatchPage(QWidget):
    plan_changed = Signal(object)
    plan_accepted = Signal(object)
    save_profile_requested = Signal()
    apply_profile_requested = Signal()

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
        self.profile_help = QLabel()
        self.profile_help.setWordWrap(True)
        self.save_profile_button = QPushButton()
        self.apply_profile_button = QPushButton()
        profile_buttons = QHBoxLayout()
        profile_buttons.addWidget(self.save_profile_button)
        profile_buttons.addWidget(self.apply_profile_button)
        self.comparison_table = QTableWidget(0, 2)
        self.comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison_table.setMinimumHeight(140)
        self.comparison_table.hide()
        self._comparison: ProfileComparison | None = None
        self.continue_button = QPushButton()
        self.continue_button.setProperty("role", "primary")
        self.continue_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.explanation)
        layout.addWidget(self.profile_help)
        layout.addLayout(profile_buttons)
        layout.addWidget(self.comparison_table)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.continue_button)
        self.continue_button.clicked.connect(lambda: self.plan_accepted.emit(self.mapping_plan()))
        self.save_profile_button.clicked.connect(self.save_profile_requested.emit)
        self.apply_profile_button.clicked.connect(self.apply_profile_requested.emit)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_context(self, dataset: TabularDataset, placeholders: tuple[str, ...]) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = {}
        self._dataset = dataset
        self._comparison = None
        self.comparison_table.hide()
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

    def set_plan(self, plan: MappingPlan) -> None:
        if not set(plan.sources) <= set(self.cards):
            raise MappingPlanError("mapping.invalid_json")
        for card in self.cards.values():
            card.type_combo.setCurrentIndex(card.type_combo.findData("unresolved"))
        for placeholder, source in plan.sources.items():
            self.cards[placeholder].set_mapping_source(source)
        if self.mapping_plan().to_json() != plan.to_json():
            raise MappingPlanError("mapping.invalid_json")

    def show_profile_comparison(self, comparison: ProfileComparison) -> None:
        self._comparison = comparison
        self.comparison_table.setRowCount(len(comparison.matches))
        for row, (placeholder, match) in enumerate(comparison.matches.items()):
            self.comparison_table.setItem(row, 0, QTableWidgetItem(f"{{{{{placeholder}}}}}"))
            self.comparison_table.setItem(row, 1, QTableWidgetItem(self._catalogs.text(f"profile.status.{match.status.value}")))
        self.comparison_table.show()

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
        self.profile_help.setText(self._catalogs.text("profile.help"))
        self.save_profile_button.setText(self._catalogs.text("profile.save"))
        self.apply_profile_button.setText(self._catalogs.text("profile.apply"))
        self.save_profile_button.setAccessibleName(self.save_profile_button.text())
        self.apply_profile_button.setAccessibleName(self.apply_profile_button.text())
        self.comparison_table.setHorizontalHeaderLabels((self._catalogs.text("profile.field"), self._catalogs.text("profile.result")))
        self.comparison_table.setAccessibleName(self._catalogs.text("profile.comparison"))
        if self._comparison is not None:
            self.show_profile_comparison(self._comparison)

    def _changed(self) -> None:
        try:
            plan = self.mapping_plan()
        except MappingPlanError:
            self.continue_button.setEnabled(False)
            return
        complete = bool(self.cards) and not plan.unresolved(tuple(self.cards))
        self.continue_button.setEnabled(complete)
        self.plan_changed.emit(plan)
