from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from certificate_automation.app import ApplicationServices
from certificate_automation.domain import (
    BatchResult,
    BatchState,
    Issue,
    Recipient,
    Severity,
)
from certificate_automation.mapping import MappingSelection, suggest_mappings
from certificate_automation.template import Placeholder, TemplateInspection
from certificate_automation.ui.main_window import MainWindow
from certificate_automation.validation import ValidationReport
from certificate_automation.workbook import WorkbookData


class FakeBatchGenerator:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.calls = 0

    def generate(self, request, progress=None, cancellation=None):
        self.calls += 1
        if progress is not None:
            progress(type("Event", (), {"current": 1, "total": 1, "message": "Done"})())
        return BatchResult(BatchState.PUBLISHED, self.output_dir, 1)


def _services(tmp_path, *, issues=()):
    workbook = WorkbookData(
        path=tmp_path / "students.xlsx",
        sheet_name="Students",
        headers=("full_name", "award"),
        display_headers={"full_name": "Full Name", "award": "Award"},
        recipients=(Recipient(2, {"full_name": "Ana", "award": "Gold"}),),
    )
    template = TemplateInspection(
        path=tmp_path / "certificate.docx",
        placeholders=(
            Placeholder("FULL_NAME", 1, ("word/document.xml",)),
            Placeholder("AWARD", 1, ("word/document.xml",)),
        ),
    )
    report = ValidationReport(tuple(issues), {2: "Ana"}, 1024)
    opened = []
    preview = tmp_path / "PREVIEW_Ana.pdf"
    preview.write_bytes(b"preview")
    generator = FakeBatchGenerator(tmp_path / "published")
    return ApplicationServices(
        list_worksheets=lambda path: ("Students",),
        load_workbook=lambda path, sheet: workbook,
        inspect_template=lambda path: template,
        suggest_mappings=suggest_mappings,
        validate=lambda workbook, template, mappings, destination: report,
        preview=lambda workbook, template, mappings: preview,
        batch_generator=generator,
        open_path=lambda path: opened.append(Path(path)) or True,
        confirm_generation=lambda parent: True,
    ), opened, generator


def _select_valid_files(window, tmp_path):
    window.files_page.workbook_input.setText(str(tmp_path / "students.xlsx"))
    window.files_page.template_input.setText(str(tmp_path / "certificate.docx"))
    window.files_page.destination_input.setText(str(tmp_path / "output"))
    window.files_page.set_worksheets(("Students",))


def _advance_to_validation(qtbot, window, tmp_path):
    _select_valid_files(window, tmp_path)
    qtbot.mouseClick(window.files_page.continue_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page is window.mapping_page)
    qtbot.waitUntil(lambda: window.active_thread is None)
    qtbot.mouseClick(window.mapping_page.continue_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page is window.validation_page)
    qtbot.waitUntil(lambda: window.active_thread is None)


def test_user_can_select_map_and_validate_in_guided_order(qtbot, tmp_path):
    services, _, _ = _services(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)

    _advance_to_validation(qtbot, window, tmp_path)

    assert window.mapping_page.selection().columns == {
        "FULL_NAME": "full_name",
        "AWARD": "award",
    }
    assert window.validation_page.generate_allowed is True
    assert window.validation_page.preview_button.isEnabled()
    assert window.validation_page.generate_button.isEnabled()


def test_errors_are_visible_and_disable_preview_and_generation(qtbot, tmp_path):
    issue = Issue(
        Severity.ERROR,
        "workbook",
        "Row 2 is missing the recipient name.",
        code="blank_mapped_value",
        row_number=2,
    )
    services, _, _ = _services(tmp_path, issues=(issue,))
    window = MainWindow(services)
    qtbot.addWidget(window)

    _advance_to_validation(qtbot, window, tmp_path)

    assert "Row 2 is missing" in window.validation_page.issue_text.toPlainText()
    assert window.validation_page.generate_allowed is False
    assert not window.validation_page.preview_button.isEnabled()
    assert not window.validation_page.generate_button.isEnabled()


def test_preview_runs_in_worker_and_opens_verified_file(qtbot, tmp_path):
    services, opened, _ = _services(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)
    _advance_to_validation(qtbot, window, tmp_path)

    qtbot.mouseClick(window.validation_page.preview_button, Qt.LeftButton)

    qtbot.waitUntil(lambda: bool(opened))
    qtbot.waitUntil(lambda: window.active_thread is None)
    assert opened == [tmp_path / "PREVIEW_Ana.pdf"]
    assert window.current_page is window.preview_page
    assert "opened" in window.preview_page.status_label.text().casefold()


def test_generation_shows_progress_and_success_without_duplicate_start(qtbot, tmp_path):
    services, _, generator = _services(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)
    _advance_to_validation(qtbot, window, tmp_path)

    qtbot.mouseClick(window.validation_page.generate_button, Qt.LeftButton)

    qtbot.waitUntil(lambda: window.generation_page.result is not None)
    qtbot.waitUntil(lambda: window.active_thread is None)
    assert generator.calls == 1
    assert window.current_page is window.generation_page
    assert window.generation_page.result.state is BatchState.PUBLISHED
    assert "success" in window.generation_page.status_label.text().casefold()


def test_mapping_allows_fixed_value_instead_of_excel_column(qtbot, tmp_path):
    services, _, _ = _services(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)
    _select_valid_files(window, tmp_path)
    qtbot.mouseClick(window.files_page.continue_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.current_page is window.mapping_page)
    qtbot.waitUntil(lambda: window.active_thread is None)

    award_row = window.mapping_page.rows["AWARD"]
    award_row.column_combo.setCurrentIndex(0)
    award_row.fixed_input.setText("Institutional Excellence Award")

    selection = window.mapping_page.selection()
    assert selection == MappingSelection(
        columns={"FULL_NAME": "full_name", "AWARD": None},
        fixed_values={"AWARD": "Institutional Excellence Award"},
    )
    assert window.mapping_page.continue_button.isEnabled()
