from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMessageBox
from docx import Document
import pytest
from pypdf import PdfReader, PdfWriter

from certificate_automation.batch import BatchGenerator
from certificate_automation.batch import BatchResult
from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.domain import BatchState, Issue, Severity
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.mapping import ColumnValue, FormattedDateValue, MappingPlan
from certificate_automation.output_options import OutputOptions
from certificate_automation.project import ProjectState, ProjectStore
from certificate_automation.template import inspect_template
from certificate_automation.template_health import TemplateHealthService
from certificate_automation.ui.workspace import WorkspaceWindow
from certificate_automation.validation import ValidationReport, validate_preflight
from certificate_automation.word import WordAvailability
from fixtures import docx_factory


class RecordingGenerator:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.requests = []

    def generate(self, request, progress=None, cancellation=None):
        self.requests.append(request)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(SimpleNamespace(current=2, total=2, message="Verified"))
        return BatchResult(BatchState.PUBLISHED, self.output_dir, 2)


def _dataset():
    return TabularDataset(
        (Column("name", "Name"), Column("award", "Award")),
        (
            DataRow("row-1", 2, {"name": "Li Ming", "award": "Gold"}),
            DataRow("row-2", 3, {"name": "Chen Wei", "award": "Silver"}),
        ),
        SourceSnapshot(
            "manual",
            "Manual table",
            None,
            "d" * 64,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        ),
    )


def _services(tmp_path, template):
    class LayoutConverter:
        def convert(self, _source, destination):
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with destination.open("wb") as stream:
                writer.write(stream)

    generator = RecordingGenerator(tmp_path / "published")
    return SimpleNamespace(
        catalogs=CatalogSet.load(package_root(), "en"),
        inspect_template=lambda path: inspect_template(path),
        validate=validate_preflight,
        batch_generator=generator,
        word_availability=lambda: WordAvailability(True, "available"),
        open_path=lambda path: True,
        generator=generator,
        template=template,
        template_health_service=TemplateHealthService(LayoutConverter(), tmp_path / "layout-previews"),
    )


def _finish_layout_review(window, qtbot):
    qtbot.mouseClick(window.template_health_page.render_button, Qt.MouseButton.LeftButton)
    assert window.template_health_page.layout_result.ready
    for index in range(window.template_health_page.preview_selector.count()):
        window.template_health_page.preview_selector.setCurrentIndex(index)
    assert window.template_health_page.mark_reviewed_button.isEnabled()
    qtbot.mouseClick(window.template_health_page.mark_reviewed_button, Qt.MouseButton.LeftButton)


@pytest.mark.parametrize("locale", ["en", "zh_CN", "ru"])
def test_operator_can_complete_manual_combined_pdf_workflow(
    qtbot,
    tmp_path,
    docx_factory,
    locale,
):
    template_path = docx_factory(
        paragraph_runs=[["{{FULL_NAME}}"], ["{{AWARD}}"]]
    )
    services = _services(tmp_path, template_path)
    settings = QSettings(str(tmp_path / f"{locale}.ini"), QSettings.Format.IniFormat)
    window = WorkspaceWindow(services, settings=settings)
    qtbot.addWidget(window)
    window.show()
    window.set_locale(locale)
    window.new_project()
    window.data_page.set_dataset(_dataset())

    qtbot.mouseClick(window.data_page.continue_button, Qt.MouseButton.LeftButton)
    window.template_page.set_inspection(inspect_template(template_path))
    qtbot.mouseClick(window.template_page.continue_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.template_health_page.continue_button, Qt.MouseButton.LeftButton)
    window.match_page.cards["FULL_NAME"].set_column("Name")
    window.match_page.cards["AWARD"].set_column("Award")
    qtbot.mouseClick(window.match_page.continue_button, Qt.MouseButton.LeftButton)
    _finish_layout_review(window, qtbot)
    window.review_page.select_recipient("row-2")
    qtbot.mouseClick(window.review_page.continue_button, Qt.MouseButton.LeftButton)
    destination = tmp_path / f"output-{locale}"
    destination.mkdir()
    window.output_page.docx.setChecked(False)
    window.output_page.combined_pdf.setChecked(True)
    window.output_page.destination.setText(str(destination))
    window.output_page.batch_name.setText("Awards")
    qtbot.mouseClick(window.output_page.continue_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.results_page.generate_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: window.results_page.state == "published")
    qtbot.waitUntil(lambda: window._thread is None)
    assert services.generator.requests[-1].outputs.combined_pdf is True
    assert services.generator.requests[-1].outputs.row_ids == ("row-1", "row-2")


def test_operator_combined_only_creates_ordered_pdf_and_opens_published_file(
    qtbot, tmp_path, docx_factory
):
    class Converter:
        def is_available(self):
            return WordAvailability(True, "available")

        def convert(self, docx_path, pdf_path, on_attempt=None):
            certificate_text = "\n".join(p.text for p in Document(docx_path).paragraphs)
            assert "Chen Wei" in certificate_text or "Li Ming" in certificate_text
            width = 613 if "Chen Wei" in certificate_text else 614
            writer = PdfWriter()
            writer.add_blank_page(width=width, height=792)
            with pdf_path.open("wb") as output:
                writer.write(output)

    template_path = docx_factory(paragraph_runs=[["{{FULL_NAME}}"], ["{{AWARD}}"]])
    services = _services(tmp_path, template_path)
    services.batch_generator = BatchGenerator(
        Converter(), batch_id_factory=lambda: "20260922-120000-abcd1234"
    )
    opened = []
    services.open_path = lambda path: opened.append(Path(path)) or True
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.show()
    window.new_project()
    window.data_page.set_dataset(_dataset())
    qtbot.mouseClick(window.data_page.continue_button, Qt.MouseButton.LeftButton)
    window.template_page.set_inspection(inspect_template(template_path))
    qtbot.mouseClick(window.template_page.continue_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.template_health_page.continue_button, Qt.MouseButton.LeftButton)
    window.match_page.cards["FULL_NAME"].set_column("Name")
    window.match_page.cards["AWARD"].set_column("Award")
    qtbot.mouseClick(window.match_page.continue_button, Qt.MouseButton.LeftButton)
    _finish_layout_review(window, qtbot)
    qtbot.mouseClick(window.review_page.continue_button, Qt.MouseButton.LeftButton)
    destination = tmp_path / "batches"
    destination.mkdir()
    window.output_page.docx.setChecked(False)
    window.output_page.individual_pdf.setChecked(False)
    window.output_page.combined_pdf.setChecked(True)
    window.output_page.set_order(("row-2", "row-1"))
    window.output_page.destination.setText(str(destination))
    window.output_page.batch_name.setText("Awards")
    qtbot.mouseClick(window.output_page.continue_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.results_page.generate_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: window.results_page.state == "published", timeout=10000)
    qtbot.waitUntil(lambda: window._thread is None)
    result = window.results_page.result
    assert result.combined_pdf_path == result.output_dir / "Awards.pdf"
    assert [p.name for p in result.output_dir.glob("*.pdf")] == ["Awards.pdf"]
    assert not list(result.output_dir.glob("*.docx"))
    assert [float(page.mediabox.width) for page in PdfReader(result.combined_pdf_path).pages] == [613, 614]
    manifest = json.loads((result.output_dir / "manifest.json").read_text("utf-8"))
    assert manifest["ordered_row_ids"] == ["row-2", "row-1"]
    assert "Awards.pdf" in window.results_page.status_label.text()
    assert str(result.combined_pdf_path) in window.results_page.status_label.text()
    qtbot.mouseClick(window.results_page.open_combined_button, Qt.MouseButton.LeftButton)
    assert opened == [result.combined_pdf_path]


def test_issue_action_focuses_exact_table_cell(qtbot, tmp_path, docx_factory):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.new_project()
    window.data_page.set_dataset(_dataset())

    window.review_page.activate_issue("row-2", "award")

    assert window.current_step == "data"
    assert window.data_page.current_cell_ids() == ("row-2", "award")


def test_warning_acknowledgement_is_bound_to_dataset_revision(qtbot, tmp_path, docx_factory):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.new_project()
    window.data_page.set_dataset(_dataset())
    window.review_page.acknowledge_warnings()
    assert window.project_state.warning_ack_revision == 0

    window.data_page.model.setData(window.data_page.model.index(0, 0), "Changed")

    assert window.project_state.warning_ack_revision is None


def test_result_actions_disabled_until_atomic_publication(qtbot, tmp_path, docx_factory):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)

    window.results_page.set_running()

    assert not window.results_page.open_output_button.isEnabled()
    assert not window.results_page.open_manifest_button.isEnabled()


def test_mapping_page_exposes_explicit_formatted_date_source(qtbot, tmp_path):
    services = _services(tmp_path, tmp_path / "unused.docx")
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.match_page.set_context(_dataset(), ("DATE",))
    card = window.match_page.cards["DATE"]

    card.type_combo.setCurrentIndex(card.type_combo.findData("formatted_date"))
    card.set_column("Award")
    card.type_combo.setCurrentIndex(card.type_combo.findData("formatted_date"))
    card.input_format.setText("%Y-%m-%d")
    card.output_format.setText("%d %B %Y")

    source = window.match_page.mapping_plan().sources["DATE"]
    assert isinstance(source, FormattedDateValue)
    assert source.input_format == "%Y-%m-%d"


def test_custom_template_field_needs_no_code_change_and_mapping_stays_simple(
    qtbot, tmp_path, docx_factory
):
    template = inspect_template(
        docx_factory(paragraph_runs=[["Employee ID: {{EMPLOYEE_ID}}"]])
    )
    services = _services(tmp_path, template.path)
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.template_page.set_inspection(template)
    window.match_page.set_context(_dataset(), template.names)

    assert "{{EMPLOYEE_ID}}" in window.template_page.placeholder_list.item(0).text()
    assert "{{FIELD_NAME}}" in window.template_page.field_guide.text()
    assert "EMPLOYEE_ID" in window.match_page.cards
    assert "{{FIELD_NAME}}" in window.match_page.explanation.text()

    card = window.match_page.cards["EMPLOYEE_ID"]
    assert card.input_format.isHidden()
    assert card.output_format.isHidden()
    card.type_combo.setCurrentIndex(card.type_combo.findData("formatted_date"))
    assert not card.input_format.isHidden()
    assert not card.output_format.isHidden()
    assert "2026-09-22" in card.input_format_label.text()
    assert "22 September 2026" in card.output_format_label.text()


def test_generation_rejects_template_changed_after_review(qtbot, tmp_path, docx_factory):
    template_path = docx_factory(paragraph_runs=[["{{FULL_NAME}}"]])
    services = _services(tmp_path, template_path)
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    dataset = _dataset()
    inspection = inspect_template(template_path)
    window.project_state = window.project_state.__class__(
        dataset=dataset,
        template=inspection,
        plan=MappingPlan({"FULL_NAME": ColumnValue("name")}),
        outputs=OutputOptions(True, False, False, tmp_path / "out", "Batch", dataset.order),
    )
    template_path.write_bytes(template_path.read_bytes() + b"changed")

    window.start_generation()

    assert window._thread is None
    assert window.banner.issue_code == "validation.template_changed"


def test_delimited_source_card_imports_only_after_preview_acceptance(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services.inspect_delimited = lambda _path: SimpleNamespace(
        encoding="utf-8",
        delimiter=",",
        encoding_candidates=("utf-8",),
        delimiter_candidates=(",",),
    )
    dataset = _dataset()
    services.import_delimited = lambda _path, _encoding, _delimiter: dataset
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    captured = []
    monkeypatch.setattr(
        window,
        "_confirm_import",
        lambda imported, **details: captured.append((imported, details)),
    )

    window._import_delimited_file(tmp_path / "people.csv")

    assert captured[0][0] is dataset
    assert captured[0][1]["encoding"] == "utf-8"


def test_clipboard_source_card_uses_offline_clipboard_adapter(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services.inspect_clipboard = lambda _text: SimpleNamespace(
        mode="tabs", mode_candidates=("tabs",)
    )
    dataset = _dataset()
    services.import_clipboard = lambda _text, _mode: dataset
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    captured = []
    monkeypatch.setattr(window, "_confirm_import", lambda imported, **_details: captured.append(imported))
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText("Name\tAward\nLi Ming\tGold")

    window._paste_source()

    assert captured == [dataset]


def test_source_buttons_dispatch_manual_excel_and_text_imports(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services.create_manual_dataset = lambda _labels: _dataset()
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(window, "_import_excel_file", lambda path: calls.append(("excel", path)))
    monkeypatch.setattr(window, "_import_delimited_file", lambda path: calls.append(("text", path)))
    choices = iter(((str(tmp_path / "people.xlsx"), ""), (str(tmp_path / "people.csv"), "")))
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QFileDialog.getOpenFileName",
        lambda *_args: next(choices),
    )

    window._import_source("manual")
    window._import_source("excel")
    window._import_source("delimited")

    assert window.data_page.model.dataset == _dataset()
    assert calls == [
        ("excel", tmp_path / "people.xlsx"),
        ("text", tmp_path / "people.csv"),
    ]


def test_excel_import_requires_sheet_and_hidden_data_decisions(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    first = SimpleNamespace(
        sheet_name="One",
        sheet_names=("One", "Two"),
        requires_hidden_data_choice=False,
    )
    chosen = SimpleNamespace(
        sheet_name="Two",
        sheet_names=("One", "Two"),
        requires_hidden_data_choice=True,
    )
    services.inspect_excel = lambda _path, sheet=None: chosen if sheet else first
    imports = []
    services.import_excel = lambda path, sheet, **options: imports.append(
        (path, sheet, options)
    ) or _dataset()
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    previews = []
    monkeypatch.setattr(window, "_confirm_import", lambda dataset, **details: previews.append(details))
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QInputDialog.getItem",
        lambda *_args: ("Two", True),
    )
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QMessageBox.question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    window._import_excel_file(tmp_path / "people.xlsx")

    assert imports[0][1:] == ("Two", {"include_hidden": True})
    assert previews[0]["hidden_policy"] == "included"


def test_ambiguous_text_and_clipboard_choices_are_explicit(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services.inspect_delimited = lambda _path: SimpleNamespace(
        encoding=None,
        delimiter=None,
        encoding_candidates=("utf-8", "cp1251"),
        delimiter_candidates=("\t", ","),
    )
    services.import_delimited = lambda *_args: _dataset()
    services.inspect_clipboard = lambda _text: SimpleNamespace(
        mode=None, mode_candidates=("tabs", "csv")
    )
    services.import_clipboard = lambda *_args: _dataset()
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    previews = []
    monkeypatch.setattr(window, "_confirm_import", lambda dataset, **details: previews.append(details))
    answers = iter((("utf-8", True), ("tab", True), ("tabs", True)))
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QInputDialog.getItem",
        lambda *_args: next(answers),
    )
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText("Name\tAward\nLi\tGold")

    window._import_delimited_file(tmp_path / "people.txt")
    window._paste_source()

    assert previews[0]["delimiter"] == "TAB"
    assert previews[1]["delimiter"] == "TAB"


def test_import_preview_accepts_snapshot_and_errors_preserve_current_data(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.ImportPreviewDialog.exec",
        lambda _dialog: 1,
    )

    window._confirm_import(
        _dataset(), encoding="UTF-8", delimiter=",", worksheet="—", hidden_policy="—"
    )
    window._show_import_error(SimpleNamespace(code="import.failed", parameters={}))

    assert window.data_page.model.dataset == _dataset()
    assert window.banner.issue_code == "import.failed"


def test_preview_failures_and_published_result_links_stay_inside_verified_paths(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    opened = []
    services.open_path = lambda path: opened.append(path) or True
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    errors = []
    monkeypatch.setattr(window.review_page, "show_preview_error", errors.append)
    window._generate_preview("row-1")
    assert errors

    services.preview_service = SimpleNamespace(generate=lambda *_args: (_ for _ in ()).throw(RuntimeError("preview failed")), clear=lambda: None)
    window.project_state = window.project_state.__class__(
        dataset=_dataset(), template=inspect_template(services.template), plan=MappingPlan({"FULL_NAME": ColumnValue("name")})
    )
    window._generate_preview("row-1")
    assert errors[-1] == "preview failed"

    output = tmp_path / "published-links"
    output.mkdir()
    for name in ("manifest.json", "batch_summary.html", "Awards.pdf"):
        (output / name).write_bytes(b"x")
    window.results_page.set_published(
        BatchResult(
            BatchState.PUBLISHED,
            output,
            2,
            combined_pdf_path=output / "Awards.pdf",
        )
    )
    window._open_published_output()
    window._open_result_file("manifest.json")
    window._open_combined_output()

    assert opened == [output, output / "manifest.json", output / "Awards.pdf"]


def test_saved_project_and_home_file_actions_restore_local_workflow(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    services = _services(tmp_path, docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    draft = tmp_path / "draft.certproject"
    project = ProjectState(4, _dataset(), locale="ru", active_step="template")
    ProjectStore.create(draft).save(project)
    settings = QSettings(str(tmp_path / "home.ini"), QSettings.Format.IniFormat)
    window = WorkspaceWindow(services, settings=settings)
    qtbot.addWidget(window)
    window.show()
    window.load_project(draft)

    assert window.current_step == "template"
    assert window.catalogs.locale == "ru"
    window._show_home()
    assert window.home.project_label(0).text().startswith(draft.name)
    qtbot.mouseClick(window.home._project_widgets[0][2], Qt.MouseButton.LeftButton)
    assert window.current_step == "template"
    monkeypatch.setattr(
        "certificate_automation.ui.workspace.QFileDialog.getOpenFileName",
        lambda *_args: (str(draft), ""),
    )
    window._show_home()
    qtbot.mouseClick(window.home.open_project_button, Qt.MouseButton.LeftButton)
    assert window.state.project_path == draft
    window._show_home()
    window._recover_draft()
    assert window.state.project_path == draft


def test_navigation_and_generation_guards_explain_stale_or_invalid_state(
    qtbot, tmp_path, docx_factory
):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services = _services(tmp_path, template.path)
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.navigate("unknown")
    window.navigate("generate")
    assert window.current_step == "data"
    window.start_generation()
    assert window.banner.issue_code == "navigation.complete_previous"

    dataset = _dataset()
    options = OutputOptions(True, False, False, tmp_path / "out", "Batch", dataset.order)
    window.project_state = window.project_state.__class__(
        dataset=dataset,
        template=template,
        plan=MappingPlan({"FULL_NAME": ColumnValue("name")}),
        outputs=options,
    )
    window._layout_review_key = TemplateHealthService.revision_key(
        dataset, template, window.project_state.plan
    )
    services.validate = lambda *_args: ValidationReport((), {}, 0, dataset.revision + 1, template.sha256)
    window.start_generation()
    assert window.banner.issue_code == "validation.revision_changed"

    issue = Issue(Severity.ERROR, "dataset", "validation.no_recipients")
    services.validate = lambda *_args: ValidationReport((issue,), {}, 0, dataset.revision, template.sha256)
    window.start_generation()
    assert window.current_step == "review"
    assert window.review_page.issue_list.count() == 1


def test_successful_preview_and_cleanup_use_only_preview_service(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services = _services(tmp_path, template.path)
    pdf = tmp_path / "preview.pdf"
    pdf.write_bytes(b"pdf")
    cleared = []
    services.preview_service = SimpleNamespace(
        generate=lambda *_args: SimpleNamespace(pdf_path=pdf),
        clear=lambda: cleared.append(True),
    )
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.project_state = window.project_state.__class__(
        dataset=_dataset(),
        template=template,
        plan=MappingPlan({"FULL_NAME": ColumnValue("name")}),
    )
    shown = []
    monkeypatch.setattr(window.review_page, "set_preview", shown.append)

    window._generate_preview("row-1")
    window.close()

    assert shown == [pdf]
    assert cleared == [True]


def test_displayed_pdf_is_unloaded_before_preview_regeneration(
    qtbot, tmp_path, docx_factory, monkeypatch
):
    template = inspect_template(docx_factory(paragraph_runs=[["{{FULL_NAME}}"]]))
    services = _services(tmp_path, template.path)
    pdf = tmp_path / "replacement.pdf"
    pdf.write_bytes(b"pdf")
    events = []
    services.preview_service = SimpleNamespace(
        generate=lambda *_args: events.append("generate")
        or SimpleNamespace(pdf_path=pdf),
        clear=lambda: None,
    )
    window = WorkspaceWindow(services)
    qtbot.addWidget(window)
    window.project_state = window.project_state.__class__(
        dataset=_dataset(),
        template=template,
        plan=MappingPlan({"FULL_NAME": ColumnValue("name")}),
    )
    monkeypatch.setattr(
        window.review_page,
        "clear_preview",
        lambda: events.append("unload"),
        raising=False,
    )
    monkeypatch.setattr(window.review_page, "set_preview", lambda _path: events.append("show"))

    window._generate_preview("row-1")

    assert events == ["unload", "generate", "show"]
