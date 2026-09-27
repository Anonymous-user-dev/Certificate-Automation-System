import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings

from certificate_automation.i18n import CatalogError, CatalogSet, validate_catalogs
from certificate_automation.domain import Issue, Severity
from certificate_automation.ui.validation_page import ValidationPage
from certificate_automation.validation import ValidationReport
from certificate_automation.ui.workspace import WorkspaceWindow


PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "certificate_automation"


def test_catalogs_have_identical_keys_and_parameters():
    assert validate_catalogs(PACKAGE_ROOT) == ()


def test_unknown_locale_falls_back_to_english():
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale="de")

    assert catalogs.locale == "en"
    assert catalogs.text("nav.data") == "Recipient Data"


def test_catalog_formats_parameters_in_selected_language():
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale="ru")

    assert catalogs.text("validation.blank_mapped_value", row=7, placeholder="FULL_NAME") == (
        "В строке 7 нет значения для {{FULL_NAME}}."
    )


def test_missing_format_parameter_is_reported_without_exposing_data():
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale="en")

    with pytest.raises(CatalogError) as caught:
        catalogs.text("validation.blank_mapped_value", row=7)

    assert caught.value.code == "i18n.missing_parameter"
    assert "FULL_NAME" not in str(caught.value)


def test_locale_change_notifies_subscribers_once():
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale="en")
    observed: list[str] = []
    catalogs.subscribe(observed.append)

    catalogs.set_locale("zh_CN")
    catalogs.set_locale("zh_CN")

    assert observed == ["zh_CN"]


def test_validation_page_formats_structured_issue_in_active_locale(qtbot):
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale="ru")
    page = ValidationPage(catalogs=catalogs)
    qtbot.addWidget(page)
    report = ValidationReport(
        issues=(
            Issue(
                Severity.ERROR,
                "workbook",
                "validation.blank_mapped_value",
                {"row": 2, "placeholder": "FULL_NAME"},
            ),
        ),
        filename_stems={},
        estimated_bytes=0,
    )

    page.set_report(report)

    assert "В строке 2 нет значения" in page.issue_text.toPlainText()
    assert "Ошибка" in page.issue_text.toPlainText()


@pytest.mark.parametrize(
    ("key", "parameters"),
    [
        ("import.excel.unreadable", {"filename": "recipients.xlsx"}),
        ("import.excel.sheet_missing", {"sheet": "Recipients"}),
        ("import.excel.formula_cache_missing", {"cell": "B2"}),
        ("import.excel.merged_data_cells", {"ranges": "A2:B2"}),
        ("import.excel.blank_header", {"cell": "B1"}),
        ("import.excel.duplicate_header", {"header": "Full Name"}),
    ],
)
def test_excel_failures_have_complete_offline_translations(key, parameters):
    for locale in ("en", "zh_CN", "ru"):
        catalogs = CatalogSet.load(PACKAGE_ROOT, locale=locale)
        assert catalogs.text(key, **parameters)


@pytest.mark.parametrize(
    ("key", "parameters"),
    [
        ("import.delimited.empty", {}),
        ("import.delimited.nul_byte", {}),
        ("import.delimited.choice_required", {}),
        ("import.delimited.decode_failed", {"encoding": "cp1251"}),
        ("import.delimited.inconsistent_width", {"row": 2, "expected": 2, "actual": 3}),
        ("import.delimited.blank_header", {"column": 2}),
        ("import.delimited.duplicate_header", {"header": "Name"}),
        ("import.delimited.malformed_csv", {}),
        ("import.clipboard.header_mismatch", {}),
        ("import.clipboard.mode_required", {}),
        ("import.manual.blank_header", {}),
        ("import.manual.duplicate_header", {}),
        ("import.manual.no_columns", {}),
    ],
)
def test_text_and_manual_import_failures_have_complete_translations(key, parameters):
    for locale in ("en", "zh_CN", "ru"):
        assert CatalogSet.load(PACKAGE_ROOT, locale).text(key, **parameters)


@pytest.mark.parametrize(
    "key",
    [
        "project.already_exists",
        "project.create_failed",
        "project.missing",
        "project.unreadable",
        "project.schema_missing",
        "project.newer_schema",
        "project.older_schema",
        "project.read_only",
        "project.save_failed",
        "project.backup_failed",
        "project.no_valid_revision",
        "project.no_valid_backup",
        "project.invalid_revision",
        "project.invalid_dataset",
    ],
)
def test_project_failures_have_complete_offline_translations(key):
    for locale in ("en", "zh_CN", "ru"):
        assert CatalogSet.load(PACKAGE_ROOT, locale).text(key)


@pytest.mark.parametrize("locale", ("en", "zh_CN", "ru"))
def test_project_home_save_and_example_messages_are_localized(locale):
    catalog = CatalogSet.load(PACKAGE_ROOT, locale)
    for key in (
        "home.new_project", "home.open_project", "home.recent_projects",
        "home.recover_project", "home.try_example", "project.health.missing",
        "save_state.saved", "save_state.saving", "save_state.failed",
        "save_state.read_only", "example.destination_not_empty", "close.save_failed",
    ):
        assert catalog.text(key) != key
    assert "Awards" in catalog.text("migration.completed", backup="Awards")


@pytest.mark.parametrize(
    ("key", "parameters"),
    [
        ("mapping.column_missing", {}),
        ("mapping.invalid_sequence", {}),
        ("mapping.invalid_date_format", {}),
        ("mapping.invalid_join", {}),
        ("mapping.blank_placeholder", {}),
        ("mapping.unknown_source_type", {}),
        ("mapping.invalid_json", {}),
        ("mapping.invalid_date_source", {}),
        ("mapping.date_ambiguous", {"row": 2}),
        ("mapping.date_format_required", {"row": 2}),
        ("mapping.date_invalid", {"row": 2}),
        ("mapping.unknown_column", {}),
        ("output.none_selected", {}),
        ("output.destination_missing", {}),
        ("output.row_missing", {}),
        ("output.duplicate_row", {}),
        ("output.invalid_batch_name", {}),
        ("output.unknown_row", {"row_id": "row-1"}),
        ("output.row_omitted", {"row_id": "row-1"}),
        ("output.reserved_filename", {"filename": "CON"}),
        ("output.path_too_long", {"filename": "certificate"}),
        ("output.filename_collision", {"filename": "Ana"}),
        ("output.combined_pdf_empty", {}),
        ("output.combined_pdf_overwrites_source", {}),
        ("output.combined_pdf_input_invalid", {}),
        ("output.combined_pdf_page_count_mismatch", {}),
        ("output.combined_pdf_failed", {}),
        ("output.combined_pdf_verification_failed", {}),
        ("output.combined_pdf_destination_exists", {}),
        ("output.artifact_changed", {}),
    ],
)
def test_mapping_and_output_failures_have_complete_offline_translations(key, parameters):
    for locale in ("en", "zh_CN", "ru"):
        assert CatalogSet.load(PACKAGE_ROOT, locale).text(key, **parameters)


def test_changed_template_during_generation_has_complete_offline_translations():
    for locale in ("en", "zh_CN", "ru"):
        assert CatalogSet.load(PACKAGE_ROOT, locale).text(
            "template.changed_during_generation"
        )


def test_operator_ui_source_has_no_untranslated_literal_labels():
    """Prevent new English-only controls from bypassing the offline catalogs."""
    constructors = {"QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox"}
    setters = {
        "setText", "setTitle", "setPlaceholderText", "setAccessibleName",
        "setAccessibleDescription", "addRow",
    }
    technical = {"", "—"}
    leaks = []
    for path in sorted((PACKAGE_ROOT / "ui").glob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = (
                node.func.id if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name not in constructors | setters:
                continue
            value = node.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal = value.value
                if literal not in technical and any(character.isalpha() for character in literal):
                    leaks.append(f"{path.name}:{node.lineno}:{literal}")
    assert leaks == []


@pytest.mark.parametrize("locale", ["zh_CN", "ru"])
def test_workspace_primary_workflow_renders_without_english_fallback(
    locale, qtbot, tmp_path,
):
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale)
    settings = QSettings(
        str(tmp_path / f"{locale}-i18n.ini"), QSettings.Format.IniFormat,
    )
    window = WorkspaceWindow(SimpleNamespace(catalogs=catalogs), settings=settings)
    qtbot.addWidget(window)
    window.show()
    window.new_project()
    window.set_locale(locale)

    assert window.step_rail.text_for("data") == catalogs.text("nav.data")
    assert window.data_page.title.text() == catalogs.text("data.title")
    assert window.output_page.title.text() == catalogs.text("output.title")
    assert window.results_page.title.text() == catalogs.text("results.title")
    assert window.data_page.title.text() != CatalogSet.load(PACKAGE_ROOT, "en").text("data.title")
