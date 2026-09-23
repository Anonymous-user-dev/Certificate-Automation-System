from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.template_page import TemplatePage
from certificate_automation.template import inspect_template
from certificate_automation.ui.workspace import WorkspaceWindow
from fixtures import docx_factory


def _drag(page: TemplatePage, urls: list[QUrl]) -> tuple[bool, bool]:
    mime = QMimeData()
    mime.setUrls(urls)
    enter = QDragEnterEvent(
        QPoint(12, 12), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(page, enter)
    drop = QDropEvent(
        QPointF(12, 12), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(page, drop)
    return enter.isAccepted(), drop.isAccepted()


def test_drop_one_local_docx_emits_same_selection_as_picker(qtbot, docx_factory):
    path = docx_factory(paragraph_runs=[["{{NAME}}"]])
    upper = path.with_suffix(".DOCX")
    path.rename(upper)
    page = TemplatePage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.show()
    selected = []
    page.template_selected.connect(selected.append)

    entered, dropped = _drag(page, [QUrl.fromLocalFile(str(upper))])

    assert page.acceptDrops()
    assert page.drop_hint.isVisible()
    assert page.drop_hint.accessibleName()
    assert entered and dropped
    assert selected == [upper]


def test_drag_move_keeps_valid_explorer_drop_accepted(qtbot, docx_factory):
    path = docx_factory(paragraph_runs=[["{{NAME}}"]])
    page = TemplatePage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.show()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter = QDragEnterEvent(
        QPoint(12, 12), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(page, enter)
    move = QDragMoveEvent(
        QPoint(60, 48), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(page, move)

    assert enter.isAccepted()
    assert move.isAccepted()


@pytest.mark.parametrize(
    ("kind", "expected_key"),
    [
        ("multiple", "template.drop_one"),
        ("folder", "template.drop_file"),
        ("remote", "template.drop_local"),
        ("wrong_type", "template.unsupported_type"),
        ("missing", "template.drop_file"),
    ],
)
def test_drag_rejects_unsafe_payload_and_explains_it(
    qtbot, tmp_path, docx_factory, kind, expected_key
):
    path = docx_factory(paragraph_runs=[["{{NAME}}"]])
    other = tmp_path / "other.docx"
    other.write_bytes(b"x")
    urls = {
        "multiple": [QUrl.fromLocalFile(str(path)), QUrl.fromLocalFile(str(other))],
        "folder": [QUrl.fromLocalFile(str(tmp_path))],
        "remote": [QUrl("https://example.com/template.docx")],
        "wrong_type": [QUrl.fromLocalFile(str(other.with_suffix(".txt")))],
        "missing": [QUrl.fromLocalFile(str(tmp_path / "missing.docx"))],
    }
    if kind == "wrong_type":
        other.with_suffix(".txt").write_bytes(b"x")
    catalogs = CatalogSet.load(package_root(), "en")
    page = TemplatePage(catalogs)
    qtbot.addWidget(page)
    page.show()
    selected = []
    page.template_selected.connect(selected.append)

    entered, dropped = _drag(page, urls[kind])

    assert not entered and not dropped
    assert selected == []
    assert page.error_label.text() == catalogs.text(expected_key)


@pytest.mark.parametrize("locale", ["en", "zh_CN", "ru"])
def test_drop_guidance_and_error_follow_language(qtbot, tmp_path, locale):
    catalogs = CatalogSet.load(package_root(), locale)
    page = TemplatePage(catalogs)
    qtbot.addWidget(page)
    page.show()

    _drag(page, [QUrl.fromLocalFile(str(tmp_path))])

    assert page.drop_hint.text() == catalogs.text("template.drop_hint")
    assert page.error_label.text() == catalogs.text("template.drop_file")
    assert page.drop_hint.accessibleName() == catalogs.text("template.drop_hint")


def test_dropped_template_uses_workspace_strict_inspection(qtbot, docx_factory):
    template = docx_factory(paragraph_runs=[["{{CUSTOM_FIELD}}"]])
    services = SimpleNamespace(
        catalogs=CatalogSet.load(package_root(), "en"),
        inspect_template=inspect_template,
    )
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.show()
    window.new_project()

    entered, dropped = _drag(window.template_page, [QUrl.fromLocalFile(str(template))])

    assert entered and dropped
    assert window.template_page.inspection.path == template
    assert window.template_page.inspection.names == ("CUSTOM_FIELD",)
