from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.domain import Issue, Severity
from certificate_automation.ui.data_page import DataPage, ImportPreviewDialog


def _dataset():
    return TabularDataset(
        (Column("full_name", "Full Name"), Column("award", "Award")),
        (DataRow("row-1", 2, {"full_name": "Ana", "award": "Gold"}),),
        SourceSnapshot(
            "manual",
            "Awards 2026",
            None,
            "b" * 64,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            {},
        ),
    )


def test_data_page_exposes_four_clear_source_actions(qtbot):
    page = DataPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    imports = QSignalSpy(page.import_requested)
    pastes = QSignalSpy(page.paste_requested)

    page.excel_button.click()
    page.delimited_button.click()
    page.paste_button.click()
    page.manual_button.click()

    assert [imports.at(index)[0] for index in range(imports.count())] == [
        "excel",
        "delimited",
        "manual",
    ]
    assert pastes.count() == 1
    for button in (
        page.excel_button,
        page.delimited_button,
        page.paste_button,
        page.manual_button,
    ):
        assert button.accessibleName()


def test_dataset_summary_continue_and_exact_cell_focus(qtbot):
    page = DataPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)

    page.set_dataset(_dataset())
    page.focus_cell("row-1", "award")

    assert page.source_label.text() == "Awards 2026"
    assert "1 recipient" in page.count_label.text()
    assert "2 columns" in page.count_label.text()
    assert page.continue_button.isEnabled()
    assert page.current_cell_ids() == ("row-1", "award")


def test_language_switch_relabels_controls_without_losing_data(qtbot):
    catalogs = CatalogSet.load(package_root(), "en")
    page = DataPage(catalogs)
    qtbot.addWidget(page)
    page.set_dataset(_dataset())

    catalogs.set_locale("zh_CN")

    assert page.title.text() == "收件人数据"
    assert page.continue_button.text() == "继续"
    assert page.model.dataset.row("row-1").value("full_name") == "Ana"


def test_import_preview_makes_parsing_choices_visible(qtbot):
    dialog = ImportPreviewDialog(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(dialog)

    dialog.set_preview(
        rows=(("Name", "Award"), ("Ana", "Gold")),
        encoding="Windows-1251",
        delimiter="Comma",
        worksheet="Recipients",
        hidden_policy="Exclude 2 hidden rows",
    )

    details = dialog.details_label.text()
    assert "Windows-1251" in details
    assert "Comma" in details
    assert "Recipients" in details
    assert "Exclude 2 hidden rows" in details
    assert dialog.preview_table.rowCount() == 2


def test_continue_emits_current_dataset(qtbot):
    page = DataPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    accepted = QSignalSpy(page.dataset_accepted)
    page.set_dataset(_dataset())

    page.continue_button.click()

    assert accepted.count() == 1
    assert accepted.at(0)[0] == page.model.dataset


def test_language_switch_retranslates_existing_issue_list(qtbot):
    catalogs = CatalogSet.load(package_root(), "en")
    page = DataPage(catalogs)
    qtbot.addWidget(page)
    page.set_dataset(_dataset())
    page.set_issues(
        (
            Issue(
                Severity.ERROR,
                "dataset",
                "validation.missing_name",
                row_id="row-1",
                column_id="full_name",
            ),
        )
    )

    catalogs.set_locale("ru")

    assert "обязательное имя" in page.issue_list.item(0).text().casefold()


def test_operator_can_rename_selected_column_and_undo(qtbot, monkeypatch):
    page = DataPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.set_dataset(_dataset())
    original_id = page.model.column_id_at(1)
    page.table.setCurrentIndex(page.model.index(0, 1))
    monkeypatch.setattr(
        "PySide6.QtWidgets.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Certificate Title", True),
    )

    qtbot.mouseClick(page.rename_column_button, Qt.MouseButton.LeftButton)

    assert page.model.dataset.columns[1].label == "Certificate Title"
    assert page.model.dataset.columns[1].column_id == original_id
    page.model.undo_stack.undo()
    assert page.model.dataset.columns[1].label == "Award"


def test_recipient_source_help_explains_paste_in_plain_language(qtbot):
    page = DataPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)

    help_text = page.source_help.text().casefold()
    assert "copy" in help_text
    assert "heading" in help_text
    assert "excel" in help_text
