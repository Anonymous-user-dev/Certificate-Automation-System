"""Human-readable validation result page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.validation import ValidationReport


class ValidationPage(QWidget):
    back_requested = Signal()
    preview_requested = Signal()
    generate_requested = Signal()

    def __init__(self, parent=None, *, catalogs: CatalogSet | None = None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs or CatalogSet.load(package_root())
        self._catalogs.subscribe(self._locale_changed)
        self._report: ValidationReport | None = None
        self.title_label = QLabel()
        self.summary_label = QLabel()
        self.issue_text = QTextEdit()
        self.issue_text.setReadOnly(True)
        self.back_button = QPushButton()
        self.preview_button = QPushButton()
        self.generate_button = QPushButton()
        self.preview_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.issue_text)
        layout.addWidget(self.back_button)
        layout.addWidget(self.preview_button)
        layout.addWidget(self.generate_button)
        self.back_button.clicked.connect(self.back_requested)
        self.preview_button.clicked.connect(self.preview_requested)
        self.generate_button.clicked.connect(self.generate_requested)
        self.retranslate()

    @property
    def generate_allowed(self) -> bool:
        return self._report is not None and self._report.ready

    def set_report(self, report: ValidationReport) -> None:
        self._report = report
        errors = sum(issue.blocking for issue in report.issues)
        warnings = len(report.issues) - errors
        if report.ready:
            self.summary_label.setText(
                self._catalogs.text("review.ready", warnings=warnings)
            )
        else:
            self.summary_label.setText(
                self._catalogs.text("review.blocked", errors=errors)
            )
        lines = []
        for issue in report.issues:
            marker_key = "severity.error" if issue.blocking else "severity.warning"
            marker = self._catalogs.text(marker_key)
            message = self._catalogs.text(issue.code, **dict(issue.parameters))
            lines.append(f"{marker}: {message}")
        self.issue_text.setPlainText(
            "\n".join(lines) or self._catalogs.text("review.no_issues")
        )
        self.preview_button.setEnabled(report.ready)
        self.generate_button.setEnabled(report.ready)

    def retranslate(self) -> None:
        self.setWindowTitle(self._catalogs.text("nav.review"))
        self.title_label.setText(self._catalogs.text("nav.review"))
        self.issue_text.setAccessibleName(
            self._catalogs.text("accessibility.issue_list")
        )
        self.back_button.setText(self._catalogs.text("action.back"))
        self.preview_button.setText(self._catalogs.text("action.preview"))
        self.generate_button.setText(self._catalogs.text("action.generate"))
        if self._report is None:
            self.summary_label.setText(self._catalogs.text("review.no_issues"))
        else:
            self.set_report(self._report)

    def _locale_changed(self, _locale: str) -> None:
        self.retranslate()
