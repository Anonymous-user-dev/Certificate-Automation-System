from __future__ import annotations

from zipfile import ZipFile

from PySide6.QtWidgets import QMessageBox

from certificate_automation.diagnostics import DiagnosticBundleService, DiagnosticContext
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.support_dialog import SupportDialog


def test_support_dialog_defaults_to_redacted_local_bundle(qtbot, tmp_path):
    catalogs = CatalogSet.load(package_root(), "en")
    dialog = SupportDialog(catalogs, DiagnosticBundleService(), DiagnosticContext(issue_codes=("validation.error",)))
    qtbot.addWidget(dialog)
    sensitive = tmp_path / "Ana García.pdf"
    sensitive.write_bytes(b"official")
    dialog.add_sensitive_file(sensitive)

    assert not dialog.include_sensitive.isChecked()
    assert str(sensitive) in dialog.attachments_list.item(0).text()
    output = dialog.create_bundle(tmp_path / "support.zip")

    with ZipFile(output) as archive:
        assert archive.namelist() == ["diagnostic.json", "support.log"]
    assert dialog.status_label.text()


def test_support_dialog_requires_confirmation_for_each_listed_sensitive_file(qtbot, tmp_path, monkeypatch):
    catalogs = CatalogSet.load(package_root(), "en")
    dialog = SupportDialog(catalogs, DiagnosticBundleService(), DiagnosticContext())
    qtbot.addWidget(dialog)
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.docx"
    first.write_bytes(b"pdf bytes")
    second.write_bytes(b"docx bytes")
    dialog.add_sensitive_file(first)
    dialog.add_sensitive_file(second)
    dialog.include_sensitive.setChecked(True)
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _parent, _title, text, *_args: prompts.append(text) or QMessageBox.StandardButton.No)

    assert dialog.create_bundle(tmp_path / "blocked.zip") is None
    assert len(prompts) == 1
    assert str(first) in prompts[0] and str(second) in prompts[0]
    assert not (tmp_path / "blocked.zip").exists()

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    output = dialog.create_bundle(tmp_path / "confirmed.zip")
    with ZipFile(output) as archive:
        assert archive.namelist()[-2:] == ["sensitive/0001.bin", "sensitive/0002.bin"]


def test_support_dialog_retranslates_controls(qtbot):
    catalogs = CatalogSet.load(package_root(), "en")
    dialog = SupportDialog(catalogs, DiagnosticBundleService(), DiagnosticContext())
    qtbot.addWidget(dialog)
    english = dialog.create_button.text()

    catalogs.set_locale("ru")
    assert dialog.create_button.text() != english
    assert dialog.create_button.accessibleName() == dialog.create_button.text()
    catalogs.set_locale("zh_CN")
    assert dialog.include_sensitive.accessibleName() == dialog.include_sensitive.text()
