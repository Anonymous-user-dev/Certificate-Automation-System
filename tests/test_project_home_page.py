from pathlib import Path
from hashlib import sha256
import shutil

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QScrollArea

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.project_catalog import ProjectHealth, ProjectSummary
from certificate_automation.ui.project_home_page import ProjectHomePage
from certificate_automation.app import ExampleProjectError, create_example_project
from certificate_automation.project import ProjectStore


def test_home_exposes_five_beginner_actions(qtbot):
    page = ProjectHomePage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.show()

    assert [button.objectName() for button in page.primary_buttons()] == [
        "newProject", "openProject", "recentProjects", "recoverProject", "tryExample"
    ]
    assert all(button.isVisible() for button in page.primary_buttons())


def test_missing_recent_project_stays_visible_with_repair_action(qtbot, tmp_path):
    catalogs = CatalogSet.load(package_root(), "en")
    page = ProjectHomePage(catalogs)
    qtbot.addWidget(page)
    page.show()
    missing = ProjectSummary(tmp_path / "missing.certproject", None, 3, "data", None, ProjectHealth.MISSING)
    page.set_projects((missing,))

    assert page.project_status(0) == catalogs.text("project.health.missing")
    assert page.repair_button(0).isVisible()
    assert missing.path.name in page.project_label(0).text()


def test_recent_step_uses_selected_language(qtbot, tmp_path):
    catalogs = CatalogSet.load(package_root(), "ru")
    page = ProjectHomePage(catalogs)
    qtbot.addWidget(page)
    page.set_projects((ProjectSummary(tmp_path / "Awards.certproject", None, 3, "data", None, ProjectHealth.READY),))

    assert catalogs.text("nav.data") in page.project_label(0).text()
    assert "Step data" not in page.project_label(0).text()


def test_home_buttons_have_distinct_accessible_names_and_keyboard_focus_at_200_percent(qtbot):
    page = ProjectHomePage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    font = QFont(page.font())
    font.setPointSize(max(20, font.pointSize() * 2))
    page.setFont(font)
    page.resize(960, 720)
    page.show()
    qtbot.waitExposed(page)
    buttons = page.primary_buttons()

    assert len({button.accessibleName() for button in buttons}) == 5
    assert all(button.isVisible() and button.height() >= button.fontMetrics().height() for button in buttons)
    buttons[0].setFocus(Qt.FocusReason.TabFocusReason)
    for current, following in zip(buttons, buttons[1:]):
        assert page.focusWidget() is current
        qtbot.keyClick(current, Qt.Key.Key_Tab)
        assert page.focusWidget() is following


def test_long_recent_list_scrolls_at_large_font(qtbot, tmp_path):
    page = ProjectHomePage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    font = QFont(page.font())
    font.setPointSize(20)
    page.setFont(font)
    page.set_projects(tuple(
        ProjectSummary(tmp_path / f"Project {index}.certproject", None, 3, "data", None, ProjectHealth.MISSING)
        for index in range(12)
    ))
    page.resize(800, 600)
    page.show()
    qtbot.waitExposed(page)

    scroll = page.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0
    assert all(button.isVisible() for button in page.primary_buttons())


def _sample_hashes(root: Path) -> dict[str, str]:
    return {path.name: sha256(path.read_bytes()).hexdigest() for path in root.iterdir() if path.is_file()}


def test_example_copies_installed_sources_into_editable_project(tmp_path):
    source = Path(__file__).parents[1] / "examples"
    originals = _sample_hashes(source)
    destination = tmp_path / "My Example"

    project = create_example_project(source, destination)

    assert project.is_file()
    assert project.parent == destination
    assert _sample_hashes(source) == originals
    assert all((destination / name).is_file() for name in originals)
    state = ProjectStore.open(project).load()
    assert state.schema_version == 2
    assert state.dataset.source.path == destination / "sample_recipients.csv"
    assert state.template_path == destination / "sample_certificate_template.docx"
    assert len(state.dataset.rows) == 3
    (destination / "sample_recipients.csv").write_text("editable copy", encoding="utf-8")
    assert _sample_hashes(source) == originals


def test_example_refuses_nonempty_destination_without_touching_it(tmp_path):
    source = Path(__file__).parents[1] / "examples"
    destination = tmp_path / "existing"
    destination.mkdir()
    keep = destination / "keep.txt"
    keep.write_text("mine", encoding="utf-8")

    with pytest.raises(ExampleProjectError, match="example.destination_not_empty"):
        create_example_project(source, destination)

    assert keep.read_text(encoding="utf-8") == "mine"
    assert list(destination.iterdir()) == [keep]


def test_invalid_example_rolls_back_copied_files(tmp_path):
    installed = Path(__file__).parents[1] / "examples"
    source = tmp_path / "broken installed example"
    source.mkdir()
    for name in ("sample_recipients.csv", "sample_certificate_template.docx", "sample_students.xlsx"):
        shutil.copy2(installed / name, source / name)
    (source / "sample_recipients.csv").write_bytes(b"bad\x00data")
    destination = tmp_path / "working example"

    with pytest.raises(ExampleProjectError, match="example.copy_failed"):
        create_example_project(source, destination)

    assert not destination.exists()
