"""Project-first home page with visible recovery for recent projects."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from certificate_automation.i18n import CatalogSet
from certificate_automation.project_catalog import ProjectHealth, ProjectSummary


class ProjectHomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    recover_requested = Signal()
    example_requested = Signal()
    project_requested = Signal(Path)
    repair_requested = Signal(Path)

    def __init__(self, catalogs: CatalogSet, parent=None) -> None:
        super().__init__(parent)
        self._catalogs = catalogs
        self._projects: tuple[ProjectSummary, ...] = ()
        self._project_widgets: list[tuple[QLabel, QLabel, QPushButton, QPushButton]] = []
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.subtitle = QLabel()
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        self.save_state_label = QLabel()
        self.save_state_label.setObjectName("homeSaveState")
        self.save_state_label.setProperty("role", "muted")
        self.new_project_button = QPushButton()
        self.open_project_button = QPushButton()
        self.recent_projects_button = QPushButton()
        self.recover_project_button = QPushButton()
        self.try_example_button = QPushButton()
        for button, name in zip(
            self.primary_buttons(),
            ("newProject", "openProject", "recentProjects", "recoverProject", "tryExample"),
            strict=True,
        ):
            button.setObjectName(name)
            button.setMinimumHeight(36)
        self.new_project_button.setProperty("role", "primary")
        card = QFrame()
        card.setProperty("role", "surface")
        actions = QVBoxLayout(card)
        for button in self.primary_buttons():
            actions.addWidget(button)
        self.recent_list = QWidget()
        self.recent_list.setObjectName("recentProjectList")
        self.recent_layout = QVBoxLayout(self.recent_list)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(6)
        self.recent_scroll = QScrollArea()
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.recent_scroll.setWidget(self.recent_list)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.save_state_label)
        layout.addSpacing(12)
        layout.addWidget(card)
        layout.addWidget(self.recent_scroll, 1)
        self.new_project_button.clicked.connect(self.new_requested)
        self.open_project_button.clicked.connect(self.open_requested)
        self.recover_project_button.clicked.connect(self.recover_requested)
        self.try_example_button.clicked.connect(self.example_requested)
        self.recent_projects_button.clicked.connect(self._focus_recent)
        for first, second in zip(self.primary_buttons(), self.primary_buttons()[1:]):
            self.setTabOrder(first, second)
        self.retranslate()

    def primary_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.new_project_button,
            self.open_project_button,
            self.recent_projects_button,
            self.recover_project_button,
            self.try_example_button,
        )

    def set_projects(self, projects: tuple[ProjectSummary, ...]) -> None:
        self._projects = tuple(projects)
        for label, status, open_button, repair_button in self._project_widgets:
            for widget in (label, status, open_button, repair_button):
                widget.deleteLater()
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._project_widgets.clear()
        for project in self._projects:
            row = QFrame()
            row.setProperty("role", "surface")
            line = QHBoxLayout(row)
            label = QLabel()
            label.setWordWrap(True)
            status = QLabel()
            status.setWordWrap(True)
            open_button = QPushButton()
            repair_button = QPushButton()
            open_button.clicked.connect(lambda _checked=False, path=project.path: self.project_requested.emit(path))
            repair_button.clicked.connect(lambda _checked=False, path=project.path: self.repair_requested.emit(path))
            line.addWidget(label, 2)
            line.addWidget(status, 1)
            line.addWidget(open_button)
            line.addWidget(repair_button)
            self.recent_layout.addWidget(row)
            self._project_widgets.append((label, status, open_button, repair_button))
            row.show()
        self._retranslate_projects()

    def project_label(self, index: int) -> QLabel:
        return self._project_widgets[index][0]

    def project_status(self, index: int) -> str:
        return self._project_widgets[index][1].text()

    def repair_button(self, index: int) -> QPushButton:
        return self._project_widgets[index][3]

    def retranslate(self) -> None:
        self.title.setText(self._catalogs.text("home.title"))
        self.subtitle.setText(self._catalogs.text("home.subtitle"))
        for button, key in zip(
            self.primary_buttons(),
            ("home.new_project", "home.open_project", "home.recent_projects", "home.recover_project", "home.try_example"),
            strict=True,
        ):
            label = self._catalogs.text(key)
            button.setText(label)
            button.setAccessibleName(label)
        self._retranslate_projects()

    def _retranslate_projects(self) -> None:
        for project, (label, status, open_button, repair_button) in zip(
            self._projects, self._project_widgets, strict=True
        ):
            name = project.path.name
            details = self._catalogs.text(
                "home.project_details",
                name=name,
                saved=project.last_saved_at.strftime("%Y-%m-%d %H:%M") if project.last_saved_at else self._catalogs.text("home.unknown"),
                template=project.template_name or self._catalogs.text("home.unknown"),
                recipients=project.recipient_count if project.recipient_count is not None else self._catalogs.text("home.unknown"),
                step=(
                    self._catalogs.text(f"nav.{project.active_step}")
                    if project.active_step in ("data", "template", "mapping", "review", "output", "generate")
                    else self._catalogs.text("home.unknown")
                ),
            )
            label.setText(details)
            status.setText(self._catalogs.text(f"project.health.{project.health.value}"))
            open_text = self._catalogs.text("home.open_recent")
            open_button.setText(open_text)
            open_button.setAccessibleName(f"{open_text}: {name}")
            repair_text = self._catalogs.text("home.repair")
            repair_button.setText(repair_text)
            repair_button.setAccessibleName(f"{repair_text}: {name}")
            repair_button.setVisible(project.health != ProjectHealth.READY)

    def _focus_recent(self) -> None:
        if self._project_widgets:
            self._project_widgets[0][2].setFocus()
