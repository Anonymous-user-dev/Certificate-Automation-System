"""Application composition and Windows desktop entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from certificate_automation.batch import BatchGenerator
from certificate_automation.filenames import safe_stem
from certificate_automation.mapping import MappingSelection, suggest_mappings
from certificate_automation.recovery import RecoveryService
from certificate_automation.template import (
    TemplateInspection,
    inspect_template,
    render_template,
)
from certificate_automation.validation import ValidationReport, validate_preflight
from certificate_automation.verification import verify_docx, verify_pdf
from certificate_automation.word import WordPdfConverter
from certificate_automation.workbook import (
    WorkbookData,
    list_worksheets,
    load_workbook_data,
)


class PreviewGenerator:
    """Create one verified, explicitly temporary preview artifact."""

    def __init__(self, converter, root: Path | None = None) -> None:
        self._converter = converter
        self._root = root or Path(tempfile.gettempdir()) / "certificate-automation-previews"

    def generate(
        self,
        workbook: WorkbookData,
        template: TemplateInspection,
        mappings: MappingSelection,
    ) -> Path:
        if not workbook.recipients:
            raise ValueError("The workbook has no recipient available for preview.")
        if self._root.exists():
            shutil.rmtree(self._root)
        self._root.mkdir(parents=True)
        recipient = workbook.recipients[0]
        replacement_name = mappings.replacements_for(recipient).get("FULL_NAME", "")
        stem = safe_stem(replacement_name or f"row-{recipient.source_row}")
        docx_path = self._root / f"PREVIEW_{stem}.docx"
        pdf_path = self._root / f"PREVIEW_{stem}.pdf"
        render_template(template.path, docx_path, mappings.replacements_for(recipient))
        verify_docx(docx_path, set(template.names))
        self._converter.convert(docx_path, pdf_path)
        verify_pdf(pdf_path)
        return pdf_path


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    list_worksheets: Callable[[Path], tuple[str, ...]]
    load_workbook: Callable[[Path, str], WorkbookData]
    inspect_template: Callable[[Path], TemplateInspection]
    suggest_mappings: Callable[[tuple[str, ...], tuple[str, ...]], MappingSelection]
    validate: Callable[
        [WorkbookData, TemplateInspection, MappingSelection, Path],
        ValidationReport,
    ]
    preview: Callable[[WorkbookData, TemplateInspection, MappingSelection], Path]
    batch_generator: BatchGenerator
    open_path: Callable[[Path], bool]
    confirm_generation: Callable[[QWidget], bool]
    recovery: RecoveryService
    confirm_recovery_removal: Callable[[QWidget, object], bool]


def create_default_services() -> ApplicationServices:
    converter = WordPdfConverter()
    preview_generator = PreviewGenerator(converter)
    return ApplicationServices(
        list_worksheets=list_worksheets,
        load_workbook=load_workbook_data,
        inspect_template=inspect_template,
        suggest_mappings=suggest_mappings,
        validate=validate_preflight,
        preview=preview_generator.generate,
        batch_generator=BatchGenerator(converter),
        open_path=lambda path: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(path).resolve()))
        ),
        confirm_generation=lambda parent: QMessageBox.question(
            parent,
            "Generate official certificates?",
            "The complete batch will be generated as Word and PDF files. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes,
        recovery=RecoveryService(),
        confirm_recovery_removal=lambda parent, record: QMessageBox.question(
            parent,
            "Remove incomplete batch?",
            (
                f"Remove the incomplete diagnostic batch '{record.batch_id}'? "
                "This does not affect any published certificate batch."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes,
    )


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setOrganizationName("Certificate Automation")
    application.setApplicationName("Certificate Automation")
    from certificate_automation.ui.main_window import MainWindow

    window = MainWindow(create_default_services())
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(250, application.quit)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
