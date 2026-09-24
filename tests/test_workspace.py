from __future__ import annotations

from types import SimpleNamespace
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
import json
import sqlite3
from threading import Event
from pypdf import PdfWriter

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QComboBox, QFileDialog, QLineEdit, QMessageBox, QTableView
import pytest

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.approval import ApprovalService
from certificate_automation.dataset import Column, DataRow, TabularDataset
from certificate_automation.domain import BatchResult, BatchState
from certificate_automation.output_options import OutputOptions
from certificate_automation.print_readiness import PrintReadinessReport, PrintReadinessService, PrintSettings
from certificate_automation.template_health import PageGeometry
from decimal import Decimal
from certificate_automation.mapping import ColumnValue, FixedValue, JoinValue, MappingPlan
from certificate_automation.profiles import MappingProfile, ProfileStore
from certificate_automation.ui.workspace import WorkspaceWindow
from certificate_automation.ui.workspace import SaveState
from certificate_automation.ui.workspace import STEP_IDS
from certificate_automation.project import ProjectCorruptError, ProjectError, ProjectSaveError, ProjectState, ProjectStore
from certificate_automation.validation import ValidationReport
from certificate_automation.word import WordAvailability
from certificate_automation.template import inspect_template
from certificate_automation.template_health import TemplateHealthService
from fixtures import docx_factory


def test_template_health_step_runs_before_mapping_and_returns_for_layout_review(
    workspace, tmp_path, docx_factory
):
    workspace.new_project(tmp_path / "Health.certproject")
    workspace._accept_data(workspace.project_state.dataset)
    workspace.services.inspect_template = inspect_template
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])

    workspace._select_template(template)
    workspace._accept_template(workspace.template_page.inspection)

    assert workspace.current_step == "template_health"
    assert workspace.template_health_page.must_fix_list.count() == 0
    workspace.template_health_page.continue_button.click()
    assert workspace.current_step == "mapping"

    workspace._accept_plan(MappingPlan({"FULL_NAME": ColumnValue("column-1")}))

    assert workspace.current_step == "template_health"
    assert not workspace.template_health_page.mark_reviewed_button.isEnabled()
    workspace.navigate("review")
    assert workspace.current_step == "template_health"
    workspace.navigate("mapping")
    assert workspace.current_step == "mapping"


def test_malformed_word_template_opens_health_repair_step(workspace, tmp_path, docx_factory):
    workspace.new_project(tmp_path / "Malformed.certproject")
    workspace._accept_data(workspace.project_state.dataset)
    workspace.services.inspect_template = inspect_template
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}"]])

    workspace._select_template(template)

    assert workspace.current_step == "template_health"
    assert workspace.template_health_page.must_fix_list.count() >= 1
    assert not workspace.template_health_page.continue_button.isEnabled()


def test_rendered_layout_review_unlocks_review_only_after_pdf_visit(
    workspace, tmp_path, docx_factory
):
    class Converter:
        def convert(self, _source, destination):
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with destination.open("wb") as stream:
                writer.write(stream)

    workspace.template_health_service = TemplateHealthService(Converter(), tmp_path / "layout")
    path = tmp_path / "Layout.certproject"
    workspace.new_project(path)
    workspace._accept_data(workspace.project_state.dataset)
    workspace.services.inspect_template = inspect_template
    workspace._select_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    workspace._accept_template(workspace.template_page.inspection)
    workspace.template_health_page.continue_button.click()
    workspace._accept_plan(MappingPlan({"FULL_NAME": ColumnValue("column-1")}))

    workspace.template_health_page.render_button.click()
    assert workspace.current_step == "template_health"
    assert workspace.template_health_page.mark_reviewed_button.isEnabled()
    workspace.template_health_page.mark_reviewed_button.click()

    assert workspace.current_step == "review"
    assert workspace.coordinator.flush()
    stored = ProjectStore.open(path).load()
    assert stored.layout_review["revision_key"] == workspace._layout_review_key
    assert len(stored.layout_review["preview_hashes"]) == 1


def test_generation_refuses_unreviewed_current_layout(workspace, tmp_path, docx_factory):
    workspace.new_project(tmp_path / "Unreviewed.certproject")
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    plan = MappingPlan({"FULL_NAME": ColumnValue("column-1")})
    workspace.project_state = replace(
        workspace.project_state, template=template, plan=plan,
        outputs=OutputOptions(True, False, False, tmp_path, "Batch", workspace.project_state.dataset.order),
    )

    workspace.start_generation()

    assert workspace.current_step == "template_health"
    assert workspace.banner.issue_code == "template.layout_review_required"
    assert workspace._thread is None


def test_data_revision_invalidates_layout_review(workspace, tmp_path, docx_factory):
    workspace.new_project(tmp_path / "Revision.certproject")
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    plan = MappingPlan({"FULL_NAME": ColumnValue("column-1")})
    workspace.project_state = replace(workspace.project_state, template=template, plan=plan)
    workspace._layout_review_key = TemplateHealthService.revision_key(
        workspace.project_state.dataset, template, plan
    )

    dataset = workspace.project_state.dataset.with_cell("row-1", "column-1", "Changed")
    workspace._data_changed(dataset)

    assert workspace._layout_review_key is None


def test_project_persists_layout_review_binding(workspace, tmp_path, docx_factory):
    path = tmp_path / "Reviewed.certproject"
    workspace.new_project(path)
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    plan = MappingPlan({"FULL_NAME": ColumnValue("column-1")})
    key = TemplateHealthService.revision_key(workspace.project_state.dataset, template, plan)
    workspace.project_state = replace(workspace.project_state, template=template, plan=plan)
    workspace._layout_review_key = key
    workspace._loaded_project = replace(
        workspace._loaded_project,
        template_inspection={"sha256": template.sha256, "names": list(template.names)},
        layout_review={"revision_key": key, "preview_hashes": ["a" * 64]},
    )
    workspace.state = replace(workspace.state, project_revision=workspace.state.project_revision + 1)
    workspace._mark_project_dirty()
    assert workspace.coordinator.flush()

    reopened = ProjectStore.open(path).load()

    assert reopened.layout_review["revision_key"] == key
    assert reopened.layout_review["preview_hashes"] == ["a" * 64]


@pytest.fixture
def workspace(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    services = SimpleNamespace(catalogs=CatalogSet.load(package_root(), "en"))
    window = WorkspaceWindow(services, settings=settings)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def test_home_has_four_clear_primary_actions(workspace):
    assert all(button.isVisible() for button in workspace.home.primary_buttons())


def test_home_history_entry_opens_local_history_and_returns_home(workspace, tmp_path):
    workspace.new_project(tmp_path / "History.certproject")
    workspace._show_home()

    workspace.home.history_button.click()

    assert workspace.root_stack.currentWidget() is workspace.history_page
    workspace.history_page.back_button.click()
    assert workspace.root_stack.currentWidget() is workspace.home


def test_home_support_entry_opens_offline_dialog(workspace, monkeypatch):
    from certificate_automation.ui.support_dialog import SupportDialog
    seen = []
    monkeypatch.setattr(SupportDialog, "exec", lambda self: seen.append(self))

    workspace.home.support_button.click()

    assert len(seen) == 1
    assert not seen[0].include_sensitive.isChecked()


def test_published_result_is_recorded_in_project_history(workspace, tmp_path):
    project_path = tmp_path / "History.certproject"
    workspace.new_project(project_path)
    revision = tmp_path / "Awards-revision-1"
    revision.mkdir()

    workspace._generation_finished(BatchResult(BatchState.PUBLISHED, revision, 1))

    assert str(revision) in workspace._loaded_project.published_revisions
    assert workspace.coordinator.flush()
    assert str(revision) in ProjectStore.open(project_path).load().published_revisions


def test_output_step_opens_final_approval_before_results(workspace, tmp_path):
    workspace.new_project(tmp_path / "Approval.certproject")
    workspace.state = replace(
        workspace.state,
        completed_steps=STEP_IDS[:STEP_IDS.index("output")],
    )
    options = OutputOptions(True, False, False, tmp_path, "Awards", workspace.project_state.dataset.order)

    workspace._accept_outputs(options)

    assert workspace.current_step == "approval"
    assert workspace.page_stack.currentWidget() is workspace.approval_page
    assert not workspace.results_page.generate_button.isEnabled()


def test_generation_without_current_frozen_approval_never_starts(workspace, tmp_path, docx_factory):
    workspace.new_project(tmp_path / "Unapproved.certproject")
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    plan = MappingPlan({"FULL_NAME": ColumnValue("column-1")})
    dataset = workspace.project_state.dataset.with_cell("row-1", "column-1", "Ana")
    workspace.project_state = replace(
        workspace.project_state,
        dataset=dataset, template=template, plan=plan,
        outputs=OutputOptions(True, False, False, tmp_path, "Awards", dataset.order),
    )
    workspace._layout_review_key = TemplateHealthService.revision_key(dataset, template, plan)
    workspace._loaded_project = replace(
        workspace._loaded_project,
        layout_review={"revision_key": workspace._layout_review_key,
                       "preview_hashes": ["a" * 64], "expected_pages": 1},
    )
    workspace.services.validate = lambda *_args: ValidationReport(
        (), {}, 0, dataset.revision, template.sha256,
    )

    workspace.start_generation()

    assert workspace._thread is None
    assert workspace.banner.issue_code == "approval.required"


def _ready_approval_workspace(workspace, tmp_path, docx_factory):
    project_path = tmp_path / "Ready approval.certproject"
    workspace.new_project(project_path)
    dataset = workspace.project_state.dataset.with_cell("row-1", "column-1", "Ana")
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    plan = MappingPlan({"FULL_NAME": ColumnValue("column-1")})
    workspace.project_state = replace(
        workspace.project_state, dataset=dataset, template=template, plan=plan,
    )
    key = TemplateHealthService.revision_key(dataset, template, plan)
    workspace._layout_review_key = key
    workspace._loaded_project = replace(
        workspace._loaded_project,
        dataset=dataset,
        template_path=template.path,
        template_sha256=template.sha256,
        template_inspection={"sha256": template.sha256, "names": ["FULL_NAME"]},
        mapping_plan=plan.to_json(),
        layout_review={"revision_key": key, "preview_hashes": ["a" * 64], "expected_pages": 1},
    )
    workspace.state = replace(
        workspace.state, completed_steps=STEP_IDS[:STEP_IDS.index("output")],
    )
    workspace._accept_outputs(OutputOptions(True, False, False, tmp_path, "Awards", dataset.order))
    return project_path


def test_two_person_freeze_requires_project_reopen_and_survives_disk_roundtrip(
    workspace, tmp_path, docx_factory
):
    path = _ready_approval_workspace(workspace, tmp_path, docx_factory)
    assert workspace.current_step == "approval"
    page = workspace.approval_page
    page.preparer_name.setText("Alice")
    page.two_person.setChecked(True)
    page.freeze_button.click()
    assert not page.review_button.isEnabled()
    assert not page.generate_button.isEnabled()
    assert workspace.coordinator.flush()
    assert ProjectStore.open(path).load().approval["preparer_name"] == "Alice"

    workspace.load_project(path)
    page = workspace.approval_page
    assert workspace.current_step == "approval"
    page.reviewer_name.setText("alice")
    assert not page.review_button.isEnabled()
    page.reviewer_name.setText("Bob")
    assert not page.review_button.isEnabled()
    class Converter:
        def convert(self, _source, destination):
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with destination.open("wb") as stream:
                writer.write(stream)

    workspace.template_health_service = TemplateHealthService(Converter(), tmp_path / "reviewer-previews")
    page.review_previews_button.click()
    assert workspace.current_step == "template_health"
    assert workspace.template_health_page.layout_result.ready
    assert workspace.template_health_page.mark_reviewed_button.isEnabled()
    workspace.template_health_page.mark_reviewed_button.click()
    assert workspace.current_step == "approval"
    assert page.reviewer_name.text() == "Bob"
    assert page._approval.snapshot == ApprovalService.snapshot(page._inputs, two_person=True)
    assert page.review_button.isEnabled()
    page.review_button.click()
    assert page.generate_button.isEnabled()
    assert workspace.coordinator.flush()
    saved = ProjectStore.open(path).load()
    assert saved.approval["reviewer_name"] == "Bob"
    assert saved.approval["snapshot"]["digest"] == workspace._approval.snapshot.digest


def test_output_change_clears_frozen_approval(workspace, tmp_path, docx_factory):
    _ready_approval_workspace(workspace, tmp_path, docx_factory)
    workspace.approval_page.preparer_name.setText("Alice")
    workspace.approval_page.freeze_button.click()
    assert workspace.approval_page.generate_button.isEnabled()

    workspace._accept_outputs(OutputOptions(True, False, False, tmp_path, "Different", workspace.project_state.dataset.order))

    assert workspace._approval is None
    assert workspace._loaded_project.approval is None
    assert not workspace.approval_page.generate_button.isEnabled()


def test_changing_two_person_mode_clears_frozen_approval(workspace, tmp_path, docx_factory):
    _ready_approval_workspace(workspace, tmp_path, docx_factory)
    page = workspace.approval_page
    page.preparer_name.setText("Alice")
    page.freeze_button.click()
    assert page.generate_button.isEnabled()

    page.two_person.setChecked(True)

    assert workspace._approval is None
    assert workspace._loaded_project.approval is None
    assert not page.generate_button.isEnabled()


def test_editing_output_controls_immediately_clears_frozen_approval(workspace, tmp_path, docx_factory):
    _ready_approval_workspace(workspace, tmp_path, docx_factory)
    workspace.approval_page.preparer_name.setText("Alice")
    workspace.approval_page.freeze_button.click()
    workspace.navigate("output")

    workspace.output_page.batch_name.setText("Corrected Awards")

    assert workspace._approval is None
    assert workspace.project_state.outputs is None
    assert workspace._loaded_project.approval is None
    assert not workspace.approval_page.generate_button.isEnabled()


def test_output_page_inherits_template_geometry_and_forecasts_separator_pages(workspace, tmp_path):
    page = workspace.output_page
    assert not page.separator_enabled.isEnabled()
    page.set_order(("row-1", "row-2", "row-3"))
    page.set_template_geometry(PageGeometry(612, 792, "portrait"))
    page.set_expected_pages_per_certificate(2)
    page.combined_pdf.setChecked(True)
    page.separator_enabled.setChecked(True)
    page.separator_every.setValue(2)
    page.destination.setText(str(tmp_path))

    choices = page.options()

    assert choices.print_settings == PrintSettings(Decimal("612"), Decimal("792"), "portrait", 2)
    assert choices.separator_count == 1
    assert "7" in page.page_forecast.text()
    assert page.printing_note.text()
    assert page.print_width_label.text() == workspace.catalogs.text("output.page_width")
    assert page.print_height_label.text() == workspace.catalogs.text("output.page_height")
    assert page.separator_every_label.text() == workspace.catalogs.text("output.separator_every")


def test_changing_print_settings_invalidates_frozen_approval(workspace, tmp_path, docx_factory):
    _ready_approval_workspace(workspace, tmp_path, docx_factory)
    workspace.approval_page.preparer_name.setText("Alice")
    workspace.approval_page.freeze_button.click()
    workspace.navigate("output")
    assert workspace._approval is not None

    workspace.output_page.print_width.setValue(613)

    assert workspace._approval is None
    assert workspace.project_state.outputs is None
    assert workspace._loaded_project.approval is None


def test_editing_accepted_print_choices_requires_accepting_them_again(workspace, tmp_path):
    workspace.new_project(tmp_path / "Print.certproject")
    dataset = workspace.project_state.dataset
    settings = PrintSettings(Decimal("612"), Decimal("792"), "portrait")
    selected = OutputOptions(True, True, True, tmp_path, "Awards", dataset.order, settings)
    workspace._accept_outputs(selected)
    workspace.navigate("output")

    workspace.output_page.print_width.setValue(613)

    assert workspace.project_state.outputs is None
    assert "output" not in workspace.state.completed_steps


def test_results_claim_print_ready_only_with_fresh_report(workspace, tmp_path):
    output = tmp_path / "Awards-revision-1"
    output.mkdir()
    combined = output / "Awards.pdf"
    combined.write_bytes(b"pdf")
    result = BatchResult(BatchState.PUBLISHED, output, 1, combined_pdf_path=combined)

    workspace.results_page.set_published(result)
    assert workspace.catalogs.text("results.print_ready") not in workspace.results_page.status_label.text()

    workspace.results_page.set_published(
        result, readiness=PrintReadinessReport(True, 1, 1, 1, ())
    )
    assert workspace.catalogs.text("results.print_ready") in workspace.results_page.status_label.text()

    workspace.results_page.set_published(
        result, readiness=PrintReadinessReport(False, 1, 1, 1, ())
    )
    assert not workspace.results_page.open_combined_button.isEnabled()


def test_combined_open_uses_verified_manifest_file_even_if_result_path_is_wrong(workspace, tmp_path):
    from test_print_readiness import _revision
    output = _revision(tmp_path)
    wrong = output / "wrong.pdf"
    opened = []
    workspace.services.open_path = lambda path: opened.append(path) or True
    workspace.results_page.set_published(
        BatchResult(BatchState.PUBLISHED, output, 3, combined_pdf_path=wrong)
    )

    workspace._open_combined_output()

    assert opened == [output / "Awards.pdf"]


def test_combined_open_rechecks_published_files_and_removes_stale_ready_claim(workspace, tmp_path):
    from test_print_readiness import _revision
    output = _revision(tmp_path)
    opened = []
    workspace.services.open_path = lambda path: opened.append(path) or True
    workspace.results_page.set_expected_combined(True)
    workspace.results_page.set_published(
        BatchResult(BatchState.PUBLISHED, output, 3, combined_pdf_path=output / "Awards.pdf"),
        readiness=PrintReadinessService().verify(output),
    )
    assert workspace.catalogs.text("results.print_ready") in workspace.results_page.status_label.text()
    (output / "Awards.pdf").write_bytes(b"changed after verification")

    workspace._open_combined_output()

    assert opened == []
    assert not workspace.results_page.open_combined_button.isEnabled()
    assert workspace.catalogs.text("results.print_ready") not in workspace.results_page.status_label.text()


def test_results_export_button_makes_a_verified_copy(workspace, tmp_path, monkeypatch):
    from test_print_readiness import _revision
    output = _revision(tmp_path)
    destination = tmp_path / "removable"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(destination))
    workspace.results_page.set_published(
        BatchResult(BatchState.PUBLISHED, output, 3, combined_pdf_path=output / "Awards.pdf")
    )

    workspace.results_page.export_button.click()

    assert (destination / output.name / "manifest.json").is_file()
    assert "official original" in workspace.results_page.status_label.text()
    assert (output / "manifest.json").is_file()


@pytest.mark.parametrize("locale", ("ru", "zh_CN"))
def test_print_controls_are_translated_and_accessible(workspace, locale):
    workspace.set_locale(locale)
    page = workspace.output_page
    assert page.printing_note.text() == workspace.catalogs.text("output.printing_note")
    assert page.separator_enabled.text() == workspace.catalogs.text("output.separator_enabled")
    assert page.print_width.accessibleName() == workspace.catalogs.text("output.page_width")
    assert page.separator_every.accessibleName() == workspace.catalogs.text("output.separator_every")


def test_changed_import_source_blocks_approved_generation(workspace, tmp_path, docx_factory):
    project_path = _ready_approval_workspace(workspace, tmp_path, docx_factory)
    source = tmp_path / "source.csv"
    source.write_text("Ana", encoding="utf-8")
    dataset = replace(
        workspace.project_state.dataset,
        source=replace(workspace.project_state.dataset.source,
                       path=source, sha256=sha256(source.read_bytes()).hexdigest()),
    )
    key = TemplateHealthService.revision_key(
        dataset, workspace.project_state.template, workspace.project_state.plan
    )
    workspace.project_state = replace(workspace.project_state, dataset=dataset)
    workspace._layout_review_key = key
    workspace._loaded_project = replace(
        workspace._loaded_project, dataset=dataset,
        layout_review={"revision_key": key, "preview_hashes": ["a" * 64], "expected_pages": 1},
    )
    workspace._refresh_approval_page()
    workspace.approval_page.preparer_name.setText("Alice")
    workspace.approval_page.freeze_button.click()
    assert workspace.approval_page.generate_button.isEnabled()

    source.write_text("Changed", encoding="utf-8")
    workspace.start_generation()

    assert workspace._thread is None
    assert workspace.banner.issue_code == "approval.source_changed"
    assert workspace.coordinator.flush()
    workspace.load_project(project_path)
    assert workspace.banner.issue_code == "approval.source_changed"
    assert workspace._approval is None
    assert workspace._loaded_project.approval is None
    assert not workspace.approval_page.generate_button.isEnabled()


def test_new_project_saves_real_edits_and_updates_status(workspace, qtbot, tmp_path):
    path = tmp_path / "Awards.certproject"
    workspace.new_project(path)
    assert path.is_file()
    assert workspace.save_state == SaveState.SAVED
    assert workspace.save_state_label.text() == workspace.catalogs.text("save_state.saved")

    index = workspace.data_page.model.index(0, 0)
    assert workspace.data_page.model.setData(index, "Ada", Qt.ItemDataRole.EditRole)
    assert workspace.save_state == SaveState.SAVING
    qtbot.waitUntil(lambda: workspace.save_state == SaveState.SAVED, timeout=4000)

    loaded = ProjectStore.open(path).load()
    assert loaded.dataset.rows[0].value("column-1") == "Ada"
    assert loaded.schema_version == 2


def test_load_project_reopens_saved_data_and_recent_catalog(workspace, tmp_path):
    path = tmp_path / "Awards.certproject"
    workspace.new_project(path)
    workspace.load_project(path)

    assert workspace.state.project_path == path
    assert workspace.save_state == SaveState.SAVED
    assert any(summary.path == path for summary in workspace.home._projects)


def test_switching_projects_flushes_pending_edit_before_opening_next(workspace, tmp_path):
    first = tmp_path / "First.certproject"
    second = tmp_path / "Second.certproject"
    workspace.new_project(first)
    ProjectStore.create(second).save(ProjectState(0, ProjectStore.open(first).load().dataset))
    index = workspace.data_page.model.index(0, 0)
    workspace.data_page.model.setData(index, "Ada", Qt.ItemDataRole.EditRole)

    workspace.load_project(second)

    assert ProjectStore.open(first).load().dataset.rows[0].value("column-1") == "Ada"
    assert workspace.state.project_path == second
    assert workspace.save_state == SaveState.SAVED


def test_failed_open_keeps_current_project_editable_and_savable(workspace, tmp_path):
    current = tmp_path / "Current.certproject"
    workspace.new_project(current)

    with pytest.raises(ProjectCorruptError):
        workspace.load_project(tmp_path / "missing.certproject")

    assert workspace.state.project_path == current
    workspace.data_page.model.setData(workspace.data_page.model.index(0, 0), "Ada", Qt.ItemDataRole.EditRole)
    assert workspace.coordinator.flush()
    assert ProjectStore.open(current).load().dataset.rows[0].value("column-1") == "Ada"


def test_failed_create_keeps_current_project_editable_and_savable(workspace, tmp_path):
    current = tmp_path / "Current.certproject"
    workspace.new_project(current)
    occupied = tmp_path / "Occupied.certproject"
    occupied.write_text("mine", encoding="utf-8")

    with pytest.raises(ProjectSaveError):
        workspace.new_project(occupied)

    assert workspace.state.project_path == current
    workspace.data_page.model.setData(workspace.data_page.model.index(0, 0), "Ada", Qt.ItemDataRole.EditRole)
    assert workspace.coordinator.flush()
    assert ProjectStore.open(current).load().dataset.rows[0].value("column-1") == "Ada"


def test_locale_change_is_saved_in_project(workspace, tmp_path):
    path = tmp_path / "Languages.certproject"
    workspace.new_project(path)

    workspace.set_locale("ru")
    assert workspace.save_state == SaveState.SAVING
    assert workspace.coordinator.flush()

    assert ProjectStore.open(path).load().locale == "ru"


def test_successful_navigation_persists_exact_active_step(workspace, tmp_path):
    path = tmp_path / "Navigation.certproject"
    workspace.new_project(path)
    workspace.mark_step_complete("data")
    workspace.navigate("template")

    assert workspace.coordinator.flush()
    assert ProjectStore.open(path).load().active_step == "template"
    workspace.load_project(path)
    assert workspace.current_step == "template"


def test_loading_older_project_migrates_and_shows_backup_location(workspace, tmp_path):
    path = tmp_path / "Legacy.certproject"
    workspace.new_project()
    payload = ProjectState(0, workspace.project_state.dataset).to_payload()
    for key in ("schema_version", "project_name", "profile_path", "approval", "published_revisions", "print_settings"):
        payload.pop(key)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '1')")
        connection.execute("CREATE TABLE revisions (revision INTEGER PRIMARY KEY, saved_at TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)")
        connection.execute("INSERT INTO revisions VALUES (0, '2026-09-22T00:00:00+00:00', ?, ?)", (encoded, sha256(encoded.encode()).hexdigest()))

    workspace.load_project(path)

    backup = path.with_name(f"{path.name}.pre-v2-backup")
    assert backup.is_file()
    assert ProjectStore.open(path).load().schema_version == 2
    assert backup.name in workspace.statusBar().currentMessage()


def _saved_with_downstream_state(workspace, path, template_path, tmp_path):
    workspace.new_project(path)
    original = ProjectStore.open(path).load()
    inspection = inspect_template(template_path)
    review_key = TemplateHealthService.revision_key(
        original.dataset, inspection, MappingPlan({"FULL_NAME": ColumnValue("column-1")})
    )
    (tmp_path / "output").mkdir(exist_ok=True)
    stored = replace(
        original,
        revision=5,
        template_path=template_path,
        template_sha256=inspection.sha256,
        template_inspection={"sha256": inspection.sha256, "names": ["FULL_NAME"]},
        layout_review={"revision_key": review_key, "preview_hashes": ["a" * 64]},
        mapping_plan={"FULL_NAME": {"type": "column", "column_id": "column-1"}},
        output_options={
            "docx": True, "individual_pdf": False, "combined_pdf": False,
            "destination": str(tmp_path / "output"), "batch_name": "Awards",
            "row_ids": list(original.dataset.order),
        },
        acknowledgements=("warning-reviewed",),
        approval={"reviewer": "Ada"},
        preview_revision=original.dataset.revision,
        profile_path=tmp_path / "profile.json",
        published_revisions=("published-1",),
        print_settings={"copies": 2},
        active_step="generate",
    )
    ProjectStore.open(path).save(stored)
    workspace.services.inspect_template = inspect_template
    workspace.load_project(path)
    return stored


def test_reopen_navigation_preserves_valid_review_facts_on_disk(
    workspace, tmp_path, docx_factory
):
    path = tmp_path / "Review facts.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    original = _saved_with_downstream_state(workspace, path, template, tmp_path)

    workspace.navigate("output")
    assert workspace.coordinator.flush()
    reopened = ProjectStore.open(path).load()

    assert reopened.acknowledgements == original.acknowledgements
    assert reopened.approval is None  # an unrecognized legacy approval cannot authorize generation
    assert reopened.preview_revision == original.preview_revision
    assert reopened.active_step == "output"


def test_new_project_clears_all_prior_workflow_widgets(
    workspace, tmp_path, docx_factory
):
    first = tmp_path / "First complete.certproject"
    second = tmp_path / "Second empty.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, first, template, tmp_path)
    assert workspace.template_page.inspection is not None
    assert workspace.match_page.cards
    assert workspace.review_page.recipient_selector.count() == 1
    assert workspace.output_page.destination.text()

    workspace.new_project(second)

    assert workspace.current_step == "data"
    assert workspace.project_state.template is None
    assert workspace.project_state.plan is None
    assert workspace.project_state.outputs is None
    assert workspace.template_page.inspection is None
    assert workspace.template_page.placeholder_list.count() == 0
    assert not workspace.template_page.continue_button.isEnabled()
    assert not workspace.match_page.cards
    assert not workspace.match_page.continue_button.isEnabled()
    assert workspace.review_page.recipient_selector.count() == 0
    assert workspace.review_page.values_table.rowCount() == 0
    assert not workspace.review_page.preview_status.text()
    assert not workspace.output_page.destination.text()
    assert not workspace.output_page.continue_button.isEnabled()
    assert not workspace.results_page.generate_button.isEnabled()


@pytest.mark.parametrize("step", ("template", "mapping", "output", "generate"))
def test_reopen_restores_saved_context_and_exact_valid_step(
    workspace, tmp_path, docx_factory, step
):
    path = tmp_path / f"Resume {step}.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    saved = _saved_with_downstream_state(workspace, path, template, tmp_path)
    ProjectStore.open(path).save(replace(saved, revision=6, active_step=step))

    workspace.load_project(path)

    assert workspace.current_step == step
    assert workspace.project_state.template.path == template
    assert workspace.template_page.inspection.path == template
    assert workspace.project_state.plan.to_json() == {"FULL_NAME": {"type": "column", "column_id": "column-1"}}
    assert workspace.match_page.cards["FULL_NAME"].mapping_source().column_id == "column-1"
    assert workspace.review_page.recipient_selector.count() == 1
    assert workspace.project_state.outputs.destination == tmp_path / "output"
    assert workspace.output_page.destination.text() == str(tmp_path / "output")
    assert workspace.output_page.batch_name.text() == "Awards"
    assert workspace.project_state.warning_ack_revision == saved.dataset.revision


def test_reopen_at_mapping_keeps_unresolved_continue_disabled(workspace, tmp_path, docx_factory):
    path = tmp_path / "Unresolved mapping.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    workspace.new_project(path)
    inspection = inspect_template(template)
    saved = replace(
        ProjectStore.open(path).load(), revision=1,
        template_path=template, template_sha256=inspection.sha256,
        template_inspection={"sha256": inspection.sha256, "names": ["FULL_NAME"]},
        active_step="mapping",
    )
    ProjectStore.open(path).save(saved)

    workspace.load_project(path)

    assert workspace.current_step == "mapping"
    assert not workspace.match_page.continue_button.isEnabled()


def test_custom_join_mapping_survives_reopen_navigation_and_save(
    workspace, tmp_path, docx_factory
):
    path = tmp_path / "Custom join.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    workspace.new_project(path)
    initial = ProjectStore.open(path).load()
    dataset = TabularDataset(
        (Column("first", "First"), Column("middle", "Middle"), Column("last", "Last")),
        (DataRow("row-1", None, {"first": "Ada", "middle": "Byron", "last": "Lovelace"}),),
        initial.dataset.source,
    )
    inspection = inspect_template(template)
    stored = replace(
        initial, revision=5, dataset=dataset,
        template_path=template, template_sha256=inspection.sha256,
        template_inspection={"sha256": inspection.sha256, "names": ["FULL_NAME"]},
        mapping_plan={"FULL_NAME": {
            "type": "join", "column_ids": ["last", "first"], "separator": ", "
        }},
        layout_review={"revision_key": TemplateHealthService.revision_key(
            dataset, inspection, MappingPlan({"FULL_NAME": JoinValue(("last", "first"), ", ")})
        ), "preview_hashes": ["a" * 64]},
        active_step="review",
    )
    ProjectStore.open(path).save(stored)

    workspace.load_project(path)

    assert workspace.current_step == "review"
    card = workspace.match_page.cards["FULL_NAME"]
    assert card.mapping_source().column_ids == ("last", "first")
    assert card.mapping_source().separator == ", "
    assert workspace.review_page.values_table.item(0, 1).text() == "Lovelace, Ada"
    card.join_columns.setText("unknown")
    assert not workspace.match_page.continue_button.isEnabled()
    card.join_columns.setText("last, first")
    assert workspace.match_page.continue_button.isEnabled()
    workspace.navigate("mapping")
    workspace.navigate("review")
    assert workspace.coordinator.flush()
    assert ProjectStore.open(path).load().mapping_plan == stored.mapping_plan


@pytest.mark.parametrize("damage", ("missing", "changed"))
def test_reopen_with_untrusted_template_downgrades_and_explains_repair(
    workspace, tmp_path, docx_factory, damage
):
    path = tmp_path / f"Damaged {damage}.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, template, tmp_path)
    if damage == "missing":
        template.unlink()
    else:
        template.write_bytes(b"changed template bytes")

    workspace.load_project(path)

    assert workspace.current_step == "template"
    assert workspace.project_state.template is None
    assert workspace.project_state.plan is None
    assert workspace.project_state.outputs is None
    assert workspace.banner.issue_code == "project.resume_template_repair"
    assert workspace.banner.isVisibleTo(workspace)
    assert workspace.catalogs.text("project.resume_template_repair") in workspace.banner.label.text()


def test_reopen_with_invalid_mapping_downgrades_without_crashing(workspace, tmp_path, docx_factory):
    path = tmp_path / "Invalid mapping.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    saved = _saved_with_downstream_state(workspace, path, template, tmp_path)
    broken = replace(
        saved, revision=6,
        mapping_plan={"FULL_NAME": {"type": "column", "column_id": "absent"}},
    )
    ProjectStore.open(path).save(broken)

    workspace.load_project(path)

    assert workspace.current_step == "mapping"
    assert workspace.project_state.plan is None
    assert workspace.banner.issue_code == "project.resume_mapping_repair"
    assert workspace.banner.isVisibleTo(workspace)


def test_reopen_with_missing_output_folder_downgrades_to_output(workspace, tmp_path, docx_factory):
    path = tmp_path / "Missing output.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, template, tmp_path)
    (tmp_path / "output").rmdir()

    workspace.load_project(path)

    assert workspace.current_step == "output"
    assert workspace.project_state.outputs is None
    assert workspace.banner.issue_code == "project.resume_output_repair"


def test_newer_schema_is_visible_read_only_and_cannot_silently_edit_or_generate(
    workspace, qtbot, tmp_path
):
    path = tmp_path / "Future.certproject"
    workspace.new_project(path)
    before = ProjectStore.open(path).load().dataset.rows[0].value("column-1")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE metadata SET value='3' WHERE key='schema_version'")

    workspace.load_project(path)

    assert workspace.save_state == SaveState.READ_ONLY
    assert workspace.read_only_notice.isVisibleTo(workspace)
    assert workspace.catalogs.text("workspace.read_only_explanation") in workspace.read_only_notice.text()
    index = workspace.data_page.model.index(0, 0)
    assert not (workspace.data_page.model.flags(index) & Qt.ItemFlag.ItemIsEditable)
    assert not workspace.data_page.model.setData(index, "Changed", Qt.ItemDataRole.EditRole)
    assert not workspace.data_page.add_row_button.isEnabled()
    assert not workspace.template_page.choose_button.isEnabled()
    assert not workspace.review_page.acknowledge_button.isEnabled()
    assert not workspace.output_page.destination.isEnabled()
    assert not workspace.results_page.generate_button.isEnabled()
    assert workspace.step_rail.button_for("data").isEnabled()
    workspace.start_generation()
    assert ProjectStore.open(path).load().dataset.rows[0].value("column-1") == before
    assert workspace.coordinator is None
    qtbot.mouseClick(workspace.home_button, Qt.MouseButton.LeftButton)
    assert workspace.root_stack.currentWidget() is workspace.home
    assert workspace.close()


def test_newer_schema_disables_restored_mapping_review_and_output_edits(
    workspace, tmp_path, docx_factory
):
    path = tmp_path / "Future complete.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, template, tmp_path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE metadata SET value='3' WHERE key='schema_version'")

    workspace.load_project(path)

    assert not workspace.match_page.cards["FULL_NAME"].type_combo.isEnabled()
    assert not workspace.match_page.cards["FULL_NAME"].join_columns.isEnabled()
    assert not workspace.match_page.cards["FULL_NAME"].join_separator.isEnabled()
    assert not workspace.match_page.continue_button.isEnabled()
    assert workspace.review_page.values_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert not workspace.review_page.preview_button.isEnabled()
    assert not workspace.output_page.docx.isEnabled()
    assert not workspace.output_page.continue_button.isEnabled()


def test_applying_profile_persists_reference_and_invalidates_review_facts(
    workspace, tmp_path, docx_factory
):
    project_path = tmp_path / "Profile batch.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, project_path, template, tmp_path)
    profile = MappingProfile.from_plan(
        "Awards", MappingPlan({"FULL_NAME": ColumnValue("column-1")}),
        ("FULL_NAME",), workspace.project_state.dataset.columns,
    )
    workspace.profile_store = ProfileStore(tmp_path / "profiles")
    profile_path = workspace.profile_store.save(profile)

    workspace._apply_profile_path(profile_path)
    assert workspace.match_page.cards["FULL_NAME"].mapping_source() == ColumnValue("column-1")
    assert workspace.match_page.comparison_table.rowCount() == 1
    assert workspace.project_state.plan is None
    assert workspace.project_state.outputs is None
    assert workspace.project_state.warning_ack_revision is None
    assert workspace.coordinator.flush()
    saved = ProjectStore.open(project_path).load()
    assert saved.profile_path == profile_path
    assert saved.mapping_plan is None
    assert saved.approval is None
    assert saved.preview_revision is None
    assert saved.acknowledgements == ()


def test_read_only_project_disables_profile_mutations(workspace, tmp_path, docx_factory):
    path = tmp_path / "Future profile.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, template, tmp_path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE metadata SET value='3' WHERE key='schema_version'")
    workspace.load_project(path)
    assert not workspace.match_page.save_profile_button.isEnabled()
    assert not workspace.match_page.apply_profile_button.isEnabled()


def test_profile_applies_output_defaults_without_recipient_order_or_destination(
    workspace, tmp_path, docx_factory
):
    path = tmp_path / "Defaults.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, template, tmp_path)
    profile = MappingProfile.from_plan(
        "Defaults", MappingPlan({"FULL_NAME": ColumnValue("column-1")}),
        ("FULL_NAME",), workspace.project_state.dataset.columns,
        defaults={"docx": False, "individual_pdf": True, "combined_pdf": True, "batch_name": "Awards"},
    )
    workspace.profile_store = ProfileStore(tmp_path / "profiles")
    profile_path = workspace.profile_store.save(profile)
    workspace.output_page.destination.clear()
    workspace.output_page.batch_name.clear()
    workspace._apply_profile_path(profile_path)
    assert not workspace.output_page.docx.isChecked()
    assert workspace.output_page.individual_pdf.isChecked()
    assert workspace.output_page.combined_pdf.isChecked()
    assert workspace.output_page.batch_name.text() == "Awards"
    assert not workspace.output_page.destination.text()
    assert "row_ids" not in profile_path.read_text(encoding="utf-8")


def test_profile_outside_configured_folder_is_rejected_without_changing_batch(
    workspace, tmp_path, docx_factory
):
    project_path = tmp_path / "Restricted.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    original = _saved_with_downstream_state(workspace, project_path, template, tmp_path)
    workspace.profile_store = ProfileStore(tmp_path / "trusted-profiles")
    outside_profile = MappingProfile.from_plan(
        "Outside", MappingPlan({"FULL_NAME": FixedValue("Wrong name")}),
        ("FULL_NAME",), workspace.project_state.dataset.columns,
    )
    outside_path = ProfileStore(tmp_path / "outside").save(
        outside_profile, allow_fixed_values=True
    )
    prior_plan = workspace.project_state.plan
    prior_outputs = workspace.project_state.outputs
    prior_step = workspace.current_step
    prior_completed = workspace.state.completed_steps

    workspace._apply_profile_path(outside_path)

    assert workspace.banner.issue_code == "profile.path_outside_store"
    assert workspace.current_step == prior_step
    assert workspace.state.completed_steps == prior_completed
    assert workspace.project_state.plan == prior_plan
    assert workspace.project_state.outputs == prior_outputs
    assert workspace.project_state.warning_ack_revision == original.dataset.revision
    assert workspace.match_page.cards["FULL_NAME"].mapping_source() == ColumnValue("column-1")
    assert workspace.coordinator.flush()
    saved = ProjectStore.open(project_path).load()
    assert saved.profile_path == original.profile_path
    assert saved.mapping_plan == original.mapping_plan
    assert saved.approval == original.approval
    assert saved.preview_revision == original.preview_revision
    assert saved.acknowledgements == original.acknowledgements
    assert saved.output_options == original.output_options


def test_profile_from_different_template_warns_but_exact_fields_still_apply(
    workspace, tmp_path, docx_factory
):
    project_path = tmp_path / "Template changed.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, project_path, template, tmp_path)
    workspace.profile_store = ProfileStore(tmp_path / "profiles")
    profile = MappingProfile.from_plan(
        "Older", MappingPlan({"FULL_NAME": ColumnValue("column-1")}),
        ("FULL_NAME",), workspace.project_state.dataset.columns,
        template_sha256="a" * 64,
    )
    profile_path = workspace.profile_store.save(profile)

    workspace._apply_profile_path(profile_path)

    assert workspace.banner.issue_code == "profile.template_changed"
    assert workspace.match_page.cards["FULL_NAME"].mapping_source() == ColumnValue("column-1")
    assert workspace.match_page.comparison_table.rowCount() == 1


def test_saving_profile_with_fixed_text_requires_explicit_ui_confirmation(
    workspace, tmp_path, docx_factory, monkeypatch
):
    path = tmp_path / "Private profile.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, template, tmp_path)
    workspace.profile_store = ProfileStore(tmp_path / "profiles")
    workspace.match_page.cards["FULL_NAME"].set_mapping_source(FixedValue("Private text"))
    monkeypatch.setattr("certificate_automation.ui.workspace.QInputDialog.getText", lambda *args: ("Private", True))
    monkeypatch.setattr("certificate_automation.ui.workspace.QMessageBox.question", lambda *args: QMessageBox.StandardButton.No)
    workspace.match_page.save_profile_button.click()
    assert workspace.profile_store.list() == ()
    monkeypatch.setattr("certificate_automation.ui.workspace.QMessageBox.question", lambda *args: QMessageBox.StandardButton.Yes)
    workspace.match_page.save_profile_button.click()
    assert len(workspace.profile_store.list()) == 1


def test_data_edit_clears_downstream_approval_and_preview_but_preserves_independent_fields(
    workspace, tmp_path, docx_factory
):
    path = tmp_path / "Data change.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    original = _saved_with_downstream_state(workspace, path, template, tmp_path)

    workspace.data_page.model.setData(workspace.data_page.model.index(0, 0), "Ada", Qt.ItemDataRole.EditRole)
    assert workspace.coordinator.flush()
    saved = ProjectStore.open(path).load()

    assert saved.mapping_plan is None
    assert saved.output_options is None
    assert saved.acknowledgements == ()
    assert saved.approval is None
    assert saved.preview_revision is None
    assert saved.template_inspection == original.template_inspection
    assert saved.profile_path == original.profile_path
    assert saved.published_revisions == original.published_revisions
    assert saved.print_settings == original.print_settings


def test_template_selection_clears_prior_inspection_mapping_and_approval(
    workspace, tmp_path, docx_factory
):
    path = tmp_path / "Template change.certproject"
    old_template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, path, old_template, tmp_path)
    new_template = docx_factory(paragraph_runs=[["{{AWARD}}"]])

    workspace._select_template(new_template)
    assert workspace.coordinator.flush()
    saved = ProjectStore.open(path).load()

    assert saved.template_path == new_template
    assert saved.template_inspection is None
    assert saved.mapping_plan is None
    assert saved.output_options is None
    assert saved.acknowledgements == ()
    assert saved.approval is None
    assert saved.preview_revision is None


def test_failed_autosave_retry_succeeds_after_store_is_repaired(workspace, qtbot, tmp_path):
    path = tmp_path / "Retry.certproject"
    workspace.new_project(path)
    path.unlink()
    workspace.data_page.model.setData(workspace.data_page.model.index(0, 0), "Ada", Qt.ItemDataRole.EditRole)
    assert not workspace.coordinator.flush()

    try:
        assert workspace.retry_save_button.isVisible()
        assert workspace.retry_save_button.accessibleName() == workspace.catalogs.text("save_state.retry")
        ProjectStore.create(path)
        qtbot.mouseClick(workspace.retry_save_button, Qt.MouseButton.LeftButton)

        assert workspace.save_state == SaveState.SAVED
        assert not workspace.coordinator.has_pending
        assert not workspace.retry_save_button.isVisible()
        assert ProjectStore.open(path).load().dataset.rows[0].value("column-1") == "Ada"
    finally:
        workspace.coordinator._timer.stop()
        workspace.coordinator._pending = None


def test_failed_autosave_retry_again_keeps_pending_revision(workspace, qtbot, tmp_path):
    path = tmp_path / "Still failing.certproject"
    workspace.new_project(path)
    path.unlink()
    workspace.data_page.model.setData(workspace.data_page.model.index(0, 0), "Ada", Qt.ItemDataRole.EditRole)
    assert not workspace.coordinator.flush()

    try:
        qtbot.mouseClick(workspace.retry_save_button, Qt.MouseButton.LeftButton)

        assert workspace.save_state == SaveState.FAILED
        assert workspace.retry_save_button.isVisible()
        assert workspace.coordinator.has_pending
    finally:
        workspace.coordinator._timer.stop()
        workspace.coordinator._pending = None


def test_failed_save_can_retry_and_return_from_home(workspace, qtbot, tmp_path):
    path = tmp_path / "Home retry.certproject"
    workspace.new_project(path)
    path.unlink()
    workspace.data_page.model.setData(
        workspace.data_page.model.index(0, 0), "Ada", Qt.ItemDataRole.EditRole
    )
    assert not workspace.coordinator.flush()

    try:
        qtbot.mouseClick(workspace.home_button, Qt.MouseButton.LeftButton)
        assert workspace.root_stack.currentWidget() is workspace.home
        assert workspace.home.retry_save_button.isVisibleTo(workspace)
        assert workspace.home.retry_save_button.accessibleName() == workspace.catalogs.text("save_state.retry")
        assert workspace.home.return_to_project_button.isVisibleTo(workspace)
        qtbot.mouseClick(workspace.home.retry_save_button, Qt.MouseButton.LeftButton)
        assert workspace.save_state == SaveState.FAILED
        assert workspace.coordinator.has_pending
        assert workspace.home.retry_save_button.isVisibleTo(workspace)

        ProjectStore.create(path)
        qtbot.mouseClick(workspace.home.retry_save_button, Qt.MouseButton.LeftButton)
        assert workspace.save_state == SaveState.SAVED
        assert not workspace.coordinator.has_pending
        assert not workspace.home.retry_save_button.isVisibleTo(workspace)
        assert ProjectStore.open(path).load().dataset.rows[0].value("column-1") == "Ada"
        qtbot.mouseClick(workspace.home.return_to_project_button, Qt.MouseButton.LeftButton)
        assert workspace.root_stack.currentWidget() is workspace.workspace_surface
    finally:
        workspace.coordinator._timer.stop()
        workspace.coordinator._pending = None


def test_language_switch_retranslates_without_losing_edits(workspace):
    workspace.new_project()
    index = workspace.data_page.model.index(0, 0)
    assert workspace.data_page.model.setData(index, "Li Ming", Qt.ItemDataRole.EditRole)

    workspace.set_locale("zh_CN")

    assert workspace.step_rail.text_for("data") == "收件人数据"
    assert workspace.data_page.model.dataset.rows[0].value("column-1") == "Li Ming"
    assert workspace.locale_selector.currentData() == "zh_CN"


def test_blocked_step_explains_required_action(workspace):
    workspace.new_project()

    workspace.navigate("review")

    assert workspace.current_step == "data"
    assert workspace.banner.issue_code == "navigation.complete_data_first"
    assert workspace.banner.isVisibleTo(workspace)


def test_step_navigation_unlocks_only_completed_predecessors(workspace):
    workspace.new_project()
    workspace.mark_step_complete("data")

    workspace.navigate("template")

    assert workspace.current_step == "template"


def test_every_interactive_control_has_accessible_name(workspace):
    interactive = (QAbstractButton, QComboBox, QLineEdit, QTableView)
    missing = [
        widget
        for widget_type in interactive
        for widget in workspace.findChildren(widget_type)
        if not widget.accessibleName().strip()
    ]

    assert missing == []


def test_narrow_window_keeps_full_step_names_for_accessibility(workspace):
    workspace.resize(620, 700)

    assert workspace.step_rail.is_compact is True
    assert workspace.step_rail.button_for("mapping").accessibleName() == "Match Fields"


def test_expanded_russian_step_rail_has_room_for_translated_labels(workspace):
    workspace.set_locale("ru")
    workspace.resize(1280, 800)

    assert workspace.step_rail.is_compact is False
    assert workspace.step_rail.width() >= 280
    for step in ("data", "template", "mapping", "review", "output", "generate"):
        button = workspace.step_rail.button_for(step)
        assert button.fontMetrics().horizontalAdvance(button.text()) <= button.contentsRect().width()


def test_default_batch_name_retranslates_without_overwriting_operator_edit(workspace):
    assert workspace.output_page.batch_name.text() == "Certificate Batch"

    workspace.set_locale("zh_CN")
    assert workspace.output_page.batch_name.text() == "证书批次"

    workspace.output_page.batch_name.setText("2026 Scholarship Awards")
    workspace.set_locale("ru")
    assert workspace.output_page.batch_name.text() == "2026 Scholarship Awards"


def test_output_defaults_to_word_and_individual_pdf_with_plain_count_summary(workspace):
    page = workspace.output_page
    page.set_order(("row-1", "row-2", "row-3"))

    assert page.docx.isChecked()
    assert page.individual_pdf.isChecked()
    assert not page.combined_pdf.isChecked()
    assert "3 Word" in page.summary_label.text()
    assert "3 individual PDF" in page.summary_label.text()
    assert "0 combined PDF" in page.summary_label.text()

    page.combined_pdf.setChecked(True)
    assert "1 combined PDF" in page.summary_label.text()


def test_unavailable_word_clears_pdf_choices_and_explains_why(workspace):
    page = workspace.output_page
    page.combined_pdf.setChecked(True)
    workspace.set_locale("ru")

    page.set_word_availability(
        WordAvailability(
            False,
            "Desktop Microsoft Word is not installed or damaged.",
            "word.not_available",
        )
    )

    assert not page.individual_pdf.isChecked()
    assert not page.combined_pdf.isChecked()
    assert not page.individual_pdf.isEnabled()
    assert "настольная версия microsoft word" in page.word_status.text().casefold()
    assert "not installed or damaged" not in page.word_status.text()


def test_results_enable_combined_action_only_for_exact_combined_artifact(
    workspace, tmp_path
):
    output = tmp_path / "published"
    output.mkdir()
    (output / "Ana.pdf").write_bytes(b"individual")

    workspace.results_page.set_published(
        BatchResult(BatchState.PUBLISHED, output, 1)
    )
    assert not workspace.results_page.open_combined_button.isEnabled()

    combined = output / "Print Batch.pdf"
    combined.write_bytes(b"combined")
    workspace.results_page.set_published(
        BatchResult(
            BatchState.PUBLISHED,
            output,
            1,
            combined_pdf_path=combined,
        )
    )
    assert workspace.results_page.open_combined_button.isEnabled()


@pytest.mark.parametrize("switch", ("new", "open"))
def test_project_switch_clears_prior_published_result_and_open_actions(
    workspace, tmp_path, switch
):
    first = tmp_path / "Published.certproject"
    second = tmp_path / "Empty.certproject"
    workspace.new_project(first)
    if switch == "open":
        ProjectStore.create(second).save(ProjectState(0, workspace.project_state.dataset))
    output = tmp_path / "published"
    output.mkdir()
    combined = output / "Awards.pdf"
    combined.write_bytes(b"pdf")
    (output / "batch_summary.html").write_text("summary", encoding="utf-8")
    opened = []
    workspace.services.open_path = lambda path: opened.append(path) or True
    workspace.results_page.set_failed(RuntimeError("previous error"))
    workspace.results_page.set_expected_combined(True)
    workspace.results_page.set_published(
        BatchResult(BatchState.PUBLISHED, output, 1, combined_pdf_path=combined)
    )

    if switch == "new":
        workspace.new_project(second)
    else:
        workspace.load_project(second)

    assert workspace.results_page.state == "ready"
    assert workspace.results_page.result is None
    assert workspace.results_page.error is None
    assert workspace.results_page._expected_combined is False
    assert workspace.results_page.status_label.text() == ""
    assert not workspace.results_page.open_combined_button.isEnabled()
    workspace._open_published_output()
    workspace._open_combined_output()
    workspace._open_result_file("batch_summary.html")
    assert opened == []


def test_active_generation_blocks_all_project_switch_routes_and_finishes_in_origin(
    workspace, qtbot, tmp_path, docx_factory, monkeypatch
):
    first = tmp_path / "Generating.certproject"
    second = tmp_path / "Another.certproject"
    template = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    _saved_with_downstream_state(workspace, first, template, tmp_path)
    ProjectStore.create(second).save(ProjectState(0, workspace.project_state.dataset))
    started = Event()
    release = Event()
    output = tmp_path / "generated-by-first"
    output.mkdir()

    class WaitingGenerator:
        def generate(self, request, progress=None, cancellation=None):
            started.set()
            if not release.wait(5):
                raise RuntimeError("test generator timed out")
            return BatchResult(BatchState.PUBLISHED, output, 1)

    workspace.services.validate = lambda dataset, template, plan, options: ValidationReport(
        (), {}, 0, dataset.revision, template.sha256
    )
    workspace.services.batch_generator = WaitingGenerator()
    reviewed_dataset = workspace.project_state.dataset.with_cell("row-1", "column-1", "Ana")
    workspace.project_state = replace(workspace.project_state, dataset=reviewed_dataset)
    workspace._layout_review_key = TemplateHealthService.revision_key(
        reviewed_dataset, workspace.project_state.template, workspace.project_state.plan
    )
    workspace._loaded_project = replace(
        workspace._loaded_project,
        layout_review={"revision_key": workspace._layout_review_key,
                       "preview_hashes": ["a" * 64], "expected_pages": 1},
    )
    workspace._approval = ApprovalService.freeze(
        workspace._current_approval_input(workspace.services.validate(
            reviewed_dataset, workspace.project_state.template,
            workspace.project_state.plan, workspace.project_state.outputs,
        )), "Ada",
    )
    workspace.start_generation()
    qtbot.waitUntil(started.is_set, timeout=3000)
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QFileDialog.getOpenFileName",
        lambda *_args: pytest.fail("project dialog opened during generation"),
    )
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QFileDialog.getSaveFileName",
        lambda *_args: pytest.fail("project dialog opened during generation"),
    )
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QFileDialog.getExistingDirectory",
        lambda *_args: pytest.fail("project dialog opened during generation"),
    )
    try:
        with pytest.raises(ProjectError, match="generation.project_switch_blocked"):
            workspace.new_project(tmp_path / "Unwanted.certproject")
        with pytest.raises(ProjectError, match="generation.project_switch_blocked"):
            workspace.load_project(second)
        workspace._show_home()
        for action in (
            workspace._create_project_from_home,
            workspace._open_project_dialog,
            lambda: workspace._open_recent_project(second),
            lambda: workspace._repair_recent_project(second),
            workspace._try_example,
            workspace._recover_draft,
        ):
            action()
        assert workspace.root_stack.currentWidget() is workspace.workspace_surface
        assert workspace.state.project_path == first
        assert workspace.banner.issue_code == "generation.project_switch_blocked"
        assert not (tmp_path / "Unwanted.certproject").exists()
    finally:
        release.set()
        qtbot.waitUntil(lambda: workspace._thread is None, timeout=5000)

    assert workspace.state.project_path == first
    assert workspace.results_page.result.output_dir == output
    assert workspace.results_page.state == "published"


def test_results_explain_when_combined_was_not_selected_or_not_created(workspace, tmp_path):
    output = tmp_path / "published"
    output.mkdir()
    result = BatchResult(BatchState.PUBLISHED, output, 1)

    workspace.results_page.set_expected_combined(False)
    workspace.results_page.set_published(result)
    assert "not selected" in workspace.results_page.status_label.text().lower()

    workspace.results_page.set_expected_combined(True)
    workspace.results_page.set_published(result)
    assert "not created" in workspace.results_page.status_label.text().lower()
    assert "complete verified batch" not in workspace.results_page.status_label.text().lower()
    assert not workspace.results_page.open_combined_button.isEnabled()


def test_combined_open_failure_is_visible_and_other_result_actions_remain_available(
    workspace, qtbot, tmp_path
):
    output = tmp_path / "published"
    output.mkdir()
    combined = output / "Awards.pdf"
    combined.write_bytes(b"pdf")
    workspace.services.open_path = lambda _path: False
    workspace.results_page.set_expected_combined(True)
    workspace.results_page.set_published(
        BatchResult(BatchState.PUBLISHED, output, 2, combined_pdf_path=combined)
    )

    qtbot.mouseClick(workspace.results_page.open_combined_button, Qt.MouseButton.LeftButton)

    assert workspace.catalogs.text("results.print_check_failed") in workspace.results_page.status_label.text()
    assert not workspace.results_page.open_combined_button.isEnabled()
    assert workspace.results_page.open_output_button.isEnabled()


def test_resumed_project_result_uses_saved_combined_choice(workspace, tmp_path):
    output = tmp_path / "published"
    output.mkdir()
    workspace.project_state = replace(
        workspace.project_state,
        outputs=OutputOptions(False, False, True, tmp_path, "Awards", ("row-1",)),
    )

    workspace._generation_finished(BatchResult(BatchState.PUBLISHED, output, 1))

    assert "not created" in workspace.results_page.status_label.text().lower()
