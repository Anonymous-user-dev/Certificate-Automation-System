"""Operator-facing template structure and representative layout review."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from certificate_automation.domain import Severity
from certificate_automation.i18n import CatalogSet
from certificate_automation.template_health import LayoutReviewResult, TemplateHealthReport


class TemplateHealthPage(QWidget):
    mapping_requested = Signal()
    render_requested = Signal(int)
    review_accepted = Signal(str)

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._structure: TemplateHealthReport | None = None
        self._layout: LayoutReviewResult | None = None
        self._visited: set[str] = set()
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.limitation = QLabel()
        self.limitation.setWordWrap(True)
        self.must_fix_heading = QLabel()
        self.must_fix_list = QListWidget()
        self.review_heading = QLabel()
        self.review_list = QListWidget()
        self.information_heading = QLabel()
        self.information_list = QListWidget()
        self.continue_button = QPushButton()
        self.continue_button.setProperty("role", "primary")
        self.expected_pages_label = QLabel()
        self.expected_pages = QSpinBox()
        self.expected_pages.setRange(1, 100)
        self.expected_pages.setValue(1)
        self.render_button = QPushButton()
        self.preview_selector = QComboBox()
        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setMinimumHeight(260)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        self.mark_reviewed_button = QPushButton()
        self.mark_reviewed_button.setProperty("role", "primary")
        self.mark_reviewed_button.setEnabled(False)

        layout = QVBoxLayout(self)
        for widget in (
            self.title, self.explanation, self.must_fix_heading, self.must_fix_list,
            self.review_heading, self.review_list, self.information_heading,
            self.information_list, self.limitation, self.continue_button,
        ):
            layout.addWidget(widget)
        controls = QHBoxLayout()
        controls.addWidget(self.expected_pages_label)
        controls.addWidget(self.expected_pages)
        controls.addWidget(self.render_button)
        layout.addLayout(controls)
        layout.addWidget(self.preview_selector)
        layout.addWidget(self.preview_status)
        layout.addWidget(self.pdf_view)
        layout.addWidget(self.mark_reviewed_button)
        self.continue_button.clicked.connect(self.mapping_requested)
        self.render_button.clicked.connect(lambda: self.render_requested.emit(self.expected_pages.value()))
        self.preview_selector.currentIndexChanged.connect(self._show_selected_preview)
        self.mark_reviewed_button.clicked.connect(self._accept_review)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    @property
    def layout_result(self) -> LayoutReviewResult | None:
        return self._layout

    def set_structure(self, report: TemplateHealthReport) -> None:
        self._structure = report
        self.clear_layout()
        self._refresh_issues()
        self.continue_button.setEnabled(not report.blocking)

    def clear_structure(self) -> None:
        self._structure = None
        self.clear_layout()
        self._refresh_issues()
        self.continue_button.setEnabled(False)

    def clear_layout(self) -> None:
        self.pdf_document.close()
        self.preview_selector.clear()
        self.preview_status.clear()
        self._layout = None
        self._visited.clear()
        self.mark_reviewed_button.setEnabled(False)
        self._refresh_issues()

    def set_layout_result(self, result: LayoutReviewResult) -> None:
        self.clear_layout()
        self._layout = result
        self.preview_selector.blockSignals(True)
        for representative in result.representatives:
            if any(preview.row_id == representative.row_id for preview in result.previews):
                self.preview_selector.addItem(representative.row_id, representative.row_id)
        self.preview_selector.blockSignals(False)
        self._refresh_issues()
        if result.ready and self.preview_selector.count():
            self._show_selected_preview(0)
        self._update_review_enabled()

    def _show_selected_preview(self, index: int) -> None:
        self.pdf_document.close()
        self.mark_reviewed_button.setEnabled(False)
        if self._layout is None or index < 0:
            return
        row_id = self.preview_selector.itemData(index)
        preview = next((item for item in self._layout.previews if item.row_id == row_id), None)
        if preview is None:
            return
        self.pdf_document.load(str(preview.pdf_path))
        if self.pdf_document.status() == QPdfDocument.Status.Ready and self.pdf_document.pageCount() == preview.page_count:
            self._visited.add(row_id)
            self.preview_status.setText(preview.pdf_path.name)
        else:
            self.preview_status.setText(self._catalogs.text("health.preview_unavailable"))
        self._update_review_enabled()

    def _update_review_enabled(self) -> None:
        result = self._layout
        self.mark_reviewed_button.setEnabled(bool(
            result and result.ready and
            {item.row_id for item in result.representatives} == self._visited
        ))

    def _accept_review(self) -> None:
        if self.mark_reviewed_button.isEnabled() and self._layout is not None:
            self.review_accepted.emit(self._layout.revision_key)

    def _refresh_issues(self) -> None:
        self.must_fix_list.clear()
        self.review_list.clear()
        self.information_list.clear()
        issues = (
            (self._structure.issues if self._structure else ())
            + (self._layout.issues if self._layout else ())
        )
        for issue in issues:
            text = self._catalogs.text(issue.code, **dict(issue.parameters))
            target = (
                self.must_fix_list if issue.severity is Severity.ERROR else
                self.review_list if issue.severity is Severity.WARNING else
                self.information_list
            )
            target.addItem(text)

    def retranslate(self) -> None:
        for widget, key in (
            (self.title, "health.title"),
            (self.explanation, "health.explanation"),
            (self.limitation, "health.limitation"),
            (self.must_fix_heading, "health.must_fix"),
            (self.review_heading, "health.review"),
            (self.information_heading, "health.information"),
            (self.continue_button, "health.continue_to_mapping"),
            (self.expected_pages_label, "health.expected_pages"),
            (self.render_button, "health.render"),
            (self.mark_reviewed_button, "health.mark_reviewed"),
        ):
            widget.setText(self._catalogs.text(key))
        self.expected_pages.setAccessibleName(self.expected_pages_label.text())
        self.preview_selector.setAccessibleName(self._catalogs.text("health.representative"))
        for listing, heading in (
            (self.must_fix_list, self.must_fix_heading),
            (self.review_list, self.review_heading),
            (self.information_list, self.information_heading),
        ):
            listing.setAccessibleName(heading.text())
        for button in (self.continue_button, self.render_button, self.mark_reviewed_button):
            button.setAccessibleName(button.text())
        self._refresh_issues()
