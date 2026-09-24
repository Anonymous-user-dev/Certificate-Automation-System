from __future__ import annotations

from types import SimpleNamespace

from certificate_automation.app import create_default_services
from certificate_automation.history import HistoryIndex
from certificate_automation.windows_protection import DpapiProtector


def test_default_history_uses_stable_local_user_folder(tmp_path, monkeypatch):
    standard_paths = SimpleNamespace(
        StandardLocation=SimpleNamespace(AppLocalDataLocation=object()),
        writableLocation=lambda _location: str(tmp_path),
    )
    monkeypatch.setattr("certificate_automation.app.QStandardPaths", standard_paths)
    first = create_default_services()
    second = create_default_services()
    assert isinstance(first.history_index, HistoryIndex)
    assert isinstance(first.history_index.protector, DpapiProtector)
    assert first.history_index.path == second.history_index.path == tmp_path / "duplicate-history.sqlite"
    assert not first.history_index.path.exists()


def test_missing_per_user_folder_disables_history_instead_of_using_cwd(monkeypatch):
    standard_paths = SimpleNamespace(
        StandardLocation=SimpleNamespace(AppLocalDataLocation=object()),
        writableLocation=lambda _location: "",
    )
    monkeypatch.setattr("certificate_automation.app.QStandardPaths", standard_paths)
    assert create_default_services().history_index is None
