"""Final operator review of the exact batch proposed for publication."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from certificate_automation.approval import ApprovalInput, ApprovalService, WorkflowApproval
from certificate_automation.i18n import CatalogSet


class ApprovalPage(QWidget):
    freeze_requested = Signal(str, bool)
    two_person_mode_changed = Signal(bool)
    review_requested = Signal(str)
    review_previews_requested = Signal()
    generate_requested = Signal()

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._inputs: ApprovalInput | None = None
        self._approval: WorkflowApproval | None = None
        self._acknowledged = False
        self._allow_review = False
        self._reviewer_previews_reviewed = False
        self.title = QLabel()
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.acknowledgement_label = QLabel()
        self.acknowledgement_label.setWordWrap(True)
        self.preparer_name = QLineEdit()
        self.two_person = QCheckBox()
        self.freeze_button = QPushButton()
        self.review_previews_button = QPushButton()
        self.reviewer_name = QLineEdit()
        self.review_button = QPushButton()
        self.review_status = QLabel()
        self.review_status.setWordWrap(True)
        self.generate_button = QPushButton()
        self.generate_button.setProperty("role", "primary")
        layout = QVBoxLayout(self)
        for control in (
            self.title, self.explanation, self.summary_label, self.acknowledgement_label,
            self.preparer_name, self.two_person, self.freeze_button, self.reviewer_name,
            self.review_previews_button, self.review_button, self.review_status, self.generate_button,
        ):
            layout.addWidget(control)
        layout.addStretch(1)
        self.preparer_name.textChanged.connect(self._refresh)
        self.reviewer_name.textChanged.connect(self._refresh)
        self.two_person.toggled.connect(self.two_person_mode_changed)
        self.freeze_button.clicked.connect(lambda: self.freeze_requested.emit(
            self.preparer_name.text(), self.two_person.isChecked()
        ))
        self.review_button.clicked.connect(lambda: self.review_requested.emit(self.reviewer_name.text()))
        self.review_previews_button.clicked.connect(self.review_previews_requested)
        self.generate_button.clicked.connect(self.generate_requested)
        catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_summary(self, inputs: ApprovalInput, *, warnings_acknowledged: bool,
                    reviewer_previews_reviewed: bool = False) -> None:
        self._inputs = inputs
        self._acknowledged = warnings_acknowledged
        self._reviewer_previews_reviewed = reviewer_previews_reviewed
        self._render_summary()
        self._refresh()

    def set_approval(self, approval: WorkflowApproval | None, *, allow_review: bool = False) -> None:
        changed = approval != self._approval
        self._approval = approval
        self._allow_review = allow_review
        if approval and changed:
            self.preparer_name.setText(approval.preparer_name)
            previous = self.two_person.blockSignals(True)
            try:
                self.two_person.setChecked(approval.two_person)
            finally:
                self.two_person.blockSignals(previous)
            self.reviewer_name.setText(approval.reviewer_name or "")
        self._refresh()

    def clear(self) -> None:
        self._inputs = None
        self._approval = None
        self._allow_review = False
        self._reviewer_previews_reviewed = False
        self._acknowledged = False
        self.summary_label.clear()
        self.preparer_name.clear()
        self.reviewer_name.clear()
        previous = self.two_person.blockSignals(True)
        try:
            self.two_person.setChecked(False)
        finally:
            self.two_person.blockSignals(previous)
        self._refresh()

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("approval.title"))
        self.explanation.setText(self._catalogs.text("approval.explanation"))
        self.preparer_name.setPlaceholderText(self._catalogs.text("approval.preparer_name"))
        self.preparer_name.setAccessibleName(self._catalogs.text("approval.preparer_name"))
        self.reviewer_name.setPlaceholderText(self._catalogs.text("approval.reviewer_name"))
        self.reviewer_name.setAccessibleName(self._catalogs.text("approval.reviewer_name"))
        for control, key in (
            (self.two_person, "approval.two_person"),
            (self.freeze_button, "approval.freeze"),
            (self.review_previews_button, "approval.review_previews"),
            (self.review_button, "approval.review"),
            (self.generate_button, "approval.generate"),
        ):
            control.setText(self._catalogs.text(key))
            control.setAccessibleName(control.text())
        self._render_summary()
        self._refresh()

    def _render_summary(self) -> None:
        inputs = self._inputs
        if inputs is None:
            return
        count = inputs.output_counts
        summary = self._catalogs.text(
            "approval.summary",
            recipients=inputs.recipient_count,
            excluded=inputs.excluded_count,
            template=inputs.template_name,
            template_hash=inputs.template_sha256,
            docx=count.get("docx", 0),
            pdf=count.get("pdf", 0),
            combined=count.get("combined", 0),
            separator=count.get("separator", 0),
            manifest=count.get("manifest", 0),
            report=count.get("report", 0),
            warnings=len(inputs.warning_codes),
            previews=len(inputs.preview_hashes),
            pages=inputs.expected_pages,
            destination=inputs.destination,
            revision_folder=inputs.proposed_revision_folder,
            word=self._catalogs.text("approval.word_yes" if inputs.word_available else "approval.word_no"),
            converter=inputs.converter_identity,
            mapping=len(inputs.mapping),
            print_settings=str(dict(inputs.print_settings)),
        )
        self.summary_label.setText(summary)
        self.summary_label.setAccessibleName(summary)

    def _refresh(self) -> None:
        inputs = self._inputs
        approval = self._approval
        self.acknowledgement_label.setText(self._catalogs.text(
            "approval.warnings_acknowledged" if self._acknowledged else "approval.warnings_unacknowledged"
        ))
        self.freeze_button.setEnabled(bool(inputs and self._acknowledged and self.preparer_name.text().strip()))
        reviewer = self.reviewer_name.text().strip()
        self.review_previews_button.setEnabled(bool(
            inputs and approval and approval.two_person and self._allow_review
        ))
        can_review = bool(
            inputs and approval and approval.two_person and self._allow_review
            and approval.snapshot == ApprovalService.snapshot(inputs, two_person=approval.two_person)
            and reviewer and reviewer.casefold() != approval.preparer_name.casefold()
            and self._acknowledged and self._reviewer_previews_reviewed
        )
        self.review_button.setEnabled(can_review)
        verified = ApprovalService.verify(approval, inputs) if inputs else None
        self.generate_button.setEnabled(bool(self._acknowledged and verified and verified.valid))
        if approval is None:
            key = "approval.awaiting_freeze"
        elif verified and verified.valid:
            key = "approval.ready"
        elif approval.two_person and not self._allow_review:
            key = "approval.reopen_for_review"
        elif approval.two_person:
            key = "approval.awaiting_reviewer"
        else:
            key = "approval.stale"
        self.review_status.setText(self._catalogs.text(key))
