from __future__ import annotations

from pathlib import Path
import time

from PySide6.QtCore import Qt
import pytest

from certificate_automation.app import ApplicationServices
from certificate_automation.domain import BatchResult, BatchState, Recipient
from certificate_automation.mapping import MappingSelection
from certificate_automation.recovery import DraftProjectBackup, IncompleteBatch, RecoveryService
from certificate_automation.template import Placeholder, TemplateInspection
from certificate_automation.ui.main_window import MainWindow
from certificate_automation.validation import ValidationReport
from certificate_automation.word import Availability
from certificate_automation.workbook import WorkbookData


class CancellableGenerator:
    def is_available(self):
        return Availability(True, "available")

    def generate(self, request, progress=None, cancellation=None):
        while not cancellation.requested:
            time.sleep(0.01)
        return BatchResult(BatchState.CANCELLED)


def _running_services(tmp_path):
    workbook = WorkbookData(
        tmp_path / "students.xlsx",
        "Students",
        ("full_name",),
        {"full_name": "Full Name"},
        (Recipient(2, {"full_name": "Ana"}),),
    )
    template = TemplateInspection(
        tmp_path / "template.docx",
        (Placeholder("FULL_NAME", 1, ("word/document.xml",)),),
    )
    mappings = MappingSelection({"FULL_NAME": "full_name"})
    recovery = RecoveryService()
    services = ApplicationServices(
        list_worksheets=lambda path: ("Students",),
        load_workbook=lambda path, sheet: workbook,
        inspect_template=lambda path: template,
        suggest_mappings=lambda headers, placeholders: mappings,
        validate=lambda *args: ValidationReport((), {2: "Ana"}, 1024),
        preview=lambda *args: tmp_path / "preview.pdf",
        batch_generator=CancellableGenerator(),
        open_path=lambda path: True,
        confirm_generation=lambda parent: True,
        recovery=recovery,
        confirm_recovery_removal=lambda parent, record: True,
    )
    return services, workbook, template, mappings


def test_close_during_generation_requests_safe_cancel(qtbot, tmp_path):
    services, workbook, template, mappings = _running_services(tmp_path)
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    window.workbook = workbook
    window.template = template
    window.mappings = mappings
    window.files_page.destination_input.setText(str(tmp_path / "output"))
    window._generate_batch()
    qtbot.waitUntil(lambda: window.active_thread is not None)

    window.close()

    assert window.cancellation.requested is True
    assert window.isVisible() is True
    qtbot.waitUntil(lambda: window.active_thread is None)
    qtbot.waitUntil(lambda: not window.isVisible())


def test_recovery_finds_only_incomplete_batch_directories(tmp_path):
    incomplete = tmp_path / ".certificate-incomplete-example"
    incomplete.mkdir()
    diagnostic = incomplete / "diagnostic.json"
    diagnostic.write_text('{"status": "incomplete"}', encoding="utf-8")
    (tmp_path / ".certificate-staging-active").mkdir()
    (tmp_path / "Certificate Batch successful").mkdir()

    records = RecoveryService().find_incomplete(tmp_path)

    assert records == (
        IncompleteBatch("example", incomplete, diagnostic),
    )


def test_recovery_returns_empty_for_missing_destination(tmp_path):
    assert RecoveryService().find_incomplete(tmp_path / "missing") == ()


def test_recovery_removes_only_exact_incomplete_directory(tmp_path):
    incomplete = tmp_path / ".certificate-incomplete-example"
    incomplete.mkdir()
    diagnostic = incomplete / "diagnostic.json"
    diagnostic.write_text("{}", encoding="utf-8")
    record = IncompleteBatch("example", incomplete, diagnostic)

    RecoveryService().remove(record)

    assert not incomplete.exists()
    assert tmp_path.exists()


def test_recovery_refuses_to_remove_non_incomplete_directory(tmp_path):
    ordinary = tmp_path / "important-documents"
    ordinary.mkdir()
    record = IncompleteBatch("fake", ordinary, ordinary / "diagnostic.json")

    try:
        RecoveryService().remove(record)
    except ValueError as error:
        assert "incomplete batch" in str(error)
    else:
        raise AssertionError("ordinary directory was accepted for removal")
    assert ordinary.exists()


def test_recovery_refuses_diagnostic_outside_incomplete_directory(tmp_path):
    incomplete = tmp_path / ".certificate-incomplete-example"
    incomplete.mkdir()
    outside = tmp_path / "diagnostic.json"
    outside.write_text("{}", encoding="utf-8")
    record = IncompleteBatch("example", incomplete, outside)

    with pytest.raises(ValueError, match="outside"):
        RecoveryService().remove(record)

    assert incomplete.exists()


def test_project_backups_are_discovered_separately_from_incomplete_batches(tmp_path):
    project = tmp_path / "awards.certproject"
    project.write_bytes(b"project")
    newest = tmp_path / "awards.certproject.bak1"
    older = tmp_path / "awards.certproject.bak2"
    newest.write_bytes(b"backup-1")
    older.write_bytes(b"backup-2")
    incomplete = tmp_path / ".certificate-incomplete-example"
    incomplete.mkdir()
    (incomplete / "diagnostic.json").write_text("{}", encoding="utf-8")

    service = RecoveryService()

    assert service.find_project_backups(tmp_path) == (
        DraftProjectBackup(project, newest, 1),
        DraftProjectBackup(project, older, 2),
    )
    assert len(service.find_incomplete(tmp_path)) == 1


def test_destination_selection_shows_recovery_actions(qtbot, tmp_path):
    services, _, _, _ = _running_services(tmp_path)
    incomplete = tmp_path / ".certificate-incomplete-example"
    incomplete.mkdir()
    (incomplete / "diagnostic.json").write_text("{}", encoding="utf-8")
    window = MainWindow(services)
    qtbot.addWidget(window)

    window.files_page.destination_input.setText(str(tmp_path))
    window.files_page.destination_selected.emit(str(tmp_path))

    assert window.files_page.recovery_panel.isVisibleTo(window.files_page)
    assert "example" in window.files_page.recovery_label.text()
    qtbot.mouseClick(window.files_page.remove_recovery_button, Qt.LeftButton)
    assert not incomplete.exists()
