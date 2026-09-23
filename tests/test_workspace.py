from __future__ import annotations

from types import SimpleNamespace
from contextlib import closing
from hashlib import sha256
import json
import sqlite3

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QTableView
import pytest

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.domain import BatchResult, BatchState
from certificate_automation.ui.workspace import WorkspaceWindow
from certificate_automation.ui.workspace import SaveState
from certificate_automation.project import ProjectCorruptError, ProjectSaveError, ProjectState, ProjectStore
from certificate_automation.word import WordAvailability


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
