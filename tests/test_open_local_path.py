from __future__ import annotations

import os

from PySide6.QtCore import QUrl

from certificate_automation.app import create_default_services
from certificate_automation.local_open import open_local_path


def test_open_local_path_rejects_missing_target_without_calling_opener(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("certificate_automation.local_open.QDesktopServices.openUrl", calls.append)

    assert open_local_path(tmp_path / "missing.pdf") is False
    assert calls == []


def test_open_local_path_uses_qt_for_existing_local_file(tmp_path, monkeypatch):
    target = tmp_path / "certificate.pdf"
    target.write_bytes(b"pdf")
    seen = []
    monkeypatch.setattr("certificate_automation.local_open.QDesktopServices.openUrl", lambda url: seen.append(url) or True)

    assert open_local_path(target) is True
    assert len(seen) == 1
    assert isinstance(seen[0], QUrl)
    assert seen[0].isLocalFile()
    assert seen[0].toLocalFile() == str(target)


def test_windows_fallback_uses_exact_path_when_qt_declines(tmp_path, monkeypatch):
    target = tmp_path / "combined.pdf"
    target.write_bytes(b"pdf")
    opened = []
    monkeypatch.setattr("certificate_automation.local_open.sys.platform", "win32")
    monkeypatch.setattr("certificate_automation.local_open.QDesktopServices.openUrl", lambda url: False)
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)

    assert open_local_path(target) is True
    assert opened == [str(target)]


def test_windows_fallback_handles_both_open_failures(tmp_path, monkeypatch):
    target = tmp_path / "combined.pdf"
    target.write_bytes(b"pdf")
    monkeypatch.setattr("certificate_automation.local_open.sys.platform", "win32")
    monkeypatch.setattr("certificate_automation.local_open.QDesktopServices.openUrl", lambda url: (_ for _ in ()).throw(RuntimeError("Qt failed")))
    monkeypatch.setattr(os, "startfile", lambda path: (_ for _ in ()).throw(OSError("no reader")), raising=False)

    assert open_local_path(target) is False


def test_default_application_service_uses_safe_local_opener(tmp_path, monkeypatch):
    missing = tmp_path / "missing.pdf"
    monkeypatch.setattr("certificate_automation.local_open.QDesktopServices.openUrl", lambda url: True)

    assert create_default_services().open_path(missing) is False
