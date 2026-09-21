from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QTableView
import pytest

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.workspace import WorkspaceWindow


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
    assert workspace.home.new_batch_button.isVisible()
    assert workspace.home.continue_draft_button.isVisible()
    assert workspace.home.recover_button.isVisible()
    assert workspace.home.open_results_button.isVisible()


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
