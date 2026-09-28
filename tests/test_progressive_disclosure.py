from PySide6.QtCore import Qt

from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.data_page import DataPage
from certificate_automation.ui.match_page import MatchPage
from certificate_automation.ui.output_page import OutputPage


def test_data_page_keeps_table_editing_available_but_collapsed_by_default(qtbot):
    page = DataPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)

    assert page.edit_tools_panel.isHidden()
    assert page.table.isHidden() is False
    page.show()
    assert page.search_input.isVisibleTo(page)
    assert page.edit_tools_toggle.isCheckable()
    assert page.edit_tools_toggle.accessibleName()

    qtbot.mouseClick(page.edit_tools_toggle, Qt.MouseButton.LeftButton)

    assert page.edit_tools_panel.isHidden() is False
    assert page.rename_column_button.isHidden() is False
    qtbot.mouseClick(page.edit_tools_toggle, Qt.MouseButton.LeftButton)
    assert page.edit_tools_panel.isHidden()


def test_match_page_keeps_profiles_available_but_collapsed_by_default(qtbot):
    page = MatchPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)

    assert page.profile_panel.isHidden()
    assert page.scroll.isHidden() is False
    assert page.profile_toggle.isCheckable()
    assert page.profile_toggle.accessibleName()

    qtbot.mouseClick(page.profile_toggle, Qt.MouseButton.LeftButton)

    assert page.profile_panel.isHidden() is False
    assert page.apply_profile_button.isHidden() is False
    qtbot.mouseClick(page.profile_toggle, Qt.MouseButton.LeftButton)
    assert page.profile_panel.isHidden()


def test_output_page_keeps_print_controls_available_but_collapsed_by_default(qtbot):
    page = OutputPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)

    assert page.advanced_panel.isHidden()
    assert page.destination.isHidden() is False
    assert page.summary_label.isHidden() is False
    assert page.advanced_toggle.isCheckable()
    assert page.advanced_toggle.accessibleName()

    qtbot.mouseClick(page.advanced_toggle, Qt.MouseButton.LeftButton)

    assert page.advanced_panel.isHidden() is False
    assert page.print_width.isHidden() is False
    assert page.order_list.isHidden() is False
    qtbot.mouseClick(page.advanced_toggle, Qt.MouseButton.LeftButton)
    assert page.advanced_panel.isHidden()


def test_print_settings_error_opens_the_controls_needed_to_fix_it(qtbot, tmp_path):
    page = OutputPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.set_order(("recipient-1",))
    page.destination.setText(str(tmp_path))
    page.batch_name.setText("Awards")
    page.combined_pdf.setChecked(True)

    page.continue_button.click()

    assert "page size" in page.error_label.text().casefold()
    assert page.advanced_toggle.isChecked()
    assert not page.advanced_panel.isHidden()


def test_disclosure_labels_retranslate_without_changing_open_state(qtbot):
    catalogs = CatalogSet.load(package_root(), "en")
    data = DataPage(catalogs)
    match = MatchPage(catalogs)
    output = OutputPage(catalogs)
    for page in (data, match, output):
        qtbot.addWidget(page)

    data.edit_tools_toggle.click()
    match.profile_toggle.click()
    output.advanced_toggle.click()
    catalogs.set_locale("ru")

    assert data.edit_tools_toggle.text() == "Редактировать таблицу"
    assert match.profile_toggle.text() == "Сохранённые настройки"
    assert output.advanced_toggle.text() == "Печать и расширенные настройки"
    assert data.edit_tools_toggle.accessibleDescription()
    assert match.profile_toggle.accessibleDescription()
    assert output.advanced_toggle.accessibleDescription()
    assert not data.edit_tools_panel.isHidden()
    assert not match.profile_panel.isHidden()
    assert not output.advanced_panel.isHidden()
