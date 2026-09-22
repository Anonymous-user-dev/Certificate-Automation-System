"""Recipient-by-recipient resolved-value review page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QComboBox, QLabel, QListWidget, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from certificate_automation.dataset import TabularDataset
from certificate_automation.domain import Issue
from certificate_automation.i18n import CatalogSet
from certificate_automation.mapping import MappingPlan, evaluate_plan


class ReviewPage(QWidget):
    issue_activated = Signal(str, str)
    warnings_acknowledged = Signal()
    review_accepted = Signal()
    preview_requested = Signal(str)

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
            self.acknowledge_button,
            self.continue_button,
        ):
            layout.addWidget(widget)
        self.recipient_selector.currentIndexChanged.connect(self._show_recipient)
        self.acknowledge_button.clicked.connect(self.acknowledge_warnings)
        self.continue_button.clicked.connect(self.review_accepted)
        self.preview_button.clicked.connect(self._request_preview)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_context(self, dataset: TabularDataset, plan: MappingPlan) -> None:
        self._dataset, self._plan = dataset, plan
        self.recipient_selector.clear()
        for row_id in dataset.order:
            row = dataset.row(row_id)
            label = next(iter(row.values.values()), row_id) or row_id
            self.recipient_selector.addItem(label, row_id)
        self._show_recipient()

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
