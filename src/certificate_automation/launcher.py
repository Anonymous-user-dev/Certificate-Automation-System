"""Minimal packaged entry point with a deterministic distribution smoke probe."""

from __future__ import annotations

import os
import sys


def _run_ui_smoke_test() -> None:
    """Import Qt and construct the real workspace before reporting success."""

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from certificate_automation.app import create_default_services
    from certificate_automation.ui.workspace import WorkspaceWindow

    application = QApplication.instance() or QApplication(sys.argv)
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "Certificate Automation",
        "Package Smoke Test",
    )
    window = WorkspaceWindow(create_default_services("en"), settings=settings)
    window.show()
    application.processEvents()
    exit_code = 0 if window.isVisible() else 3
    window.close()
    os._exit(exit_code)


def _run_workflow_smoke_test() -> None:
    """Exercise the packaged beginner workflow without opening user files."""

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from certificate_automation.app import create_default_services
    from certificate_automation.ui.workspace import WorkspaceWindow

    application = QApplication.instance() or QApplication(sys.argv)
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "Certificate Automation",
        "Workflow Package Smoke Test",
    )
    window = WorkspaceWindow(create_default_services("en"), settings=settings)
    window.new_project()
    window.match_page.set_context(
        window.data_page.model.dataset,
        ("EMPLOYEE_ID",),
    )
    application.processEvents()
    correct = all(
        (
            window.output_page.docx.isChecked(),
            window.output_page.individual_pdf.isChecked(),
            not window.output_page.combined_pdf.isChecked(),
            "EMPLOYEE_ID" in window.match_page.cards,
            "{{FIELD_NAME}}" in window.match_page.explanation.text(),
        )
    )
    window.close()
    os._exit(0 if correct else 4)


if "--workflow-smoke-test" in sys.argv:
    _run_workflow_smoke_test()
elif "--smoke-test" in sys.argv or "--ui-smoke-test" in sys.argv:
    _run_ui_smoke_test()

from certificate_automation.app import main  # noqa: E402


raise SystemExit(main())
