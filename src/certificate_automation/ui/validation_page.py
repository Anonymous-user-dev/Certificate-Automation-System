"""Human-readable validation result page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from certificate_automation.validation import ValidationReport


class ValidationPage(QWidget):
    back_requested = Signal()
    preview_requested = Signal()
    generate_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._report: ValidationReport | None = None
        self.summary_label = QLabel("Validation has not run yet.")
        self.issue_text = QTextEdit()
        self.issue_text.setReadOnly(True)
        self.issue_text.setAccessibleName("Validation issues")
        self.back_button = QPushButton("Back to mapping")
        self.preview_button = QPushButton("Generate one preview")
        self.generate_button = QPushButton("Generate official batch")
        self.preview_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Validation results"))
        layout.addWidget(self.summary_label)
        layout.addWidget(self.issue_text)
        layout.addWidget(self.back_button)
        layout.addWidget(self.preview_button)
        layout.addWidget(self.generate_button)
        self.back_button.clicked.connect(self.back_requested)
        self.preview_button.clicked.connect(self.preview_requested)
        self.generate_button.clicked.connect(self.generate_requested)

    @property
    def generate_allowed(self) -> bool:
        return self._report is not None and self._report.ready

    def set_report(self, report: ValidationReport) -> None:
        self._report = report
        errors = sum(issue.blocking for issue in report.issues)
        warnings = len(report.issues) - errors
        if report.ready:
            self.summary_label.setText(
                f"Ready to generate. {warnings} warning(s), no blocking errors."
            )
        else:
            self.summary_label.setText(
                f"Generation is blocked by {errors} error(s)."
            )
        lines = []
        for issue in report.issues:
            marker = "ERROR" if issue.blocking else "WARNING"
            lines.append(f"{marker}: {issue.message}")
        self.issue_text.setPlainText("\n".join(lines) or "No issues found.")
        self.preview_button.setEnabled(report.ready)
        self.generate_button.setEnabled(report.ready)

