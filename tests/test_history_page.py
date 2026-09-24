from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QMessageBox

from certificate_automation.history import HistoryIndex, PublishedBatch
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.history_page import HistoryPage


class MemoryProtector:
    def protect(self, value, *, purpose):
        return purpose.encode() + b":" + value[::-1]

    def unprotect(self, value, *, purpose):
        return value.split(b":", 1)[1][::-1]


def test_history_lists_missing_and_incomplete_without_removing_either(qtbot, tmp_path):
    index = HistoryIndex(tmp_path / "index.sqlite", MemoryProtector())
    missing = tmp_path / "Awards-revision-1"
    index.record(PublishedBatch("batch-1", 1, datetime.now(timezone.utc), missing), ("Ana",))
    incomplete = tmp_path / ".certificate-incomplete-batch-2"
    incomplete.mkdir()
    (incomplete / "diagnostic.json").write_text("{}", encoding="utf-8")
    page = HistoryPage(CatalogSet.load(package_root(), "en"), history_index=index)
    qtbot.addWidget(page)

    page.load(tmp_path)

    assert {record.status for record in page.records} == {"missing", "incomplete"}
    assert missing in (record.path for record in page.records)
    assert page.action_button(0, "open_combined").isEnabled() is False
    assert missing.exists() is False
    assert incomplete.is_dir()


def test_history_removes_only_exact_incomplete_after_confirmation(qtbot, tmp_path, monkeypatch):
    incomplete = tmp_path / ".certificate-incomplete-batch-2"
    incomplete.mkdir()
    (incomplete / "diagnostic.json").write_text("{}", encoding="utf-8")
    unrelated = tmp_path / "official-revision-1"
    unrelated.mkdir()
    page = HistoryPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.load(tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
    page.action_button(0, "remove").click()
    assert incomplete.is_dir()

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    page.action_button(0, "remove").click()
    assert not incomplete.exists()
    assert unrelated.is_dir()


def test_history_integrity_action_reports_invalid_bytes_and_blocks_open(qtbot, tmp_path):
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    page = HistoryPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.load(tmp_path, published_paths=(folder,))

    assert page.records[0].status == "damaged"
    page.action_button(0, "verify").click()
    assert "integrity.manifest_invalid" in page.status_label.text()
    assert not page.action_button(0, "open_audit").isEnabled()
    assert not page.action_button(0, "correct").isEnabled()


def test_history_retranslates_action_buttons(qtbot, tmp_path):
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    catalogs = CatalogSet.load(package_root(), "en")
    page = HistoryPage(catalogs)
    qtbot.addWidget(page)
    page.load(tmp_path, published_paths=(folder,))
    english = page.action_button(0, "verify").text()

    catalogs.set_locale("ru")
    assert page.action_button(0, "verify").text() != english
    catalogs.set_locale("zh_CN")
    assert page.action_button(0, "verify").accessibleName().startswith(page.action_button(0, "verify").text())


def test_history_discovers_revision_folder_when_private_index_is_unavailable(qtbot, tmp_path):
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "batch_journal.json").write_text("{}", encoding="utf-8")
    page = HistoryPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)

    page.load(tmp_path)

    assert len(page.records) == 1
    assert page.records[0].path == folder
    assert page.records[0].status == "damaged"
