from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings, Qt
import pytest

from certificate_automation.batch import BatchResult
from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.domain import BatchState
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.mapping import ColumnValue, FormattedDateValue, MappingPlan
from certificate_automation.output_options import OutputOptions
from certificate_automation.template import inspect_template
from certificate_automation.ui.workspace import WorkspaceWindow
from certificate_automation.validation import validate_preflight
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
    )


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
    window.match_page.cards["FULL_NAME"].set_column("Name")
    window.match_page.cards["AWARD"].set_column("Award")
    qtbot.mouseClick(window.match_page.continue_button, Qt.MouseButton.LeftButton)
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
