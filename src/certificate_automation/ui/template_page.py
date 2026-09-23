"""Word-template selection and inspection page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from certificate_automation.i18n import CatalogSet
from certificate_automation.template import TemplateInspection


class TemplatePage(QWidget):
    template_selected = Signal(object)
    inspection_accepted = Signal(object)

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self.setAcceptDrops(True)
        self.inspection: TemplateInspection | None = None
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.field_guide = QLabel()
        self.field_guide.setWordWrap(True)
        self.drop_hint = QLabel()
        self.drop_hint.setWordWrap(True)
        self.drop_hint.setMinimumHeight(72)
        self.drop_hint.setProperty("role", "drop_target")
        self.drop_hint.setStyleSheet(
            "border: 2px dashed #8497b5; border-radius: 8px; padding: 16px;"
        )
        self.choose_button = QPushButton()
        self.file_name = QLabel("—")
        self.hash_label = QLabel("—")
        self.placeholder_list = QListWidget()
        self.error_label = QLabel()
        self.error_label.setProperty("state", "error")
        self.error_label.setWordWrap(True)
        self.continue_button = QPushButton()
        self.continue_button.setProperty("role", "primary")
        self.continue_button.setEnabled(False)
        layout = QVBoxLayout(self)
        for widget in (
            self.title,
            self.explanation,
            self.field_guide,
            self.drop_hint,
            self.choose_button,
            self.file_name,
            self.hash_label,
            self.placeholder_list,
            self.error_label,
            self.continue_button,
        ):
            layout.addWidget(widget)
        self.choose_button.clicked.connect(self._choose)
        self.continue_button.clicked.connect(
            lambda: self.inspection and self.inspection_accepted.emit(self.inspection)
        )
        self._catalogs.subscribe(lambda _locale: self.retranslate())
        self.retranslate()

    def set_inspection(self, inspection: TemplateInspection) -> None:
        self.inspection = inspection
        self.file_name.setText(inspection.path.name)
        self.hash_label.setText(inspection.sha256 or "—")
        self.placeholder_list.clear()
        for placeholder in inspection.placeholders:
            locations = ", ".join(placeholder.parts)
            self.placeholder_list.addItem(
                f"{{{{{placeholder.name}}}}}  × {placeholder.occurrences}  ·  {locations}"
            )
        self.error_label.clear()
        self.continue_button.setEnabled(bool(inspection.placeholders))

    def clear_inspection(self) -> None:
        self.inspection = None
        self.file_name.setText("—")
        self.hash_label.setText("—")
        self.placeholder_list.clear()
        self.error_label.clear()
        self.continue_button.setEnabled(False)

    def show_template_error(self, code: str, parameters=None) -> None:
        self.error_label.setText(self._catalogs.text(code, **dict(parameters or {})))
        self.continue_button.setEnabled(False)

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("template.title"))
        self.explanation.setText(self._catalogs.text("template.explanation"))
        self.field_guide.setText(self._catalogs.text("template.field_guide"))
        self.drop_hint.setText(self._catalogs.text("template.drop_hint"))
        self.drop_hint.setAccessibleName(self.drop_hint.text())
        self.choose_button.setText(self._catalogs.text("template.choose"))
        self.choose_button.setAccessibleName(self.choose_button.text())
        self.placeholder_list.setAccessibleName(self._catalogs.text("template.placeholders"))
        self.continue_button.setText(self._catalogs.text("action.continue"))
        self.continue_button.setAccessibleName(self.continue_button.text())

    def _choose(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self._catalogs.text("template.choose"),
            "",
            self._catalogs.text("template.file_filter"),
        )
        if selected:
            self.template_selected.emit(Path(selected))

    def _drop_candidate(self, mime_data) -> tuple[Path | None, str | None]:
        if not mime_data.hasUrls() or len(mime_data.urls()) != 1:
            return None, "template.drop_one"
        url = mime_data.urls()[0]
        if not url.isLocalFile():
            return None, "template.drop_local"
        path = Path(url.toLocalFile())
        if path.is_dir():
            return None, "template.drop_file"
        if path.suffix.casefold() != ".docx":
            return None, "template.unsupported_type"
        if not path.is_file():
            return None, "template.drop_file"
        return path, None

    def dragEnterEvent(self, event) -> None:
        path, error = self._drop_candidate(event.mimeData())
        if path is not None:
            self.error_label.clear()
            event.acceptProposedAction()
        else:
            self.error_label.setText(self._catalogs.text(error))
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        path, error = self._drop_candidate(event.mimeData())
        if path is None:
            self.error_label.setText(self._catalogs.text(error))
            event.ignore()
            return
        self.error_label.clear()
        self.template_selected.emit(path)
        event.acceptProposedAction()
