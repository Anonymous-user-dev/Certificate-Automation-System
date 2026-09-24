"""First-time-friendly home screen and guided certificate workspace."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import os
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QSettings, QStandardPaths, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
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
from certificate_automation.i18n import CatalogError, CatalogSet, SUPPORTED_LOCALES, package_root
from certificate_automation.mapping import MappingPlan, evaluate_plan
from certificate_automation.profiles import MappingProfile, ProfileError, ProfileStore, compare_profile
from certificate_automation.output_options import OutputOptions
from certificate_automation.project import ProjectCoordinator, ProjectError, ProjectSaveError, ProjectState, ProjectStore
from certificate_automation.project_catalog import ProjectCatalog
from certificate_automation.project_migration import ProjectMigrationService
from certificate_automation.template import Placeholder, TemplateInspection, inspect_template
from certificate_automation.template_health import TemplateHealthService
from certificate_automation.ui.project_home_page import ProjectHomePage
from certificate_automation.ui.data_page import DataPage, ImportPreviewDialog
from certificate_automation.ui.match_page import MatchPage
from certificate_automation.ui.output_page import OutputPage
from certificate_automation.ui.results_page import ResultsPage
from certificate_automation.ui.review_page import ReviewPage
from certificate_automation.ui.template_page import TemplatePage
from certificate_automation.ui.template_health_page import TemplateHealthPage
from certificate_automation.ui.theme import application_stylesheet
from certificate_automation.ui.worker import GenerationWorker


STEP_IDS = ("data", "template", "template_health", "mapping", "review", "output", "generate")
STEP_KEYS = {
    "data": "nav.data",
    "template": "nav.template",
    "template_health": "nav.template_health",
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


class SaveState(str, Enum):
    SAVED = "saved"
    SAVING = "saving"
    FAILED = "failed"
    READ_ONLY = "read_only"


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
        self.coordinator: ProjectCoordinator | None = None
        self._read_only = False
        self._hydrating_project = False
        self._restoring_mapping = False
        self._loaded_project: ProjectState | None = None
        self._layout_review_key: str | None = None
        self.template_health_service = getattr(services, "template_health_service", None) or TemplateHealthService(
            getattr(getattr(services, "preview_service", None), "_converter", None)
        )
        self._last_migration_backup: Path | None = None
        self.save_state = SaveState.SAVED
        catalog_dir = (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
            if os.name == "nt" and self.settings.format() == QSettings.Format.NativeFormat
            else Path(self.settings.fileName()).parent
        )
        self.project_catalog = getattr(services, "project_catalog", None) or ProjectCatalog(
            catalog_dir / "recent-projects.json"
        )
        self.profile_store = ProfileStore(catalog_dir / "profiles")
        self.migration_service = getattr(services, "migration_service", None) or ProjectMigrationService()

        self.home = ProjectHomePage(self.catalogs)
        self.root_stack = QStackedWidget()
        self.root_stack.addWidget(self.home)
        self.workspace_surface = self._build_workspace()
        self.root_stack.addWidget(self.workspace_surface)
        self.setCentralWidget(self.root_stack)
        self.resize(1120, 760)
        self.setMinimumSize(620, 520)
        self.setStyleSheet(application_stylesheet())

        self.home.new_requested.connect(self._create_project_from_home)
        self.home.open_requested.connect(self._open_project_dialog)
        self.home.recover_requested.connect(self._recover_draft)
        self.home.example_requested.connect(self._try_example)
        self.home.project_requested.connect(self._open_recent_project)
        self.home.repair_requested.connect(self._repair_recent_project)
        self.home.retry_save_requested.connect(self._retry_save)
        self.home.return_to_project_requested.connect(self._return_to_project)
        self.home_button.clicked.connect(self._show_home)
        self.retry_save_button.clicked.connect(self._retry_save)
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
        self.template_health_page.mapping_requested.connect(self._health_continue_mapping)
        self.template_health_page.render_requested.connect(self._render_layout_review)
        self.template_health_page.review_accepted.connect(self._accept_layout_review)
        self.match_page.plan_accepted.connect(self._accept_plan)
        self.match_page.plan_changed.connect(self._mapping_changed)
        self.match_page.save_profile_requested.connect(self._save_profile)
        self.match_page.apply_profile_requested.connect(self._choose_profile)
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
        self._refresh_recent_projects()
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
        self.home_button = QPushButton()
        self.draft_label = QLabel()
        self.draft_label.setProperty("role", "muted")
        self.save_state_label = QLabel()
        self.save_state_label.setProperty("role", "muted")
        self.retry_save_button = QPushButton()
        self.retry_save_button.setObjectName("retryProjectSave")
        self.retry_save_button.hide()
        self.locale_label = QLabel()
        self.locale_selector = QComboBox()
        for code, label in (("en", "English"), ("zh_CN", "简体中文"), ("ru", "Русский")):
            self.locale_selector.addItem(label, code)
        top_layout.addWidget(self.product_label)
        top_layout.addWidget(self.home_button)
        top_layout.addWidget(self.draft_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.save_state_label)
        top_layout.addWidget(self.retry_save_button)
        top_layout.addWidget(self.locale_label)
        top_layout.addWidget(self.locale_selector)
        outer.addWidget(top)

        self.read_only_notice = QLabel()
        self.read_only_notice.setWordWrap(True)
        self.read_only_notice.setProperty("state", "warning")
        self.read_only_notice.hide()
        outer.addWidget(self.read_only_notice)

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
        self.template_health_page = TemplateHealthPage(self.catalogs)
        self.match_page = MatchPage(self.catalogs)
        self.review_page = ReviewPage(self.catalogs)
        self.output_page = OutputPage(self.catalogs)
        self.results_page = ResultsPage(self.catalogs)
        pages = {
            "template": self.template_page,
            "template_health": self.template_health_page,
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

    def new_project(self, path: Path | None = None) -> None:
        self._flush_before_switch()
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
        store = None
        project = None
        if path is not None:
            store = ProjectStore.create(Path(path))
            project = ProjectState(revision=0, dataset=dataset, locale=self.catalogs.locale,
                                   project_name=Path(path).stem)
            store.save(project)
        self.coordinator = None
        self._loaded_project = project
        self._read_only = False
        self._last_migration_backup = None
        self.statusBar().clearMessage()
        self.data_page.set_dataset(dataset)
        self.state = WorkspaceState(current_step="data", project_path=Path(path) if path else None)
        self.project_state = OperatorProjectState(dataset=dataset)
        self._layout_review_key = None
        self._reset_workflow_pages(dataset)
        if store is not None:
            self._attach_store(store)
            self.project_catalog.remember(Path(path), project)
            self._refresh_recent_projects()
        self._set_save_state(SaveState.SAVED)
        self._set_read_only_mode(False)
        self.output_page.continue_button.setEnabled(False)
        self.banner.clear()
        self.root_stack.setCurrentWidget(self.workspace_surface)
        self._show_step("data")

    def load_project(self, path: Path) -> None:
        self._flush_before_switch()
        opener = getattr(self.services, "open_project", None)
        store = opener(Path(path)) if callable(opener) else ProjectStore.open(Path(path))
        migration_backup = None
        if store.issue_code == "project.older_schema":
            result = self.migration_service.migrate(Path(path))
            store = opener(Path(path)) if callable(opener) else ProjectStore.open(Path(path))
            migration_backup = result.backup_path
        project = store.load()
        project, restored, target_step, repair_code = self._restore_project_state(project)
        self.coordinator = None
        self._last_migration_backup = migration_backup
        self.statusBar().clearMessage()
        self._loaded_project = project
        self._read_only = store.read_only
        self._hydrating_project = True
        try:
            self.data_page.set_dataset(project.dataset)
        finally:
            self._hydrating_project = False
        self.project_state = restored
        self._layout_review_key = (
            str(project.layout_review.get("revision_key"))
            if project.layout_review and restored.template is not None and restored.plan is not None
            else None
        )
        self._restoring_mapping = True
        self._reset_workflow_pages(project.dataset)
        if restored.template is not None:
            self.template_page.set_inspection(restored.template)
            self.template_health_page.set_structure(
                self.template_health_service.inspect_structure(restored.template.path)
            )
        self.match_page.set_context(
            project.dataset,
            restored.template.names if restored.template is not None else (),
        )
        if restored.plan is not None:
            try:
                self.match_page.set_plan(restored.plan)
            except ValueError:
                repair_code = "project.resume_mapping_repair"
                target_step = "mapping"
                restored = replace(restored, plan=None, outputs=None, warning_ack_revision=None)
                self.project_state = restored
                project = self._clear_invalid_project_state(project, "mapping", target_step)
                self._loaded_project = project
                self.match_page.set_context(project.dataset, restored.template.names)
        if restored.plan is not None:
            self.review_page.set_context(project.dataset, restored.plan)
        self.output_page.set_order(project.dataset.order)
        if restored.outputs is not None:
            self.output_page.set_options(restored.outputs)
        self.state = WorkspaceState(
            current_step=target_step,
            completed_steps=STEP_IDS[:STEP_IDS.index(target_step)],
            project_path=Path(path),
            project_revision=project.revision,
        )
        self._remember_project(Path(path))
        self.project_catalog.remember(Path(path), project)
        self._refresh_recent_projects()
        self._attach_store(store)
        self._set_save_state(SaveState.READ_ONLY if store.read_only else SaveState.SAVED)
        self._set_read_only_mode(store.read_only)
        self._restoring_mapping = False
        self.set_locale(project.locale)
        self.banner.clear()
        if repair_code is not None:
            self.banner.show_issue(repair_code, self.catalogs.text(repair_code))
            if self.coordinator is not None:
                self.coordinator.mark_dirty(project)
                self._set_save_state(SaveState.SAVING)
        self.root_stack.setCurrentWidget(self.workspace_surface)
        self._show_step(self.state.current_step)
        self._update_migration_status()

    def _reset_workflow_pages(self, dataset: TabularDataset) -> None:
        self.template_page.clear_inspection()
        self.template_health_page.clear_structure()
        self.template_health_service.clear()
        self.match_page.set_context(dataset, ())
        self.review_page.clear_context()
        self.output_page.reset_options()
        self.results_page.set_ready()
        self.results_page.generate_button.setEnabled(False)

    def _restore_project_state(
        self, project: ProjectState
    ) -> tuple[ProjectState, OperatorProjectState, str, str | None]:
        restored = OperatorProjectState(dataset=project.dataset)
        maximum = "template"
        repair_code = None
        if project.template_path is not None:
            try:
                path = project.template_path
                if not path.is_file() or sha256(path.read_bytes()).hexdigest() != project.template_sha256:
                    raise ValueError("template bytes changed")
                inspector = getattr(self.services, "inspect_template", None)
                inspection = inspector(path) if callable(inspector) else inspect_template(path)
                saved_inspection = project.template_inspection
                if inspection.sha256 != project.template_sha256 or (
                    saved_inspection is not None and (
                        saved_inspection.get("sha256") != inspection.sha256
                        or tuple(saved_inspection.get("names", ())) != inspection.names
                    )
                ):
                    raise ValueError("template inspection changed")
                restored = replace(restored, template=inspection)
                maximum = "mapping"
            except Exception:
                repair_code = "project.resume_template_repair"
        elif project.active_step in STEP_IDS[2:]:
            repair_code = "project.resume_template_repair"
        if restored.template is not None and project.mapping_plan is not None:
            try:
                plan = MappingPlan.from_json(project.mapping_plan)
                if plan.unresolved(restored.template.names) or set(plan.sources) != set(restored.template.names):
                    raise ValueError("incomplete mapping")
                for row_id in project.dataset.order:
                    evaluate_plan(plan, project.dataset, row_id)
                restored = replace(
                    restored, plan=plan,
                    warning_ack_revision=(project.dataset.revision if project.acknowledgements else None),
                )
                maximum = "output"
            except Exception:
                repair_code = "project.resume_mapping_repair"
        elif restored.template is not None and project.active_step in STEP_IDS[3:]:
            repair_code = "project.resume_mapping_repair"
        if restored.plan is not None and project.output_options is not None:
            try:
                options = OutputOptions.from_json(project.output_options)
                if set(options.row_ids) != set(project.dataset.order) or not options.destination.is_dir():
                    raise ValueError("output order changed")
                restored = replace(restored, outputs=options)
                maximum = "generate"
            except Exception:
                repair_code = "project.resume_output_repair"
        elif restored.plan is not None and project.active_step == "generate":
            repair_code = "project.resume_output_repair"
        if restored.template is not None and restored.plan is not None:
            expected_key = self.template_health_service.revision_key(
                project.dataset, restored.template, restored.plan
            )
            saved_key = project.layout_review.get("revision_key") if project.layout_review else None
            if saved_key != expected_key and project.active_step in {"review", "output", "generate"}:
                maximum = "template_health"
                repair_code = "project.resume_layout_repair"
        requested = project.active_step if project.active_step in STEP_IDS else "data"
        target = STEP_IDS[min(STEP_IDS.index(requested), STEP_IDS.index(maximum))]
        if requested != target and repair_code is None:
            repair_code = {
                "template": "project.resume_template_repair",
                "mapping": "project.resume_mapping_repair",
                "output": "project.resume_output_repair",
            }.get(maximum)
        if repair_code is not None:
            project = self._clear_invalid_project_state(project, maximum, target)
        return project, restored, target, repair_code

    @staticmethod
    def _clear_invalid_project_state(
        project: ProjectState, maximum: str, target: str
    ) -> ProjectState:
        cleared = {"revision": project.revision + 1, "active_step": target,
                   "approval": None, "preview_revision": None}
        if maximum == "template":
            cleared.update(template_inspection=None, layout_review=None, mapping_plan=None,
                           output_options=None, acknowledgements=())
        elif maximum == "template_health":
            cleared.update(layout_review=None, acknowledgements=())
        elif maximum == "mapping":
            cleared.update(layout_review=None, mapping_plan=None, output_options=None, acknowledgements=())
        elif maximum == "output":
            cleared.update(output_options=None)
        return replace(project, **cleared)

    def open_project(self, path: Path) -> None:
        self.load_project(path)

    def _flush_before_switch(self) -> None:
        if self._block_project_switch_while_generating():
            raise ProjectError("generation.project_switch_blocked")
        if self.coordinator is not None and not self.coordinator.flush():
            raise ProjectSaveError("project.save_failed")

    def _block_project_switch_while_generating(self) -> bool:
        if self._thread is None:
            return False
        code = "generation.project_switch_blocked"
        self.banner.show_issue(code, self.catalogs.text(code))
        return True

    def _attach_store(self, store: ProjectStore) -> None:
        if store.read_only:
            self.coordinator = None
            return
        coordinator = ProjectCoordinator(store, self)
        coordinator.saved.connect(self._project_saved)
        coordinator.save_failed.connect(self._project_save_failed)
        self.coordinator = coordinator

    def _set_read_only_mode(self, read_only: bool) -> None:
        self._read_only = read_only
        self.read_only_notice.setText(self.catalogs.text("workspace.read_only_explanation"))
        self.read_only_notice.setVisible(read_only)
        self.data_page.model.set_read_only(read_only)
        self.data_page.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers if read_only
            else QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.review_page.values_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        data_controls = (
            self.data_page.excel_button, self.data_page.delimited_button,
            self.data_page.paste_button, self.data_page.manual_button,
            self.data_page.add_row_button, self.data_page.remove_row_button,
            self.data_page.add_column_button, self.data_page.rename_column_button,
            self.data_page.remove_column_button, self.data_page.undo_button,
            self.data_page.redo_button, self.data_page.continue_button,
        )
        template_controls = (
            self.template_page.choose_button, self.template_page.continue_button,
        )
        health_controls = (
            self.template_health_page.continue_button,
            self.template_health_page.expected_pages,
            self.template_health_page.render_button,
            self.template_health_page.mark_reviewed_button,
        )
        review_controls = (
            self.review_page.preview_button, self.review_page.acknowledge_button,
            self.review_page.continue_button,
        )
        output_controls = (
            self.output_page.docx, self.output_page.individual_pdf,
            self.output_page.combined_pdf, self.output_page.destination,
            self.output_page.browse_button, self.output_page.batch_name,
            self.output_page.continue_button,
        )
        for control in (*data_controls, *template_controls, *health_controls, *review_controls, *output_controls):
            control.setEnabled(not read_only)
        for card in self.match_page.cards.values():
            for control in (
                card.type_combo, card.column_combo, card.fixed_input,
                card.join_columns, card.join_separator,
                card.sequence_start, card.sequence_step, card.sequence_width,
                card.sequence_prefix, card.sequence_suffix,
                card.input_format, card.output_format,
            ):
                control.setEnabled(not read_only)
        if read_only:
            self.match_page.continue_button.setEnabled(False)
        else:
            self.match_page._changed()
        self.match_page.save_profile_button.setEnabled(not read_only)
        self.match_page.apply_profile_button.setEnabled(not read_only)
        self.results_page.generate_button.setEnabled(
            not read_only and self.project_state.outputs is not None
        )
        self.results_page.cancel_button.setEnabled(False if read_only else self.results_page.cancel_button.isEnabled())
        if not read_only:
            self.data_page.undo_button.setEnabled(self.data_page.model.undo_stack.canUndo())
            self.data_page.redo_button.setEnabled(self.data_page.model.undo_stack.canRedo())
            self.data_page.continue_button.setEnabled(bool(self.data_page.model.dataset.rows))
            self.template_page.continue_button.setEnabled(
                bool(self.template_page.inspection and self.template_page.inspection.placeholders)
            )
            self.template_health_page.continue_button.setEnabled(bool(
                self.template_health_page._structure and not self.template_health_page._structure.blocking
            ))

    def _set_save_state(self, state: SaveState) -> None:
        self.save_state = state
        label = self.catalogs.text(f"save_state.{state.value}")
        self.save_state_label.setText(label)
        self.save_state_label.setAccessibleName(label)
        self.home.save_state_label.setText(label)
        self.home.save_state_label.setAccessibleName(label)
        retry_available = (
            state == SaveState.FAILED
            and self.coordinator is not None
            and self.coordinator.has_pending
        )
        self.retry_save_button.setVisible(retry_available)
        self.home.set_retry_available(retry_available)

    def _project_saved(self, _revision: int) -> None:
        self._set_save_state(SaveState.SAVED)
        if self.state.project_path is not None and self._loaded_project is not None:
            self.project_catalog.remember(self.state.project_path, self._loaded_project)
            self._refresh_recent_projects()

    def _project_save_failed(self, _error: Exception) -> None:
        self._set_save_state(SaveState.FAILED)

    def _retry_save(self) -> None:
        if self.coordinator is not None:
            self.coordinator.flush()

    def _mark_project_dirty(self) -> None:
        if self.coordinator is None or self._loaded_project is None:
            return
        current = self.project_state
        template = current.template
        self._loaded_project = replace(
            self._loaded_project,
            revision=self.state.project_revision,
            dataset=current.dataset,
            template_path=template.path if template is not None else self._loaded_project.template_path,
            template_sha256=template.sha256 if template is not None else self._loaded_project.template_sha256,
            mapping_plan=current.plan.to_json() if current.plan is not None else None,
            output_options=current.outputs.to_json() if current.outputs is not None else None,
            layout_review=(
                self._loaded_project.layout_review
                if self._loaded_project.layout_review
                and self._loaded_project.layout_review.get("revision_key") == self._layout_review_key
                else None
            ),
            locale=self.catalogs.locale,
            active_step=self.current_step,
        )
        self.coordinator.mark_dirty(self._loaded_project)
        self._set_save_state(SaveState.SAVING)

    def set_locale(self, locale: str) -> None:
        self.catalogs.set_locale(locale)
        self.settings.setValue("locale", self.catalogs.locale)
        if (
            self.coordinator is not None
            and self._loaded_project is not None
            and self._loaded_project.locale != self.catalogs.locale
        ):
            self.state = replace(self.state, project_revision=self.state.project_revision + 1)
            self._loaded_project = replace(
                self._loaded_project,
                revision=self.state.project_revision,
                locale=self.catalogs.locale,
            )
            self.coordinator.mark_dirty(self._loaded_project)
            self._set_save_state(SaveState.SAVING)
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
        required = STEP_IDS[first_incomplete]
        mapping_return = (
            required == "template_health"
            and step == "mapping"
            and self.project_state.plan is not None
        )
        if target > first_incomplete and not mapping_return:
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
        self.home_button.setText(self.catalogs.text("action.home"))
        self.home_button.setAccessibleName(self.home_button.text())
        self.read_only_notice.setText(self.catalogs.text("workspace.read_only_explanation"))
        self.draft_label.setText(self.catalogs.text("workspace.untitled"))
        self._set_save_state(self.save_state)
        self.retry_save_button.setText(self.catalogs.text("save_state.retry"))
        self.retry_save_button.setAccessibleName(self.retry_save_button.text())
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
        self._update_migration_status()

    def _update_migration_status(self) -> None:
        if self._last_migration_backup is not None:
            message = self.catalogs.text("migration.completed", backup=str(self._last_migration_backup))
            self.statusBar().showMessage(message)
            self.statusBar().setAccessibleName(message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "step_rail"):
            self.step_rail.set_compact(event.size().width() < 760)

    def _show_home(self) -> None:
        if self._block_project_switch_while_generating():
            return
        self.home.set_current_project_available(self.state.project_path is not None)
        self.root_stack.setCurrentWidget(self.home)

    def _return_to_project(self) -> None:
        if self.state.project_path is not None:
            self.root_stack.setCurrentWidget(self.workspace_surface)

    def _show_step(self, step: str) -> None:
        changed = step != self.state.current_step
        self.state = replace(self.state, current_step=step)
        self.page_stack.setCurrentWidget(self._page_by_step[step])
        self.step_rail.set_state(step, self.state.completed_steps)
        index = STEP_IDS.index(step)
        self.back_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(STEP_IDS) - 1)
        if changed and self.coordinator is not None:
            self.state = replace(self.state, project_revision=self.state.project_revision + 1)
            self._mark_project_dirty()

    def _accept_data(self, _dataset: TabularDataset) -> None:
        if self._read_only:
            return
        self.project_state = replace(self.project_state, dataset=_dataset)
        self.mark_step_complete("data")
        self.navigate("template")

    def _import_source(self, kind: str) -> None:
        if self._read_only:
            return
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
        if self._read_only:
            return
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
        if self._hydrating_project:
            return
        if self._read_only and self._loaded_project is not None:
            if _dataset != self._loaded_project.dataset:
                self.data_page.set_dataset(self._loaded_project.dataset)
            return
        completed = tuple(step for step in self.state.completed_steps if step == "data")
        self.project_state = replace(
            self.project_state,
            dataset=_dataset,
            plan=None,
            outputs=None,
            warning_ack_revision=None,
        )
        self._layout_review_key = None
        self.template_health_page.clear_layout()
        self.template_health_service.clear()
        self.state = replace(
            self.state,
            completed_steps=completed,
            project_revision=self.state.project_revision + 1,
        )
        if self._loaded_project is not None:
            self._loaded_project = replace(
                self._loaded_project,
                acknowledgements=(), approval=None, preview_revision=None,
                layout_review=None,
            )
        self.review_page.clear_preview()
        self.review_page.set_issues(())
        self._mark_project_dirty()

    def _select_template(self, path: Path) -> None:
        if self._read_only:
            return
        try:
            inspection = self.services.inspect_template(Path(path))
        except Exception as error:
            if Path(path).suffix.casefold() != ".docx":
                self.template_page.show_template_error(getattr(error, "code", "template.invalid"))
                return
            report = self.template_health_service.inspect_structure(Path(path))
            if not report.template_sha256:
                self.template_page.show_template_error(getattr(error, "code", "template.invalid"))
                return
            inspection = TemplateInspection(
                Path(path),
                tuple(
                    Placeholder(name, len(locations), tuple(dict.fromkeys(item.part for item in locations)))
                    for name, locations in report.placeholders.items()
                ),
                report.template_sha256,
            )
            self.template_page.set_inspection(inspection)
            self._accept_template(inspection)
            return
        self.template_page.set_inspection(inspection)
        if self._loaded_project is not None and (
            self._loaded_project.template_path != inspection.path
            or self._loaded_project.template_sha256 != inspection.sha256
        ):
            self.project_state = replace(
                self.project_state, template=None, plan=None, outputs=None,
                warning_ack_revision=None,
            )
            self._layout_review_key = None
            self.template_health_page.clear_layout()
            self.template_health_service.clear()
            self._loaded_project = replace(
                self._loaded_project,
                template_path=inspection.path,
                template_sha256=inspection.sha256,
                template_inspection=None,
                mapping_plan=None,
                output_options=None,
                acknowledgements=(),
                approval=None,
                preview_revision=None,
                layout_review=None,
            )
            self.review_page.clear_preview()
            self.review_page.set_issues(())
            self.state = replace(
                self.state,
                completed_steps=tuple(step for step in self.state.completed_steps if step == "data"),
                project_revision=self.state.project_revision + 1,
            )
            self._show_step("template")
            self._mark_project_dirty()

    def _accept_template(self, inspection) -> None:
        if self._read_only:
            return
        self.project_state = replace(
            self.project_state,
            template=inspection,
            plan=None,
            outputs=None,
            warning_ack_revision=None,
        )
        self._layout_review_key = None
        self.template_health_page.clear_layout()
        self.template_health_service.clear()
        self.template_health_page.set_structure(
            self.template_health_service.inspect_structure(inspection.path)
        )
        self.match_page.set_context(
            self.project_state.dataset,
            inspection.names,
        )
        if self._loaded_project is not None:
            self._loaded_project = replace(
                self._loaded_project,
                template_path=inspection.path,
                template_sha256=inspection.sha256,
                template_inspection={"sha256": inspection.sha256, "names": list(inspection.names)},
                acknowledgements=(), approval=None, preview_revision=None,
                layout_review=None,
            )
        self.state = replace(self.state, project_revision=self.state.project_revision + 1)
        self._mark_project_dirty()
        self.mark_step_complete("template")
        self.navigate("template_health")

    def _health_continue_mapping(self) -> None:
        report = self.template_health_page._structure
        if self._read_only or report is None or report.blocking:
            return
        self.mark_step_complete("template_health")
        self.navigate("mapping")

    def _accept_plan(self, plan: MappingPlan) -> None:
        if self._read_only:
            return
        self.project_state = replace(
            self.project_state,
            plan=plan,
            outputs=None,
            warning_ack_revision=None,
        )
        self._layout_review_key = None
        self.template_health_page.clear_layout()
        self.template_health_service.clear()
        if self._loaded_project is not None:
            self._loaded_project = replace(self._loaded_project, layout_review=None)
        self.review_page.set_context(self.project_state.dataset, plan)
        self.state = replace(self.state, project_revision=self.state.project_revision + 1)
        self._mark_project_dirty()
        self.mark_step_complete("mapping")
        self.state = replace(
            self.state,
            completed_steps=tuple(
                step for step in self.state.completed_steps if step != "template_health"
            ),
        )
        self._show_step("template_health")

    def _render_layout_review(self, expected_pages: int) -> None:
        if self._read_only:
            return
        current = self.project_state
        if not all((current.dataset, current.template, current.plan)):
            self.banner.show_issue(
                "navigation.complete_previous", self.catalogs.text("navigation.complete_previous")
            )
            return
        self.template_health_page.clear_layout()
        self.template_health_service.clear()
        try:
            result = self.template_health_service.render_representatives(
                current.dataset, current.template, current.plan, expected_pages=expected_pages
            )
        except Exception:
            self.banner.show_issue("preview.render_failed", self.catalogs.text("preview.render_failed", row="—"))
            return
        self.template_health_page.set_layout_result(result)

    def _accept_layout_review(self, revision_key: str) -> None:
        if self._read_only:
            return
        current = self.project_state
        result = self.template_health_page.layout_result
        if not all((current.dataset, current.template, current.plan)) or result is None or not result.ready:
            return
        expected_key = self.template_health_service.revision_key(
            current.dataset, current.template, current.plan
        )
        if revision_key != expected_key or not self.template_health_page.mark_reviewed_button.isEnabled():
            return
        self._layout_review_key = revision_key
        if self._loaded_project is not None:
            self._loaded_project = replace(
                self._loaded_project,
                layout_review={
                    "revision_key": revision_key,
                    "preview_hashes": [preview.pdf_sha256 for preview in result.previews],
                    "representative_rows": [preview.row_id for preview in result.previews],
                    "expected_pages": self.template_health_page.expected_pages.value(),
                },
            )
        self.state = replace(self.state, project_revision=self.state.project_revision + 1)
        self._mark_project_dirty()
        self.mark_step_complete("template_health")
        self.mark_step_complete("mapping")
        self.navigate("review")

    def _invalidate_mapping_review(self, *, preserve_plan: bool = False) -> None:
        previous_plan = self.project_state.plan if preserve_plan else None
        self.project_state = replace(
            self.project_state, plan=previous_plan, outputs=None, warning_ack_revision=None,
        )
        self._layout_review_key = None
        self.template_health_page.clear_layout()
        self.template_health_service.clear()
        self.state = replace(
            self.state,
            completed_steps=tuple(step for step in self.state.completed_steps if step in {"data", "template", "template_health"}),
            project_revision=self.state.project_revision + 1,
        )
        if self._loaded_project is not None:
            self._loaded_project = replace(
                self._loaded_project,
                mapping_plan=previous_plan.to_json() if previous_plan else None,
                output_options=None,
                acknowledgements=(), approval=None, preview_revision=None,
                layout_review=None,
            )
        self.review_page.clear_context()
        self.review_page.clear_preview()
        self.results_page.generate_button.setEnabled(False)
        self._mark_project_dirty()

    def _mapping_changed(self, plan: MappingPlan) -> None:
        if self._read_only or self._restoring_mapping or self.project_state.plan is None:
            return
        if plan.to_json() != self.project_state.plan.to_json():
            self._invalidate_mapping_review(preserve_plan=True)
            if self._loaded_project is not None and self._loaded_project.profile_path is not None:
                self._loaded_project = replace(self._loaded_project, profile_path=None)
                self._mark_project_dirty()

    def _save_profile(self) -> None:
        if self._read_only or self.project_state.dataset is None or self.project_state.template is None:
            return
        try:
            plan = self.match_page.mapping_plan()
            if not plan.sources:
                raise ProfileError("profile.no_mapping")
            name, accepted = QInputDialog.getText(
                self, self.catalogs.text("profile.save"), self.catalogs.text("profile.name_prompt")
            )
            if not accepted:
                return
            profile = MappingProfile.from_plan(
                name, plan, self.project_state.template.names,
                self.project_state.dataset.columns,
                template_sha256=self.project_state.template.sha256,
                defaults={
                    "docx": self.output_page.docx.isChecked(),
                    "individual_pdf": self.output_page.individual_pdf.isChecked(),
                    "combined_pdf": self.output_page.combined_pdf.isChecked(),
                    "batch_name": self.output_page.batch_name.text(),
                },
            )
            has_fixed = any(record["type"] == "fixed" for record in profile.mappings.values())
            allow_fixed = False
            if has_fixed:
                allow_fixed = QMessageBox.question(
                    self, self.catalogs.text("profile.save"),
                    self.catalogs.text("profile.fixed_confirm"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) == QMessageBox.StandardButton.Yes
                if not allow_fixed:
                    return
            path = self.profile_store.save(profile, allow_fixed_values=allow_fixed)
            self.statusBar().showMessage(self.catalogs.text("profile.saved", path=str(path)))
        except (ProfileError, OSError) as error:
            code = getattr(error, "code", "profile.save_failed")
            self.banner.show_issue(code, self.catalogs.text(code))

    def _choose_profile(self) -> None:
        if self._read_only:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self, self.catalogs.text("profile.apply"), str(self.profile_store.directory),
            "Certificate profiles (*.certprofile)",
        )
        if selected:
            self._apply_profile_path(Path(selected))

    def _apply_profile_path(self, path: Path) -> None:
        if self._read_only or self.project_state.dataset is None or self.project_state.template is None:
            return
        try:
            profile = self.profile_store.load(Path(path))
            comparison = compare_profile(
                profile, self.project_state.dataset.columns, self.project_state.template.names
            )
            self._restoring_mapping = True
            try:
                self.match_page.set_plan(comparison.applied_plan)
            finally:
                self._restoring_mapping = False
            self.match_page.show_profile_comparison(comparison)
            self._invalidate_mapping_review()
            for key, control in (
                ("docx", self.output_page.docx),
                ("individual_pdf", self.output_page.individual_pdf),
                ("combined_pdf", self.output_page.combined_pdf),
            ):
                if key in profile.defaults:
                    control.setChecked(profile.defaults[key])
            if "batch_name" in profile.defaults:
                self.output_page.batch_name.setText(profile.defaults["batch_name"])
            if self._loaded_project is not None:
                self._loaded_project = replace(self._loaded_project, profile_path=Path(path))
                self._mark_project_dirty()
            if profile.template_sha256 is not None and profile.template_sha256 != self.project_state.template.sha256:
                code = "profile.template_changed"
                self.banner.show_issue(code, self.catalogs.text(code))
            else:
                self.banner.clear()
            self.statusBar().showMessage(self.catalogs.text("profile.applied"))
        except (ProfileError, ValueError, OSError) as error:
            code = getattr(error, "code", "profile.unreadable")
            self.banner.show_issue(code, self.catalogs.text(code))

    def _accept_review(self) -> None:
        if self._read_only:
            return
        self.output_page.set_order(self.project_state.dataset.order)
        self.output_page.continue_button.setEnabled(True)
        availability = getattr(self.services, "word_availability", None)
        if callable(availability):
            self.output_page.set_word_availability(availability())
        self.mark_step_complete("review")
        self.navigate("output")

    def _accept_outputs(self, outputs: OutputOptions) -> None:
        if self._read_only:
            return
        self.project_state = replace(self.project_state, outputs=outputs)
        self.results_page.set_expected_combined(outputs.combined_pdf)
        self.results_page.generate_button.setEnabled(True)
        self.state = replace(self.state, project_revision=self.state.project_revision + 1)
        self._mark_project_dirty()
        self.mark_step_complete("output")
        self.navigate("generate")

    def _focus_issue(self, row_id: str, column_id: str) -> None:
        self._show_step("data")
        self.data_page.focus_cell(row_id, column_id)

    def _acknowledge_warnings(self) -> None:
        if self._read_only:
            return
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
        self.review_page.clear_preview()
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
        if self._read_only:
            return
        if self._thread is not None:
            return
        current = self.project_state
        if not all((current.dataset, current.template, current.plan, current.outputs)):
            self.banner.show_issue(
                "navigation.complete_previous",
                self.catalogs.text("navigation.complete_previous"),
            )
            return
        expected_layout_key = self.template_health_service.revision_key(
            current.dataset, current.template, current.plan
        )
        structure = self.template_health_service.inspect_structure(current.template.path)
        if structure.template_sha256 != current.template.sha256:
            self._layout_review_key = None
            self.banner.show_issue(
                "validation.template_changed",
                self.catalogs.text("validation.template_changed"),
            )
            self._show_step("template")
            return
        if (
            self._layout_review_key != expected_layout_key
            or structure.blocking
        ):
            self.banner.show_issue(
                "template.layout_review_required",
                self.catalogs.text("template.layout_review_required"),
            )
            self._show_step("template_health")
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
        outputs = self.project_state.outputs
        self.results_page.set_expected_combined(
            bool(outputs and outputs.combined_pdf)
        )
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
        result = self.results_page.result if self.results_page.state == "published" else None
        opener = getattr(self.services, "open_path", None)
        if result and result.output_dir and callable(opener):
            opener(result.output_dir)

    def _open_result_file(self, name: str) -> None:
        result = self.results_page.result if self.results_page.state == "published" else None
        opener = getattr(self.services, "open_path", None)
        path = result.output_dir / name if result and result.output_dir else None
        if path is not None and path.is_file() and callable(opener):
            opener(path)

    def _open_combined_output(self) -> None:
        result = self.results_page.result if self.results_page.state == "published" else None
        opener = getattr(self.services, "open_path", None)
        path = result.combined_pdf_path if result else None
        if not (result and result.output_dir and path and callable(opener)):
            return
        try:
            is_published_artifact = path.resolve().parent == result.output_dir.resolve()
        except OSError:
            is_published_artifact = False
        if not is_published_artifact or not path.is_file() or not opener(path):
            self.results_page.show_open_error()

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._close_when_idle = True
            self._request_cancel()
            event.ignore()
            return
        if self.coordinator is not None and self.coordinator.has_pending:
            while not self.coordinator.flush():
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setWindowTitle(self.catalogs.text("app.title"))
                dialog.setText(self.catalogs.text("close.save_failed"))
                retry_button = dialog.addButton(
                    self.catalogs.text("close.retry"), QMessageBox.ButtonRole.AcceptRole
                )
                discard_button = dialog.addButton(
                    self.catalogs.text("close.discard"), QMessageBox.ButtonRole.DestructiveRole
                )
                dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
                dialog.button(QMessageBox.StandardButton.Cancel).setText(
                    self.catalogs.text("close.cancel")
                )
                dialog.exec()
                if dialog.clickedButton() is retry_button:
                    continue
                if dialog.clickedButton() is not discard_button:
                    event.ignore()
                    return
                break
        preview_service = getattr(self.services, "preview_service", None)
        self.template_health_page.clear_layout()
        self.template_health_service.clear()
        if preview_service is not None:
            self.review_page.clear_preview()
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
        if self._block_project_switch_while_generating():
            return
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
            self._open_recent_project(Path(selected))

    def _recover_draft(self) -> None:
        if self._block_project_switch_while_generating():
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self.catalogs.text("home.recover_project"),
            "",
            self.catalogs.text("file.backup_filter"),
        )
        if selected:
            self._open_recent_project(Path(selected))

    def _refresh_recent_projects(self) -> None:
        self.home.set_projects(self.project_catalog.list())

    def _create_project_from_home(self) -> None:
        if self._block_project_switch_while_generating():
            return
        selected, _filter = QFileDialog.getSaveFileName(
            self, self.catalogs.text("home.new_project"), "",
            self.catalogs.text("file.project_filter"),
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix != ".certproject":
            path = path.with_suffix(".certproject")
        try:
            self.new_project(path)
        except Exception as error:
            self._show_project_error(error)

    def _open_project_dialog(self) -> None:
        if self._block_project_switch_while_generating():
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self, self.catalogs.text("home.choose_project"), "",
            self.catalogs.text("file.project_filter"),
        )
        if selected:
            self._open_recent_project(Path(selected))

    def _open_recent_project(self, path: Path) -> None:
        if self._block_project_switch_while_generating():
            return
        try:
            self.load_project(path)
        except Exception as error:
            self._show_project_error(error)

    def _repair_recent_project(self, missing_path: Path) -> None:
        if self._block_project_switch_while_generating():
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self, self.catalogs.text("home.repair"), "",
            self.catalogs.text("file.project_filter"),
        )
        if selected:
            try:
                self.load_project(Path(selected))
            except Exception as error:
                self._show_project_error(error)
                return
            self.project_catalog.forget(missing_path)
            self._refresh_recent_projects()

    def _try_example(self) -> None:
        if self._block_project_switch_while_generating():
            return
        selected = QFileDialog.getExistingDirectory(
            self, self.catalogs.text("example.choose_destination")
        )
        if not selected:
            return
        try:
            creator = getattr(self.services, "create_example", None)
            if callable(creator):
                path = creator(Path(selected))
            else:
                from certificate_automation.app import create_example_project
                path = create_example_project(package_root().parent.parent / "examples", Path(selected))
            self.load_project(path)
        except Exception as error:
            self._show_project_error(error)
            return
        QMessageBox.information(
            self, self.catalogs.text("app.title"), self.catalogs.text("example.copied")
        )

    def _show_project_error(self, error: Exception) -> None:
        code = getattr(error, "code", "migration.open_failed")
        try:
            message = self.catalogs.text(code)
        except CatalogError:
            message = self.catalogs.text("migration.failed")
        QMessageBox.warning(self, self.catalogs.text("app.title"), message)

    def _open_results(self) -> None:
        if self._block_project_switch_while_generating():
            return
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
