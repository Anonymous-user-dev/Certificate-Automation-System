"""Application composition and Windows desktop entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import os
from hashlib import sha256
import shutil
import sys
import tempfile

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from certificate_automation.batch import BatchGenerator
from certificate_automation.filenames import safe_stem
from certificate_automation.i18n import CatalogSet, package_root, validate_catalogs
from certificate_automation.importers.clipboard import (
    create_manual_dataset,
    import_clipboard,
    inspect_clipboard,
)
from certificate_automation.importers.delimited import import_delimited, inspect_delimited
from certificate_automation.importers.excel import import_excel, inspect_excel
from certificate_automation.mapping import MappingSelection, suggest_mappings
from certificate_automation.project import ProjectState, ProjectStore
from certificate_automation.project import ProjectStore
from certificate_automation.preview import PreviewService
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


class ExampleProjectError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def create_example_project(example_root: Path, destination: Path) -> Path:
    """Copy installed samples to an empty working folder and create a draft."""

    example_root, destination = Path(example_root), Path(destination)
    required = ("sample_recipients.csv", "sample_certificate_template.docx", "sample_students.xlsx")
    if not example_root.is_dir() or any(
        not (example_root / name).is_file() or (example_root / name).is_symlink()
        for name in required
    ):
        raise ExampleProjectError("example.source_missing")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ExampleProjectError("example.destination_not_empty")
    if destination.resolve() == example_root.resolve() or example_root.resolve() in destination.resolve().parents:
        raise ExampleProjectError("example.destination_not_empty")
    stage: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
        for name in required:
            shutil.copy2(example_root / name, stage / name)
        from certificate_automation.importers.delimited import import_delimited

        dataset = import_delimited(stage / "sample_recipients.csv", "utf-8", ",")
        dataset = replace(dataset, source=replace(
            dataset.source, path=destination / "sample_recipients.csv"
        ))
        template = stage / "sample_certificate_template.docx"
        project = destination / "Example.certproject"
        ProjectStore.create(stage / project.name).save(ProjectState(
            revision=0,
            dataset=dataset,
            template_path=destination / template.name,
            template_sha256=sha256(template.read_bytes()).hexdigest(),
            project_name="Example",
        ))
        if destination.exists():
            destination.rmdir()
        os.replace(stage, destination)
    except Exception as error:
        raise ExampleProjectError("example.copy_failed") from error
    finally:
        if stage is not None and stage.is_dir():
            shutil.rmtree(stage)
    return project


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
    catalogs: CatalogSet | None = None
    inspect_excel: Callable | None = None
    import_excel: Callable | None = None
    inspect_delimited: Callable | None = None
    import_delimited: Callable | None = None
    inspect_clipboard: Callable | None = None
    import_clipboard: Callable | None = None
    create_manual_dataset: Callable | None = None
    open_project: Callable[[Path], ProjectStore] | None = None
    word_availability: Callable | None = None
    preview_service: PreviewService | None = None
    create_example: Callable[[Path], Path] | None = None
    example_root: Path | None = None


def create_default_services(locale: str = "en") -> ApplicationServices:
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
        catalogs=CatalogSet.load(package_root(), locale),
        inspect_excel=inspect_excel,
        import_excel=import_excel,
        inspect_delimited=inspect_delimited,
        import_delimited=import_delimited,
        inspect_clipboard=inspect_clipboard,
        import_clipboard=import_clipboard,
        create_manual_dataset=create_manual_dataset,
        open_project=ProjectStore.open,
        word_availability=converter.is_available,
        preview_service=PreviewService(converter),
        create_example=lambda destination: create_example_project(
            package_root().parent.parent / "examples", destination
        ),
        example_root=package_root().parent.parent / "examples",
    )


def main() -> int:
    if "--smoke-test" in sys.argv:
        exit_code = 2 if validate_catalogs(package_root()) else 0
        create_default_services("en")
        os._exit(exit_code)
    application = QApplication.instance() or QApplication(sys.argv)
    application.setOrganizationName("Certificate Automation")
    application.setApplicationName("Certificate Automation")
    settings = QSettings()
    locale = str(settings.value("locale", "en"))
    from certificate_automation.ui.workspace import WorkspaceWindow

    window = WorkspaceWindow(create_default_services(locale), settings=settings)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
