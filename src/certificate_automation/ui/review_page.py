"""Recipient-by-recipient resolved-value review page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from certificate_automation.dataset import TabularDataset
from certificate_automation.domain import Issue
from certificate_automation.i18n import CatalogSet
from certificate_automation.mapping import MappingPlan, evaluate_plan
from certificate_automation.history import DuplicatePolicy


class ReviewPage(QWidget):
    issue_activated = Signal(str, str)
    warnings_acknowledged = Signal()
    review_accepted = Signal()
    preview_requested = Signal(str)
    policy_changed = Signal(object)

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._dataset: TabularDataset | None = None
        self._plan: MappingPlan | None = None
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.recipient_selector = QComboBox()
        self.values_table = QTableWidget(0, 2)
        self.preview_button = QPushButton()
        self.preview_status = QLabel()
        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setMinimumHeight(260)
        self.issue_list = QListWidget()
        self.duplicates_help = QLabel()
        self.duplicates_help.setWordWrap(True)
        self.identity_label = QLabel()
        self.identity_columns = QListWidget()
        self.identity_columns.setMaximumHeight(110)
        self.certificate_id_label = QLabel()
        self.certificate_id_combo = QComboBox()
        self.check_history = QCheckBox()
        self._loading_policy = False
        self.acknowledge_button = QPushButton()
        self.continue_button = QPushButton()
        self.continue_button.setProperty("role", "primary")
        layout = QVBoxLayout(self)
        for widget in (
            self.title,
            self.recipient_selector,
            self.values_table,
            self.preview_button,
            self.preview_status,
            self.pdf_view,
            self.issue_list,
            self.duplicates_help,
            self.identity_label,
            self.identity_columns,
            self.certificate_id_label,
            self.certificate_id_combo,
            self.check_history,
            self.acknowledge_button,
            self.continue_button,
        ):
            layout.addWidget(widget)
        self.recipient_selector.currentIndexChanged.connect(self._show_recipient)
        self.acknowledge_button.clicked.connect(self.acknowledge_warnings)
        self.continue_button.clicked.connect(self.review_accepted)
        self.preview_button.clicked.connect(self._request_preview)
        self.identity_columns.itemChanged.connect(self._emit_policy)
        self.certificate_id_combo.currentIndexChanged.connect(self._emit_policy)
        self.check_history.toggled.connect(self._emit_policy)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_context(self, dataset: TabularDataset, plan: MappingPlan) -> None:
        self._dataset, self._plan = dataset, plan
        self._loading_policy = True
        self.identity_columns.clear()
        self.certificate_id_combo.clear()
        self.certificate_id_combo.addItem(self._catalogs.text("review.no_certificate_id"), None)
        for column in dataset.columns:
            item = QListWidgetItem(column.label)
            item.setData(Qt.ItemDataRole.UserRole, column.column_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.identity_columns.addItem(item)
            self.certificate_id_combo.addItem(column.label, column.column_id)
        self._loading_policy = False
        self.recipient_selector.clear()
        for row_id in dataset.order:
            row = dataset.row(row_id)
            label = next(iter(row.values.values()), row_id) or row_id
            self.recipient_selector.addItem(label, row_id)
        self._show_recipient()

    def clear_context(self) -> None:
        self._dataset = None
        self._plan = None
        self.recipient_selector.clear()
        self._loading_policy = True
        self.identity_columns.clear()
        self.certificate_id_combo.clear()
        self.check_history.setChecked(False)
        self._loading_policy = False
        self.values_table.setRowCount(0)
        self.set_issues(())
        self.clear_preview()

    def set_issues(self, issues: tuple[Issue, ...]) -> None:
        self.issue_list.clear()
        for issue in issues:
            self.issue_list.addItem(self._catalogs.text(issue.code, **dict(issue.parameters)))

    def select_recipient(self, row_id: str) -> None:
        index = self.recipient_selector.findData(row_id)
        if index >= 0:
            self.recipient_selector.setCurrentIndex(index)

    def activate_issue(self, row_id: str, column_id: str) -> None:
        self.issue_activated.emit(row_id, column_id)

    def acknowledge_warnings(self) -> None:
        self.warnings_acknowledged.emit()

    def policy(self) -> DuplicatePolicy:
        selected = tuple(
            self.identity_columns.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.identity_columns.count())
            if self.identity_columns.item(index).checkState() == Qt.CheckState.Checked
        )
        return DuplicatePolicy(
            self.certificate_id_combo.currentData(), selected,
            self.check_history.isChecked(),
        )

    def set_policy(self, policy: DuplicatePolicy) -> None:
        self._loading_policy = True
        for index in range(self.identity_columns.count()):
            item = self.identity_columns.item(index)
            item.setCheckState(
                Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in policy.identity_columns
                else Qt.CheckState.Unchecked
            )
        selected = self.certificate_id_combo.findData(policy.certificate_id_column)
        self.certificate_id_combo.setCurrentIndex(max(selected, 0))
        self.check_history.setChecked(policy.check_history)
        self._loading_policy = False

    def _emit_policy(self, *_args: object) -> None:
        if not self._loading_policy:
            self.policy_changed.emit(self.policy())

    def set_preview(self, path) -> None:
        self.pdf_document.load(str(path))
        self.preview_status.setText(str(path.name))

    def clear_preview(self) -> None:
        """Release the current Windows file handle before replacing a preview."""

        self.pdf_document.close()
        self.preview_status.clear()

    def show_preview_error(self, message: str) -> None:
        self.preview_status.setText(message)

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("review.title"))
        self.duplicates_help.setText(self._catalogs.text("review.duplicates_help"))
        self.identity_label.setText(self._catalogs.text("review.identity_columns"))
        self.certificate_id_label.setText(self._catalogs.text("review.certificate_id"))
        self.check_history.setText(self._catalogs.text("review.check_history"))
        if self.certificate_id_combo.count():
            self.certificate_id_combo.setItemText(0, self._catalogs.text("review.no_certificate_id"))
        self.identity_columns.setAccessibleName(self.identity_label.text())
        self.certificate_id_combo.setAccessibleName(self.certificate_id_label.text())
        self.recipient_selector.setAccessibleName(self._catalogs.text("review.recipient"))
        self.values_table.setAccessibleName(self._catalogs.text("review.resolved_values"))
        self.issue_list.setAccessibleName(self._catalogs.text("accessibility.issue_list"))
        self.acknowledge_button.setText(self._catalogs.text("review.acknowledge"))
        self.preview_button.setText(self._catalogs.text("review.preview"))
        self.continue_button.setText(self._catalogs.text("action.continue"))
        self.acknowledge_button.setAccessibleName(self.acknowledge_button.text())
        self.preview_button.setAccessibleName(self.preview_button.text())
        self.continue_button.setAccessibleName(self.continue_button.text())

    def _show_recipient(self) -> None:
        if self._dataset is None or self._plan is None:
            return
        row_id = self.recipient_selector.currentData()
        if not row_id:
            return
        values = evaluate_plan(self._plan, self._dataset, str(row_id))
        self.values_table.setRowCount(len(values))
        for index, (placeholder, value) in enumerate(values.items()):
            self.values_table.setItem(index, 0, QTableWidgetItem(placeholder))
            self.values_table.setItem(index, 1, QTableWidgetItem(value))

    def _request_preview(self) -> None:
        row_id = self.recipient_selector.currentData()
        if row_id:
            self.preview_requested.emit(str(row_id))
