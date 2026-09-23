"""Recipient source selection and spreadsheet-like editing page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from certificate_automation.dataset import DatasetError, TabularDataset
from certificate_automation.domain import Issue
from certificate_automation.i18n import CatalogSet
from certificate_automation.importers.clipboard import create_manual_dataset
from certificate_automation.ui.table_model import DatasetTableModel


class ImportPreviewDialog(QDialog):
    """Show parsing choices and sample rows before replacing active edits."""

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._catalogs.subscribe(self._locale_changed)
        self.title_label = QLabel()
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.details_label)
        layout.addWidget(self.preview_table)
        layout.addWidget(self.buttons)
        self._details = {
            "encoding": "—",
            "delimiter": "—",
            "worksheet": "—",
            "hidden_policy": "—",
        }
        self.retranslate()

    def set_preview(
        self,
        *,
        rows: tuple[tuple[str, ...], ...],
        encoding: str,
        delimiter: str,
        worksheet: str,
        hidden_policy: str,
    ) -> None:
        self._details = {
            "encoding": encoding,
            "delimiter": delimiter,
            "worksheet": worksheet,
            "hidden_policy": hidden_policy,
        }
        width = max((len(row) for row in rows), default=0)
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setColumnCount(width)
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.preview_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(value),
                )
        self._render_details()

    def retranslate(self) -> None:
        self.setWindowTitle(self._catalogs.text("import.preview"))
        self.title_label.setText(self._catalogs.text("import.preview"))
        self._render_details()

    def _render_details(self) -> None:
        self.details_label.setText(
            self._catalogs.text("import.preview_details", **self._details)
        )

    def _locale_changed(self, _locale: str) -> None:
        self.retranslate()


class DataPage(QWidget):
    """Choose a data source, inspect it, and edit an internal snapshot."""

    dataset_accepted = Signal(object)
    import_requested = Signal(str)
    paste_requested = Signal()

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._catalogs.subscribe(self._locale_changed)
        self._issues: tuple[Issue, ...] = ()
        self.title = QLabel()
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)

        self.excel_button = QPushButton()
        self.delimited_button = QPushButton()
        self.paste_button = QPushButton()
        self.manual_button = QPushButton()
        self.source_help = QLabel()
        self.source_help.setWordWrap(True)
        source_layout = QGridLayout()
        source_layout.addWidget(self.excel_button, 0, 0)
        source_layout.addWidget(self.delimited_button, 0, 1)
        source_layout.addWidget(self.paste_button, 1, 0)
        source_layout.addWidget(self.manual_button, 1, 1)

        self.source_label = QLabel()
        self.count_label = QLabel()
        self.search_input = QLineEdit()
        self.add_row_button = QPushButton()
        self.remove_row_button = QPushButton()
        self.add_column_button = QPushButton()
        self.rename_column_button = QPushButton()
        self.remove_column_button = QPushButton()
        self.undo_button = QPushButton()
        self.redo_button = QPushButton()
        toolbar = QHBoxLayout()
        for control in (
            self.add_row_button,
            self.remove_row_button,
            self.add_column_button,
            self.rename_column_button,
            self.remove_column_button,
            self.undo_button,
            self.redo_button,
        ):
            toolbar.addWidget(control)
        toolbar.addStretch(1)
        toolbar.addWidget(self.search_input)

        initial = create_manual_dataset(("Full Name",))
        self.model = DatasetTableModel(initial, catalogs=self._catalogs)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.issue_list = QListWidget()
        self.continue_button = QPushButton()
        self.continue_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.explanation)
        layout.addLayout(source_layout)
        layout.addWidget(self.source_help)
        summary = QHBoxLayout()
        summary.addWidget(self.source_label)
        summary.addStretch(1)
        summary.addWidget(self.count_label)
        layout.addLayout(summary)
        layout.addLayout(toolbar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.issue_list)
        layout.addWidget(self.continue_button)

        self.excel_button.clicked.connect(lambda: self.import_requested.emit("excel"))
        self.delimited_button.clicked.connect(
            lambda: self.import_requested.emit("delimited")
        )
        self.paste_button.clicked.connect(self.paste_requested)
        self.manual_button.clicked.connect(lambda: self.import_requested.emit("manual"))
        self.search_input.textChanged.connect(self.model.set_filter)
        self.add_row_button.clicked.connect(self._add_row)
        self.remove_row_button.clicked.connect(self._remove_selected_rows)
        self.add_column_button.clicked.connect(self._add_column)
        self.rename_column_button.clicked.connect(self._rename_current_column)
        self.remove_column_button.clicked.connect(self._remove_current_column)
        self.undo_button.clicked.connect(self.model.undo_stack.undo)
        self.redo_button.clicked.connect(self.model.undo_stack.redo)
        self.model.undo_stack.canUndoChanged.connect(self.undo_button.setEnabled)
        self.model.undo_stack.canRedoChanged.connect(self.redo_button.setEnabled)
        self.model.dataset_changed.connect(self._dataset_changed)
        self.issue_list.itemActivated.connect(self._issue_item_activated)
        self.continue_button.clicked.connect(
            lambda: self.dataset_accepted.emit(self.model.dataset)
        )
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self.retranslate()
        self._dataset_changed(initial)

    def set_dataset(self, dataset: TabularDataset) -> None:
        self.model.replace_dataset(dataset)
        self._dataset_changed(dataset)

    def set_issues(self, issues: tuple[Issue, ...]) -> None:
        self._issues = tuple(issues)
        self.model.set_issues(issues)
        self.issue_list.clear()
        for issue in issues:
            item = QListWidgetItem(
                self._catalogs.text(issue.code, **dict(issue.parameters))
            )
            item.setData(Qt.ItemDataRole.UserRole, (issue.row_id, issue.column_id))
            self.issue_list.addItem(item)

    def focus_cell(self, row_id: str, column_id: str) -> None:
        self.model.set_filter("")
        self.search_input.clear()
        index = self.model.index_for_ids(row_id, column_id)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index)
        self.table.setFocus()

    def current_cell_ids(self) -> tuple[str, str] | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return (
            self.model.row_id_at(index.row()),
            self.model.column_id_at(index.column()),
        )

    def retranslate(self) -> None:
        text_by_control = (
            (self.excel_button, "import.excel"),
            (self.delimited_button, "import.csv"),
            (self.paste_button, "import.clipboard"),
            (self.manual_button, "import.manual"),
            (self.add_row_button, "data.add_row"),
            (self.remove_row_button, "data.remove_row"),
            (self.add_column_button, "data.add_column"),
            (self.rename_column_button, "data.rename_column"),
            (self.remove_column_button, "data.remove_column"),
            (self.undo_button, "data.undo"),
            (self.redo_button, "data.redo"),
            (self.continue_button, "action.continue"),
        )
        self.title.setText(self._catalogs.text("data.title"))
        self.explanation.setText(self._catalogs.text("data.explanation"))
        self.source_help.setText(self._catalogs.text("data.source_help"))
        for control, key in text_by_control:
            translated = self._catalogs.text(key)
            control.setText(translated)
            control.setAccessibleName(translated)
        self.search_input.setPlaceholderText(self._catalogs.text("data.search"))
        self.search_input.setAccessibleName(self._catalogs.text("data.search"))
        self.table.setAccessibleName(self._catalogs.text("data.table"))
        self.issue_list.setAccessibleName(
            self._catalogs.text("accessibility.issue_list")
        )
        if self._issues:
            self.set_issues(self._issues)
        self._dataset_changed(self.model.dataset)

    def _dataset_changed(self, dataset: TabularDataset) -> None:
        self.source_label.setText(dataset.source.label)
        self.count_label.setText(
            self._catalogs.text(
                "data.counts",
                rows=len(dataset.rows),
                columns=len(dataset.columns),
            )
        )
        self.continue_button.setEnabled(bool(dataset.rows and dataset.columns))

    def _add_row(self) -> None:
        self.model.insert_rows(len(self.model.dataset.order), 1)

    def _remove_selected_rows(self) -> None:
        row_ids = tuple(
            dict.fromkeys(
                self.model.row_id_at(index.row())
                for index in self.table.selectionModel().selectedIndexes()
            )
        )
        if row_ids:
            self.model.remove_rows(row_ids)

    def _add_column(self) -> None:
        number = len(self.model.dataset.columns) + 1
        label = self._catalogs.text("data.new_column", number=number)
        self.model.insert_column(number - 1, label)

    def _remove_current_column(self) -> None:
        index = self.table.currentIndex()
        if index.isValid():
            try:
                self.model.remove_column(self.model.column_id_at(index.column()))
            except DatasetError:
                return

    def _rename_current_column(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        column_id = self.model.column_id_at(index.column())
        current_label = self.model.dataset.columns[index.column()].label
        label, accepted = QInputDialog.getText(
            self,
            self._catalogs.text("data.rename_column"),
            self._catalogs.text("data.rename_column_prompt"),
            text=current_label,
        )
        if not accepted or label.strip() == current_label:
            return
        try:
            self.model.rename_column(column_id, label)
        except DatasetError as error:
            code = error.args[0] if error.args else "dataset.blank_column"
            self.issue_list.clear()
            self.issue_list.addItem(self._catalogs.text(str(code)))

    def _issue_item_activated(self, item: QListWidgetItem) -> None:
        location = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(location, (tuple, list)) or len(location) != 2:
            return
        row_id, column_id = location
        if row_id and column_id:
            self.focus_cell(row_id, column_id)
            self.model.activate_issue(row_id, column_id)

    def _locale_changed(self, _locale: str) -> None:
        self.retranslate()
