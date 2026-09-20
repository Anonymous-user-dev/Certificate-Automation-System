"""Guided desktop workflow and background-operation coordination."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from certificate_automation.batch import BatchRequest, CancellationToken
from certificate_automation.ui.files_page import FilesPage
from certificate_automation.ui.generation_page import GenerationPage
from certificate_automation.ui.mapping_page import MappingPage
from certificate_automation.ui.preview_page import PreviewPage
from certificate_automation.ui.validation_page import ValidationPage
from certificate_automation.ui.worker import GenerationWorker, OperationWorker


class MainWindow(QMainWindow):
    def __init__(self, services, parent=None) -> None:
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Certificate Automation")
        self.resize(860, 640)
        self.files_page = FilesPage()
        self.mapping_page = MappingPage()
        self.validation_page = ValidationPage()
        self.preview_page = PreviewPage()
        self.generation_page = GenerationPage()
        self.stack = QStackedWidget()
        for page in (
            self.files_page,
            self.mapping_page,
            self.validation_page,
            self.preview_page,
            self.generation_page,
        ):
            self.stack.addWidget(page)
        steps = QLabel("1 Files  ›  2 Mapping  ›  3 Validation  ›  4 Preview  ›  5 Generate")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(steps)
        layout.addWidget(self.stack)
        self.setCentralWidget(container)

        self.workbook = None
        self.template = None
        self.mappings = None
        self.report = None
        self._thread: QThread | None = None
        self._worker = None
        self._success_callback = None
        self._failure_callback = None
        self.cancellation: CancellationToken | None = None

        self.files_page.workbook_selected.connect(self._request_worksheets)
        self.files_page.continue_requested.connect(self._load_inputs)
        self.mapping_page.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.files_page)
        )
        self.mapping_page.continue_requested.connect(self._validate_inputs)
        self.validation_page.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.mapping_page)
        )
        self.validation_page.preview_requested.connect(self._generate_preview)
        self.validation_page.generate_requested.connect(self._generate_batch)
        self.preview_page.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.validation_page)
        )
        self.preview_page.generate_requested.connect(self._generate_batch)
        self.generation_page.cancel_requested.connect(self._request_cancel)

    @property
    def current_page(self):
        return self.stack.currentWidget()

    @property
    def active_thread(self):
        return self._thread

    def _request_worksheets(self, value: str) -> None:
        if not value or self._thread is not None:
            return
        self.files_page.show_error("")
        self._start_operation(
            lambda: self.services.list_worksheets(Path(value)),
            self.files_page.set_worksheets,
            lambda error: self.files_page.show_error(str(error)),
        )

    def _load_inputs(self) -> None:
        workbook_path, sheet_name, template_path, _ = self.files_page.selected_paths()

        def operation():
            workbook = self.services.load_workbook(workbook_path, sheet_name)
            template = self.services.inspect_template(template_path)
            suggestions = self.services.suggest_mappings(
                workbook.headers,
                template.names,
            )
            return workbook, template, suggestions

        def success(result):
            self.workbook, self.template, suggestions = result
            self.mapping_page.configure(
                self.workbook,
                self.template.names,
                suggestions,
            )
            self.stack.setCurrentWidget(self.mapping_page)

        self._start_operation(
            operation,
            success,
            lambda error: self.files_page.show_error(str(error)),
        )

    def _validate_inputs(self) -> None:
        self.mappings = self.mapping_page.selection()
        destination = self.files_page.selected_paths()[3]
        self._start_operation(
            lambda: self.services.validate(
                self.workbook,
                self.template,
                self.mappings,
                destination,
            ),
            self._show_validation,
            lambda error: self.files_page.show_error(str(error)),
        )

    def _show_validation(self, report) -> None:
        self.report = report
        self.validation_page.set_report(report)
        self.stack.setCurrentWidget(self.validation_page)

    def _generate_preview(self) -> None:
        self.preview_page.status_label.setText("Generating and verifying preview…")
        self.stack.setCurrentWidget(self.preview_page)

        def success(path):
            opened = self.services.open_path(Path(path))
            message = "Preview generated and opened." if opened else "Preview generated."
            self.preview_page.status_label.setText(f"{message} {path}")

        self._start_operation(
            lambda: self.services.preview(
                self.workbook,
                self.template,
                self.mappings,
            ),
            success,
            lambda error: self.preview_page.status_label.setText(
                f"Preview failed safely. {error}"
            ),
        )

    def _generate_batch(self) -> None:
        if self._thread is not None or not self.services.confirm_generation(self):
            return
        request = BatchRequest(
            self.workbook,
            self.template,
            self.mappings,
            self.files_page.selected_paths()[3],
        )
        self.cancellation = CancellationToken()
        self.generation_page.start()
        self.stack.setCurrentWidget(self.generation_page)
        thread = QThread(self)
        worker = GenerationWorker(
            self.services.batch_generator,
            request,
            self.cancellation,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.generation_page.update_progress)
        worker.finished.connect(self._generation_finished)
        worker.failed.connect(self._generation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self._set_pages_enabled(False)
        self.generation_page.setEnabled(True)
        thread.start()

    def _generation_finished(self, result) -> None:
        self.generation_page.set_result(result)

    def _generation_failed(self, error) -> None:
        action = getattr(error, "user_action", "Review the source files and try again.")
        self.generation_page.set_error(f"{error} {action}")

    def _request_cancel(self) -> None:
        if self.cancellation is not None:
            self.cancellation.request()
            self.generation_page.status_label.setText(
                "Cancellation requested. Finishing the current document safely…"
            )

    def _start_operation(self, operation, success, failure) -> None:
        if self._thread is not None:
            return
        thread = QThread(self)
        worker = OperationWorker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._operation_succeeded)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._success_callback = success
        self._failure_callback = failure
        self._thread = thread
        self._worker = worker
        self._set_pages_enabled(False)
        thread.start()

    def _operation_succeeded(self, value) -> None:
        callback = self._success_callback
        if callback is not None:
            callback(value)

    def _operation_failed(self, error) -> None:
        callback = self._failure_callback
        if callback is not None:
            callback(error)

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._success_callback = None
        self._failure_callback = None
        self._set_pages_enabled(True)

    def _set_pages_enabled(self, enabled: bool) -> None:
        for index in range(self.stack.count()):
            self.stack.widget(index).setEnabled(enabled)
