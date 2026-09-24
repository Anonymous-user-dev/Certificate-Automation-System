from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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


def test_locked_destination_keeps_other_history_visible_and_disables_local_actions(qtbot, tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    elsewhere = tmp_path / "elsewhere" / "Awards-revision-1"
    elsewhere.mkdir(parents=True)
    (elsewhere / "manifest.json").write_text("{}", encoding="utf-8")
    original_stat = Path.stat

    def inaccessible(self, *args, **kwargs):
        if self == locked:
            raise PermissionError(13, "access denied", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", inaccessible)
    catalogs = CatalogSet.load(package_root(), "en")
    page = HistoryPage(catalogs)
    qtbot.addWidget(page)

    page.load(locked, published_paths=(elsewhere,))

    assert len(page.records) == 1
    assert page.records[0].path == elsewhere
    assert page.records[0].status == "damaged"
    assert page.status_label.text() == catalogs.text("history.scan_unavailable")
    opened = []
    page.open_path_requested.connect(opened.append)
    assert page.action_button(0, "open_folder").isEnabled()
    page.action_button(0, "open_folder").click()
    assert opened == [elsewhere]
    assert not page.action_button(0, "open_combined").isEnabled()
    assert not page.action_button(0, "correct").isEnabled()
    for locale in ("ru", "zh_CN"):
        catalogs.set_locale(locale)
        assert page.status_label.text() == catalogs.text("history.scan_unavailable")


def test_record_stat_failure_is_unavailable_with_actions_disabled(qtbot, tmp_path, monkeypatch):
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    original_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self == folder:
            raise PermissionError(13, "locked", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    catalogs = CatalogSet.load(package_root(), "en")
    page = HistoryPage(catalogs)
    qtbot.addWidget(page)

    page.load(tmp_path, published_paths=(folder,))

    assert page.records[0].status == "unavailable"
    assert not any(page.action_button(0, action).isEnabled() for action in
                   ("open_folder", "open_combined", "open_audit", "verify", "correct", "remove"))


def test_history_root_stat_denial_keeps_other_records_visible(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "locked-root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere" / "Awards-revision-1"
    elsewhere.mkdir(parents=True)
    (elsewhere / "manifest.json").write_text("{}", encoding="utf-8")
    original_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self == root:
            raise PermissionError(13, "access denied", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    catalogs = CatalogSet.load(package_root(), "en")
    page = HistoryPage(catalogs)
    qtbot.addWidget(page)
    page.load(root, published_paths=(elsewhere,))

    assert page._scan_unavailable
    assert any(record.path == elsewhere for record in page.records)
    assert page.status_label.text() == catalogs.text("history.scan_unavailable")


def test_history_entry_stat_denial_is_not_misreported_as_missing(qtbot, tmp_path, monkeypatch):
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    original_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self == folder:
            raise PermissionError(1, "operation not permitted", str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    page = HistoryPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.load(tmp_path)

    assert len(page.records) == 1
    assert page.records[0].status == "unavailable"
    assert not page.action_button(0, "open_folder").isEnabled()
