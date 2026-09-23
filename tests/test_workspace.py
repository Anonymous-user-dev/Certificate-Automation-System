from __future__ import annotations

from types import SimpleNamespace
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
import json
import sqlite3

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QComboBox, QLineEdit, QTableView
import pytest

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.domain import BatchResult, BatchState
from certificate_automation.ui.workspace import WorkspaceWindow
from certificate_automation.ui.workspace import SaveState
from certificate_automation.project import ProjectCorruptError, ProjectSaveError, ProjectState, ProjectStore
from certificate_automation.word import WordAvailability
from certificate_automation.template import inspect_template
from fixtures import docx_factory


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
    (tmp_path / "output").mkdir(exist_ok=True)
    stored = replace(
        original,
        revision=5,
        template_path=template_path,
        template_sha256=inspection.sha256,
        template_inspection={"sha256": inspection.sha256, "names": ["FULL_NAME"]},
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
    assert not workspace.match_page.continue_button.isEnabled()
    assert workspace.review_page.values_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert not workspace.review_page.preview_button.isEnabled()
    assert not workspace.output_page.docx.isEnabled()
    assert not workspace.output_page.continue_button.isEnabled()


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
