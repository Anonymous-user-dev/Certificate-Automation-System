"""First-time-friendly home screen and guided certificate workspace."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QSettings, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.batch import BatchRequest, CancellationToken
from certificate_automation.i18n import CatalogSet, SUPPORTED_LOCALES, package_root
from certificate_automation.mapping import MappingPlan
from certificate_automation.output_options import OutputOptions
from certificate_automation.project import ProjectStore
from certificate_automation.ui.data_page import DataPage, ImportPreviewDialog
from certificate_automation.ui.match_page import MatchPage
from certificate_automation.ui.output_page import OutputPage
from certificate_automation.ui.results_page import ResultsPage
from certificate_automation.ui.review_page import ReviewPage
from certificate_automation.ui.template_page import TemplatePage
from certificate_automation.ui.theme import application_stylesheet
from certificate_automation.ui.worker import GenerationWorker


STEP_IDS = ("data", "template", "mapping", "review", "output", "generate")
STEP_KEYS = {
    "data": "nav.data",
    "template": "nav.template",
    "mapping": "nav.mapping",
    "review": "nav.review",
    "output": "nav.output",
    "generate": "nav.generate",
}


@dataclass(frozen=True, slots=True)
class WorkspaceState:
    current_step: str = "data"
    completed_steps: tuple[str, ...] = ()
    project_path: Path | None = None
    project_revision: int = 0


@dataclass(frozen=True, slots=True)
class OperatorProjectState:
    dataset: TabularDataset | None = None
    template: object | None = None
    plan: MappingPlan | None = None
    outputs: OutputOptions | None = None
    warning_ack_revision: int | None = None


class HomePage(QWidget):
    new_batch_requested = Signal()
    continue_draft_requested = Signal()
    recover_requested = Signal()
    open_results_requested = Signal()

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.subtitle = QLabel()
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        self.new_batch_button = QPushButton()
        self.new_batch_button.setProperty("role", "primary")
        self.continue_draft_button = QPushButton()
        self.recover_button = QPushButton()
        self.open_results_button = QPushButton()
        card = QFrame()
        card.setProperty("role", "surface")
        card_layout = QVBoxLayout(card)
        for button in (
            self.new_batch_button,
            self.continue_draft_button,
            self.recover_button,
            self.open_results_button,
        ):
            card_layout.addWidget(button)
        card_layout.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 56, 64, 56)
        layout.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addSpacing(24)
        layout.addWidget(card)
        layout.addStretch(2)
        self.new_batch_button.clicked.connect(self.new_batch_requested)
        self.continue_draft_button.clicked.connect(self.continue_draft_requested)
        self.recover_button.clicked.connect(self.recover_requested)
        self.open_results_button.clicked.connect(self.open_results_requested)
        self.retranslate()

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("home.title"))
        self.subtitle.setText(self._catalogs.text("home.subtitle"))
        controls = (
            (self.new_batch_button, "home.new_batch"),
            (self.continue_draft_button, "home.continue_draft"),
            (self.recover_button, "home.recover"),
            (self.open_results_button, "home.open_results"),
        )
        for control, key in controls:
            text = self._catalogs.text(key)
            control.setText(text)
            control.setAccessibleName(text)


class StepRail(QFrame):
    step_requested = Signal(str)
    EXPANDED_WIDTH = 280

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "surface")
        self._catalogs = catalogs
        self._compact = False
        self._current = "data"
        self._completed: set[str] = set()
        self._buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        for index, step in enumerate(STEP_IDS, start=1):
            button = QPushButton()
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, selected=step: self.step_requested.emit(selected)
            )
            self._buttons[step] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.retranslate()

    @property
    def is_compact(self) -> bool:
        return self._compact

    def button_for(self, step: str) -> QPushButton:
        return self._buttons[step]

    def text_for(self, step: str) -> str:
        return self._catalogs.text(STEP_KEYS[step])

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedWidth(76 if compact else self.EXPANDED_WIDTH)
        self._refresh_buttons()

    def set_state(self, current: str, completed: tuple[str, ...]) -> None:
        self._current = current
        self._completed = set(completed)
        self._refresh_buttons()

    def retranslate(self) -> None:
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        for index, step in enumerate(STEP_IDS, start=1):
            text = self.text_for(step)
            button = self._buttons[step]
            button.setText(str(index) if self._compact else f"{index}. {text}")
            button.setAccessibleName(text)
            state = (
                "current"
                if step == self._current
                else "complete"
                if step in self._completed
                else "pending"
            )
            button.setProperty("stepState", state)
            button.setChecked(step == self._current)
            button.style().unpolish(button)
            button.style().polish(button)


class ContextBanner(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("bannerState", "error")
        self.issue_code: str | None = None
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setProperty("state", "error")
        layout = QHBoxLayout(self)
        layout.addWidget(self.label)
        self.hide()

    def show_issue(self, code: str, text: str) -> None:
        self.issue_code = code
        self.label.setText(text)
        self.show()

    def clear(self) -> None:
        self.issue_code = None
        self.label.clear()
        self.hide()


class WorkspaceWindow(QMainWindow):
    """Own the home page, stable workspace state, and safe step navigation."""

    def __init__(self, services, parent=None, *, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.settings = settings or QSettings()
        configured_locale = str(self.settings.value("locale", "en"))
        supplied = getattr(services, "catalogs", None)
        self.catalogs = supplied or CatalogSet.load(package_root(), configured_locale)
        if self.catalogs.locale != configured_locale:
            self.catalogs.set_locale(configured_locale)
        self.state = WorkspaceState()
        self.project_state = OperatorProjectState()
        self._page_by_step: dict[str, QWidget] = {}
        self._last_issue_code: str | None = None
        self._thread: QThread | None = None
        self._worker = None
        self.cancellation: CancellationToken | None = None
        self._close_when_idle = False

        self.home = HomePage(self.catalogs)
        self.root_stack = QStackedWidget()
        self.root_stack.addWidget(self.home)
        self.workspace_surface = self._build_workspace()
        self.root_stack.addWidget(self.workspace_surface)
        self.setCentralWidget(self.root_stack)
        self.resize(1120, 760)
        self.setMinimumSize(620, 520)
        self.setStyleSheet(application_stylesheet())

        self.home.new_batch_requested.connect(self.new_project)
        self.home.continue_draft_requested.connect(self._continue_draft)
        self.home.recover_requested.connect(self._recover_draft)
        self.home.open_results_requested.connect(self._open_results)
        self.step_rail.step_requested.connect(self.navigate)
        self.back_button.clicked.connect(self._go_back)
        self.next_button.clicked.connect(self._go_next)
        self.locale_selector.currentIndexChanged.connect(self._locale_selected)
        self.data_page.dataset_accepted.connect(self._accept_data)
        self.data_page.import_requested.connect(self._import_source)
        self.data_page.paste_requested.connect(self._paste_source)
        self.data_page.model.dataset_changed.connect(self._data_changed)
        self.template_page.template_selected.connect(self._select_template)
        self.template_page.inspection_accepted.connect(self._accept_template)
        self.match_page.plan_accepted.connect(self._accept_plan)
        self.review_page.review_accepted.connect(self._accept_review)
        self.review_page.issue_activated.connect(self._focus_issue)
        self.review_page.warnings_acknowledged.connect(self._acknowledge_warnings)
        self.review_page.preview_requested.connect(self._generate_preview)
        self.output_page.options_accepted.connect(self._accept_outputs)
        self.results_page.generate_requested.connect(self.start_generation)
        self.results_page.cancel_requested.connect(self._request_cancel)
        self.results_page.open_output_requested.connect(self._open_published_output)
        self.results_page.open_combined_requested.connect(self._open_combined_output)
        self.results_page.open_summary_requested.connect(
            lambda: self._open_result_file("batch_summary.html")
        )
        self.results_page.open_manifest_requested.connect(
            lambda: self._open_result_file("manifest.json")
        )
        self.catalogs.subscribe(self._locale_changed)
        self.retranslate()
        self._ensure_accessible_names()
        self._show_home()

    @property
    def current_step(self) -> str:
        return self.state.current_step

    def _build_workspace(self) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(12)

        top = QFrame()
        top.setProperty("role", "surface")
        top_layout = QHBoxLayout(top)
        self.product_label = QLabel()
        self.product_label.setProperty("role", "title")
        self.draft_label = QLabel()
        self.draft_label.setProperty("role", "muted")
        self.save_state_label = QLabel()
        self.save_state_label.setProperty("role", "muted")
        self.locale_label = QLabel()
        self.locale_selector = QComboBox()
        for code, label in (("en", "English"), ("zh_CN", "简体中文"), ("ru", "Русский")):
            self.locale_selector.addItem(label, code)
        top_layout.addWidget(self.product_label)
        top_layout.addWidget(self.draft_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.save_state_label)
        top_layout.addWidget(self.locale_label)
        top_layout.addWidget(self.locale_selector)
        outer.addWidget(top)

        self.banner = ContextBanner()
        outer.addWidget(self.banner)

        body = QHBoxLayout()
        self.step_rail = StepRail(self.catalogs)
        self.step_rail.setFixedWidth(StepRail.EXPANDED_WIDTH)
        body.addWidget(self.step_rail)
        self.page_stack = QStackedWidget()
        self.data_page = DataPage(self.catalogs)
        self._page_by_step["data"] = self.data_page
        self.page_stack.addWidget(self.data_page)
        self.template_page = TemplatePage(self.catalogs)
        self.match_page = MatchPage(self.catalogs)
        self.review_page = ReviewPage(self.catalogs)
        self.output_page = OutputPage(self.catalogs)
        self.results_page = ResultsPage(self.catalogs)
        pages = {
            "template": self.template_page,
            "mapping": self.match_page,
            "review": self.review_page,
            "output": self.output_page,
            "generate": self.results_page,
        }
        for step, page in pages.items():
            self._page_by_step[step] = page
            self.page_stack.addWidget(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.page_stack)
        body.addWidget(scroll, 1)
        outer.addLayout(body, 1)

        bottom = QFrame()
        bottom.setProperty("role", "surface")
        bottom_layout = QHBoxLayout(bottom)
        self.back_button = QPushButton()
        self.next_button = QPushButton()
        self.next_button.setProperty("role", "primary")
        bottom_layout.addWidget(self.back_button)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.next_button)
        outer.addWidget(bottom)
        return container

    def new_project(self) -> None:
        dataset = TabularDataset(
            (Column("column-1", self.catalogs.text("data.default_column")),),
            (DataRow("row-1", None, {"column-1": ""}),),
            SourceSnapshot(
                "manual",
                self.catalogs.text("data.manual_source"),
                None,
                "0" * 64,
                datetime.now(timezone.utc),
            ),
        )
        self.data_page.set_dataset(dataset)
        self.state = WorkspaceState(current_step="data")
        self.project_state = OperatorProjectState(dataset=dataset)
        self.banner.clear()
        self.root_stack.setCurrentWidget(self.workspace_surface)
        self._show_step("data")

    def open_project(self, path: Path) -> None:
        opener = getattr(self.services, "open_project", None)
        store = opener(Path(path)) if callable(opener) else ProjectStore.open(Path(path))
        project = store.load()
        self.data_page.set_dataset(project.dataset)
        self.project_state = OperatorProjectState(dataset=project.dataset)
        self.state = WorkspaceState(
            current_step=project.active_step if project.active_step in STEP_IDS else "data",
            completed_steps=tuple(
                step for step in STEP_IDS if STEP_IDS.index(step) < STEP_IDS.index(project.active_step)
            ) if project.active_step in STEP_IDS else (),
            project_path=Path(path),
            project_revision=project.revision,
        )
        self._remember_project(Path(path))
        self.set_locale(project.locale)
        self.root_stack.setCurrentWidget(self.workspace_surface)
        self._show_step(self.state.current_step)

    def set_locale(self, locale: str) -> None:
        self.catalogs.set_locale(locale)
        self.settings.setValue("locale", self.catalogs.locale)
        index = self.locale_selector.findData(self.catalogs.locale)
        if index >= 0 and index != self.locale_selector.currentIndex():
            self.locale_selector.blockSignals(True)
            self.locale_selector.setCurrentIndex(index)
            self.locale_selector.blockSignals(False)

    def navigate(self, step: str) -> None:
        if step not in STEP_IDS:
            return
        target = STEP_IDS.index(step)
        first_incomplete = next(
            (
                index
                for index, candidate in enumerate(STEP_IDS)
                if candidate not in self.state.completed_steps
            ),
            len(STEP_IDS) - 1,
        )
        if target > first_incomplete:
            required = STEP_IDS[first_incomplete]
            code = (
                "navigation.complete_data_first"
                if required == "data"
                else "navigation.complete_previous"
            )
            self.banner.show_issue(code, self.catalogs.text(code))
            self._show_step(required)
            return
        self.banner.clear()
        self._show_step(step)

    def mark_step_complete(self, step: str) -> None:
        if step not in STEP_IDS:
            return
        completed = tuple(
            candidate
            for candidate in STEP_IDS
            if candidate in set(self.state.completed_steps) | {step}
        )
        self.state = replace(self.state, completed_steps=completed)
        self.step_rail.set_state(self.current_step, completed)

    def retranslate(self) -> None:
        self.setWindowTitle(self.catalogs.text("app.title"))
        self.home.retranslate()
        self.product_label.setText(self.catalogs.text("app.title"))
        self.draft_label.setText(self.catalogs.text("workspace.untitled"))
        self.save_state_label.setText(self.catalogs.text("workspace.saved"))
        self.locale_label.setText(self.catalogs.text("workspace.language"))
        self.locale_selector.setAccessibleName(self.catalogs.text("workspace.language"))
        self.back_button.setText(self.catalogs.text("action.back"))
        self.back_button.setAccessibleName(self.catalogs.text("action.back"))
        self.next_button.setText(self.catalogs.text("action.continue"))
        self.next_button.setAccessibleName(self.catalogs.text("action.continue"))
        self.step_rail.retranslate()
        if self.banner.issue_code:
            self.banner.show_issue(
                self.banner.issue_code,
                self.catalogs.text(self.banner.issue_code),
            )
        self._ensure_accessible_names()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "step_rail"):
            self.step_rail.set_compact(event.size().width() < 760)

    def _show_home(self) -> None:
        self.root_stack.setCurrentWidget(self.home)

    def _show_step(self, step: str) -> None:
        self.state = replace(self.state, current_step=step)
        self.page_stack.setCurrentWidget(self._page_by_step[step])
        self.step_rail.set_state(step, self.state.completed_steps)
        index = STEP_IDS.index(step)
        self.back_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(STEP_IDS) - 1)

    def _accept_data(self, _dataset: TabularDataset) -> None:
        self.project_state = replace(self.project_state, dataset=_dataset)
        self.mark_step_complete("data")
        self.navigate("template")

    def _import_source(self, kind: str) -> None:
        if kind == "manual":
            creator = getattr(self.services, "create_manual_dataset", None)
            if callable(creator):
                self.data_page.set_dataset(
                    creator((self.catalogs.text("data.default_column"),))
                )
            return
        if kind == "excel":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                self.catalogs.text("import.excel"),
                "",
                "Excel (*.xlsx)",
            )
            if selected:
                self._import_excel_file(Path(selected))
            return
        if kind == "delimited":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                self.catalogs.text("import.csv"),
                "",
                "CSV / TSV (*.csv *.tsv *.txt)",
            )
            if selected:
                self._import_delimited_file(Path(selected))

    def _import_excel_file(self, path: Path) -> None:
        try:
            inspect = self.services.inspect_excel(path)
            sheet = inspect.sheet_name
            if len(inspect.sheet_names) > 1:
                sheet, accepted = QInputDialog.getItem(
                    self,
                    self.catalogs.text("import.excel"),
                    self.catalogs.text("import.excel.worksheet"),
                    inspect.sheet_names,
                    inspect.sheet_names.index(sheet),
                    False,
                )
                if not accepted:
                    return
                inspect = self.services.inspect_excel(path, sheet)
            include_hidden = False
            if inspect.requires_hidden_data_choice:
                answer = QMessageBox.question(
                    self,
                    self.catalogs.text("import.excel"),
                    self.catalogs.text("import.excel.hidden_choice"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                include_hidden = answer == QMessageBox.StandardButton.Yes
            dataset = self.services.import_excel(
                path,
                inspect.sheet_name,
                include_hidden=include_hidden,
            )
            self._confirm_import(
                dataset,
                encoding="—",
                delimiter="—",
                worksheet=inspect.sheet_name,
                hidden_policy=("included" if include_hidden else "excluded"),
            )
        except Exception as error:
            self._show_import_error(error)

    def _import_delimited_file(self, path: Path) -> None:
        try:
            inspect = self.services.inspect_delimited(path)
            encoding = inspect.encoding
            delimiter = inspect.delimiter
            if encoding is None:
                encoding, accepted = QInputDialog.getItem(
                    self,
                    self.catalogs.text("import.csv"),
                    self.catalogs.text("import.encoding"),
                    inspect.encoding_candidates,
                    0,
                    False,
                )
                if not accepted:
                    return
            if delimiter is None:
                labels = {",": "comma (,)", "\t": "tab", ";": "semicolon (;)"}
                choices = tuple(labels[item] for item in inspect.delimiter_candidates)
                choice, accepted = QInputDialog.getItem(
                    self,
                    self.catalogs.text("import.csv"),
                    self.catalogs.text("import.delimiter"),
                    choices,
                    0,
                    False,
                )
                if not accepted:
                    return
                delimiter = next(item for item, label in labels.items() if label == choice)
            dataset = self.services.import_delimited(path, encoding, delimiter)
            self._confirm_import(
                dataset,
                encoding=str(encoding),
                delimiter="TAB" if delimiter == "\t" else str(delimiter),
                worksheet="—",
                hidden_policy="—",
            )
        except Exception as error:
            self._show_import_error(error)

    def _paste_source(self) -> None:
        try:
            text = QApplication.clipboard().text()
            inspect = self.services.inspect_clipboard(text)
            mode = inspect.mode
            if mode is None:
                mode, accepted = QInputDialog.getItem(
                    self,
                    self.catalogs.text("import.clipboard"),
                    self.catalogs.text("import.clipboard.mode"),
                    inspect.mode_candidates,
                    0,
                    False,
                )
                if not accepted:
                    return
            dataset = self.services.import_clipboard(text, mode)
            self._confirm_import(
                dataset,
                encoding="UTF-8",
                delimiter="TAB" if mode == "tabs" else ",",
                worksheet="—",
                hidden_policy="—",
            )
        except Exception as error:
            self._show_import_error(error)

    def _confirm_import(
        self,
        dataset: TabularDataset,
        *,
        encoding: str,
        delimiter: str,
        worksheet: str,
        hidden_policy: str,
    ) -> None:
        rows = (tuple(column.label for column in dataset.columns),) + tuple(
            tuple(row.value(column.column_id) for column in dataset.columns)
            for row in dataset.rows[:9]
        )
        dialog = ImportPreviewDialog(self.catalogs, self)
        dialog.set_preview(
            rows=rows,
            encoding=encoding,
            delimiter=delimiter,
            worksheet=worksheet,
            hidden_policy=hidden_policy,
        )
        if dialog.exec():
            self.data_page.set_dataset(dataset)

    def _show_import_error(self, error: Exception) -> None:
        code = getattr(error, "code", "import.failed")
        parameters = dict(getattr(error, "parameters", {}))
        self.banner.show_issue(code, self.catalogs.text(code, **parameters))

    def _data_changed(self, _dataset: TabularDataset) -> None:
        if not hasattr(self, "save_state_label"):
            return
        completed = tuple(step for step in self.state.completed_steps if step == "data")
        self.project_state = replace(
            self.project_state,
            dataset=_dataset,
            plan=None,
            outputs=None,
            warning_ack_revision=None,
        )
        self.state = replace(
            self.state,
            completed_steps=completed,
            project_revision=self.state.project_revision + 1,
        )
        self.save_state_label.setText(self.catalogs.text("workspace.unsaved"))

    def _select_template(self, path: Path) -> None:
        try:
            inspection = self.services.inspect_template(Path(path))
        except Exception as error:
            self.template_page.show_template_error(
                getattr(error, "code", "template.invalid")
            )
            return
        self.template_page.set_inspection(inspection)

    def _accept_template(self, inspection) -> None:
        self.project_state = replace(
            self.project_state,
            template=inspection,
            plan=None,
            outputs=None,
            warning_ack_revision=None,
        )
        self.match_page.set_context(
            self.project_state.dataset,
            inspection.names,
        )
        self.mark_step_complete("template")
        self.navigate("mapping")

    def _accept_plan(self, plan: MappingPlan) -> None:
        self.project_state = replace(
            self.project_state,
            plan=plan,
            outputs=None,
            warning_ack_revision=None,
        )
        self.review_page.set_context(self.project_state.dataset, plan)
        self.mark_step_complete("mapping")
        self.navigate("review")

    def _accept_review(self) -> None:
        self.output_page.set_order(self.project_state.dataset.order)
        availability = getattr(self.services, "word_availability", None)
        if callable(availability):
            self.output_page.set_word_availability(availability())
        self.mark_step_complete("review")
        self.navigate("output")

    def _accept_outputs(self, outputs: OutputOptions) -> None:
        self.project_state = replace(self.project_state, outputs=outputs)
        self.mark_step_complete("output")
        self.navigate("generate")

    def _focus_issue(self, row_id: str, column_id: str) -> None:
        self._show_step("data")
        self.data_page.focus_cell(row_id, column_id)

    def _acknowledge_warnings(self) -> None:
        dataset = self.project_state.dataset
        self.project_state = replace(
            self.project_state,
            warning_ack_revision=dataset.revision if dataset else None,
        )

    def _generate_preview(self, row_id: str) -> None:
        current = self.project_state
        service = getattr(self.services, "preview_service", None)
        if service is None or not all((current.dataset, current.template, current.plan)):
            self.review_page.show_preview_error(
                self.catalogs.text("review.preview_unavailable")
            )
            return
        try:
            record = service.generate(
                current.dataset,
                row_id,
                current.template,
                current.plan,
            )
        except Exception as error:
            self.review_page.show_preview_error(str(error))
            return
        self.review_page.set_preview(record.pdf_path)

    def start_generation(self) -> None:
        if self._thread is not None:
            return
        current = self.project_state
        if not all((current.dataset, current.template, current.plan, current.outputs)):
            self.banner.show_issue(
                "navigation.complete_previous",
                self.catalogs.text("navigation.complete_previous"),
            )
            return
        report = self.services.validate(
            current.dataset,
            current.template,
            current.plan,
            current.outputs,
        )
        if report.dataset_revision != current.dataset.revision:
            self.banner.show_issue(
                "validation.revision_changed",
                self.catalogs.text("validation.revision_changed"),
            )
            return
        if report.template_sha256 != current.template.sha256:
            self.project_state = replace(
                self.project_state,
                template=None,
                plan=None,
                outputs=None,
                warning_ack_revision=None,
            )
            self.banner.show_issue(
                "validation.template_changed",
                self.catalogs.text("validation.template_changed"),
            )
            self._show_step("template")
            return
        if not report.ready:
            self.review_page.set_issues(report.issues)
            self._show_step("review")
            return
        request = BatchRequest(
            current.dataset,
            current.template,
            current.plan,
            current.outputs,
            self.catalogs.locale,
        )
        self.cancellation = CancellationToken()
        self.results_page.set_running()
        thread = QThread(self)
        worker = GenerationWorker(
            self.services.batch_generator,
            request,
            self.cancellation,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.results_page.update_progress)
        worker.finished.connect(self._generation_finished)
        worker.failed.connect(self._generation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    def _generation_finished(self, result) -> None:
        self.results_page.set_published(result)

    def _generation_failed(self, error) -> None:
        self.results_page.set_failed(error)

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._close_when_idle:
            self._close_when_idle = False
            QTimer.singleShot(0, self.close)

    def _request_cancel(self) -> None:
        if self.cancellation is not None:
            self.cancellation.request()

    def _open_published_output(self) -> None:
        result = getattr(self.results_page, "result", None)
        opener = getattr(self.services, "open_path", None)
        if result and result.output_dir and callable(opener):
            opener(result.output_dir)

    def _open_result_file(self, name: str) -> None:
        result = getattr(self.results_page, "result", None)
        opener = getattr(self.services, "open_path", None)
        path = result.output_dir / name if result and result.output_dir else None
        if path is not None and path.is_file() and callable(opener):
            opener(path)

    def _open_combined_output(self) -> None:
        result = getattr(self.results_page, "result", None)
        outputs = self.project_state.outputs
        opener = getattr(self.services, "open_path", None)
        if result and result.output_dir and outputs and callable(opener):
            path = result.output_dir / f"{outputs.batch_name}.pdf"
            if path.is_file():
                opener(path)

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._close_when_idle = True
            self._request_cancel()
            event.ignore()
            return
        preview_service = getattr(self.services, "preview_service", None)
        if preview_service is not None:
            preview_service.clear()
        event.accept()

    def _go_back(self) -> None:
        index = STEP_IDS.index(self.current_step)
        if index > 0:
            self.navigate(STEP_IDS[index - 1])

    def _go_next(self) -> None:
        index = STEP_IDS.index(self.current_step)
        if index < len(STEP_IDS) - 1:
            self.navigate(STEP_IDS[index + 1])

    def _locale_selected(self, _index: int) -> None:
        locale = self.locale_selector.currentData()
        if locale:
            self.set_locale(str(locale))

    def _locale_changed(self, _locale: str) -> None:
        self.retranslate()

    def _remember_project(self, path: Path) -> None:
        current = self.settings.value("recent_projects", [])
        if isinstance(current, str):
            current = [current]
        recent = [str(path), *(item for item in current if item != str(path))][:8]
        self.settings.setValue("recent_projects", recent)

    def _continue_draft(self) -> None:
        recent = self.settings.value("recent_projects", [])
        if isinstance(recent, str):
            recent = [recent]
        existing = next((Path(item) for item in recent if Path(item).is_file()), None)
        if existing is not None:
            self.open_project(existing)
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self.catalogs.text("home.continue_draft"),
            "",
            self.catalogs.text("file.project_filter"),
        )
        if selected:
            self.open_project(Path(selected))

    def _recover_draft(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self.catalogs.text("home.recover"),
            "",
            self.catalogs.text("file.backup_filter"),
        )
        if selected:
            self.open_project(Path(selected))

    def _open_results(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            self.catalogs.text("home.open_results"),
        )
        opener = getattr(self.services, "open_path", None)
        if selected and callable(opener):
            opener(Path(selected))

    def _ensure_accessible_names(self) -> None:
        seen: set[QWidget] = set()
        for widget_type in (QAbstractButton, QComboBox, QLineEdit, QTableView):
            for widget in self.findChildren(widget_type):
                if widget in seen:
                    continue
                seen.add(widget)
                if widget.accessibleName().strip():
                    continue
                label = widget.text() if isinstance(widget, QAbstractButton) else ""
                widget.setAccessibleName(
                    label or widget.objectName() or type(widget).__name__
                )


# Compatibility name for callers that import the new module directly.
MainWindow = WorkspaceWindow
