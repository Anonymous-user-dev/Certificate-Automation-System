"""Editable Qt model backed by stable row and column identifiers."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable
from uuid import uuid4

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap, QUndoCommand, QUndoStack

from certificate_automation.dataset import (
    Column,
    DataRow,
    DatasetError,
    TabularDataset,
    normalize_column_id,
)
from certificate_automation.domain import Issue, Severity
from certificate_automation.i18n import CatalogSet, package_root


class DatasetTableModel(QAbstractTableModel):
    """Present immutable datasets while translating view rows to stable IDs."""

    dataset_changed = Signal(object)
    issue_activated = Signal(str, str)

    def __init__(
        self,
        dataset: TabularDataset,
        parent=None,
        *,
        catalogs: CatalogSet | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset = dataset
        self._read_only = False
        self._catalogs = catalogs or CatalogSet.load(package_root())
        self._issues: dict[tuple[str, str], tuple[Issue, ...]] = {}
        self._filter = ""
        self._sort_column: int | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._view_order: list[str] = []
        self.undo_stack = QUndoStack(self)
        self._rebuild_view_order()

    @property
    def dataset(self) -> TabularDataset:
        return self._dataset

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._view_order)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._dataset.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row_id = self.row_id_at(index.row())
        column_id = self.column_id_at(index.column())
        row = self._dataset.row(row_id)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return row.values[column_id]
        issues = self._issues.get((row_id, column_id), ())
        if role == Qt.ItemDataRole.DecorationRole and issues:
            return _issue_icon(issues)
        if role in (
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.AccessibleDescriptionRole,
        ) and issues:
            return "\n".join(
                self._catalogs.text(issue.code, **dict(issue.parameters))
                for issue in issues
            )
        if role == Qt.ItemDataRole.BackgroundRole and issues:
            color = "#FDECEC" if any(issue.blocking for issue in issues) else "#FFF4DE"
            return QColor(color)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._dataset.columns[section].label
        row = self._dataset.row(self.row_id_at(section))
        return str(row.source_row) if row.source_row is not None else str(section + 1)

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        return flags if self._read_only else flags | Qt.ItemFlag.ItemIsEditable

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if self._read_only or role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row_id = self.row_id_at(index.row())
        column_id = self.column_id_at(index.column())
        if self._dataset.row(row_id).value(column_id) == str(value):
            return False
        self.undo_stack.push(SetCellCommand(self, row_id, column_id, str(value)))
        return True

    def row_id_at(self, view_row: int) -> str:
        return self._view_order[view_row]

    def column_id_at(self, view_column: int) -> str:
        return self._dataset.columns[view_column].column_id

    def index_for_ids(self, row_id: str, column_id: str) -> QModelIndex:
        try:
            row = self._view_order.index(row_id)
            column = next(
                index
                for index, item in enumerate(self._dataset.columns)
                if item.column_id == column_id
            )
        except (ValueError, StopIteration) as error:
            raise DatasetError("dataset.cell_not_visible") from error
        return self.index(row, column)

    def replace_dataset(self, dataset: TabularDataset) -> None:
        self.beginResetModel()
        self._dataset = dataset
        self._filter = ""
        self._sort_column = None
        self._rebuild_view_order()
        self._issues.clear()
        self.undo_stack.clear()
        self.endResetModel()
        self.dataset_changed.emit(dataset)

    def set_issues(self, issues: tuple[Issue, ...]) -> None:
        located: dict[tuple[str, str], list[Issue]] = {}
        for issue in issues:
            if issue.row_id and issue.column_id:
                located.setdefault((issue.row_id, issue.column_id), []).append(issue)
        self._issues = {key: tuple(value) for key, value in located.items()}
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [
                    Qt.ItemDataRole.DecorationRole,
                    Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.AccessibleDescriptionRole,
                    Qt.ItemDataRole.BackgroundRole,
                ],
            )

    def activate_issue(self, row_id: str, column_id: str) -> None:
        self.issue_activated.emit(row_id, column_id)

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        if not 0 <= column < len(self._dataset.columns):
            return
        self.layoutAboutToBeChanged.emit()
        self._sort_column = column
        self._sort_order = order
        self._rebuild_view_order()
        self.layoutChanged.emit()

    def set_filter(self, text: str) -> None:
        self.layoutAboutToBeChanged.emit()
        self._filter = str(text).strip().casefold()
        self._rebuild_view_order()
        self.layoutChanged.emit()

    def set_generation_order(self, row_ids: tuple[str, ...]) -> None:
        self._apply_dataset(self._dataset.with_order(row_ids), structural=False)

    def paste_matrix(
        self,
        start_row: int,
        start_column: int,
        values: tuple[tuple[str, ...], ...],
    ) -> None:
        if not values:
            return
        row_ids = self._view_order[start_row : start_row + len(values)]
        if len(row_ids) != len(values) or any(
            start_column + len(row) > len(self._dataset.columns) for row in values
        ):
            raise DatasetError("dataset.paste_out_of_bounds")
        changes: dict[tuple[str, str], str] = {}
        for row_id, row_values in zip(row_ids, values, strict=True):
            for offset, value in enumerate(row_values):
                changes[(row_id, self.column_id_at(start_column + offset))] = str(value)
        self.undo_stack.push(PasteCellsCommand(self, changes))

    def insert_rows(self, position: int, count: int = 1) -> None:
        self.undo_stack.push(InsertRowsCommand(self, position, count))

    def remove_rows(self, row_ids: tuple[str, ...]) -> None:
        self.undo_stack.push(RemoveRowsCommand(self, row_ids))

    def insert_column(self, position: int, label: str) -> None:
        self.undo_stack.push(InsertColumnCommand(self, position, label))

    def remove_column(self, column_id: str) -> None:
        self.undo_stack.push(RemoveColumnCommand(self, column_id))

    def rename_column(self, column_id: str, label: str) -> None:
        self.undo_stack.push(RenameColumnCommand(self, column_id, label))

    def _rebuild_view_order(self) -> None:
        rows = [self._dataset.row(row_id) for row_id in self._dataset.order]
        if self._filter:
            rows = [
                row
                for row in rows
                if any(self._filter in value.casefold() for value in row.values.values())
            ]
        if self._sort_column is not None:
            column_id = self.column_id_at(self._sort_column)
            rows.sort(
                key=lambda row: row.values[column_id].casefold(),
                reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
            )
        self._view_order = [row.row_id for row in rows]

    def _apply_dataset(
        self,
        dataset: TabularDataset,
        *,
        structural: bool,
        changed_cell: tuple[str, str] | None = None,
    ) -> None:
        if structural or self._sort_column is not None or self._filter:
            self.beginResetModel()
            self._dataset = dataset
            self._rebuild_view_order()
            self.endResetModel()
        else:
            self._dataset = dataset
            self._rebuild_view_order()
            if changed_cell is not None:
                try:
                    index = self.index_for_ids(*changed_cell)
                except DatasetError:
                    pass
                else:
                    self.dataChanged.emit(
                        index,
                        index,
                        [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
                    )
            elif self.rowCount() and self.columnCount():
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(self.rowCount() - 1, self.columnCount() - 1),
                    [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
                )
        self.dataset_changed.emit(dataset)


class _DatasetCommand(QUndoCommand):
    def __init__(
        self,
        model: DatasetTableModel,
        before: TabularDataset,
        after: TabularDataset,
        text: str,
        *,
        structural: bool,
        changed_cell: tuple[str, str] | None = None,
    ) -> None:
        super().__init__(text)
        self._model = model
        self._before = before
        self._after = after
        self._structural = structural
        self._changed_cell = changed_cell

    def redo(self) -> None:
        self._model._apply_dataset(
            self._after,
            structural=self._structural,
            changed_cell=self._changed_cell,
        )

    def undo(self) -> None:
        self._model._apply_dataset(
            self._before,
            structural=self._structural,
            changed_cell=self._changed_cell,
        )


class SetCellCommand(_DatasetCommand):
    def __init__(self, model, row_id: str, column_id: str, value: str) -> None:
        before = model.dataset
        after = before.with_cell(row_id, column_id, value)
        super().__init__(
            model,
            before,
            after,
            model._catalogs.text("data.command_edit_cell"),
            structural=False,
            changed_cell=(row_id, column_id),
        )


class PasteCellsCommand(_DatasetCommand):
    def __init__(self, model, changes: dict[tuple[str, str], str]) -> None:
        before = model.dataset
        rows: list[DataRow] = []
        for row in before.rows:
            values = dict(row.values)
            displays = dict(row.display_values or {})
            for (row_id, column_id), value in changes.items():
                if row.row_id == row_id:
                    values[column_id] = value
                    displays[column_id] = value
            rows.append(replace(row, values=values, display_values=displays))
        after = replace(before, rows=tuple(rows), revision=before.revision + 1)
        super().__init__(model, before, after, model._catalogs.text("data.command_paste_cells"), structural=False)


class InsertRowsCommand(_DatasetCommand):
    def __init__(self, model, position: int, count: int) -> None:
        before = model.dataset
        if count < 1:
            raise DatasetError("dataset.invalid_row_count")
        position = max(0, min(position, len(before.order)))
        blank_values = {column.column_id: "" for column in before.columns}
        inserted = tuple(
            DataRow(f"manual-{uuid4().hex}", None, blank_values)
            for _index in range(count)
        )
        order = before.order[:position] + tuple(row.row_id for row in inserted) + before.order[position:]
        after = replace(
            before,
            rows=before.rows + inserted,
            order=order,
            revision=before.revision + 1,
        )
        super().__init__(model, before, after, model._catalogs.text("data.command_insert_rows"), structural=True)


class RemoveRowsCommand(_DatasetCommand):
    def __init__(self, model, row_ids: tuple[str, ...]) -> None:
        before = model.dataset
        removed = set(row_ids)
        if not removed or not removed <= set(before.order):
            raise DatasetError("dataset.unknown_row")
        after = replace(
            before,
            rows=tuple(row for row in before.rows if row.row_id not in removed),
            order=tuple(row_id for row_id in before.order if row_id not in removed),
            revision=before.revision + 1,
        )
        super().__init__(model, before, after, model._catalogs.text("data.command_remove_rows"), structural=True)


class InsertColumnCommand(_DatasetCommand):
    def __init__(self, model, position: int, label: str) -> None:
        before = model.dataset
        column_id = normalize_column_id(label)
        if not column_id:
            raise DatasetError("dataset.blank_column")
        if column_id in {column.column_id for column in before.columns}:
            raise DatasetError("dataset.duplicate_column_id")
        position = max(0, min(position, len(before.columns)))
        columns = list(before.columns)
        columns.insert(position, Column(column_id, label.strip()))
        rows = tuple(_row_with_added_column(row, column_id) for row in before.rows)
        after = replace(
            before,
            columns=tuple(columns),
            rows=rows,
            revision=before.revision + 1,
        )
        super().__init__(model, before, after, model._catalogs.text("data.command_insert_column"), structural=True)


class RemoveColumnCommand(_DatasetCommand):
    def __init__(self, model, column_id: str) -> None:
        before = model.dataset
        if len(before.columns) <= 1:
            raise DatasetError("dataset.last_column")
        if column_id not in {column.column_id for column in before.columns}:
            raise DatasetError("dataset.unknown_column")
        columns = tuple(column for column in before.columns if column.column_id != column_id)
        rows = tuple(_row_without_column(row, column_id) for row in before.rows)
        after = replace(
            before,
            columns=columns,
            rows=rows,
            revision=before.revision + 1,
        )
        super().__init__(model, before, after, model._catalogs.text("data.command_remove_column"), structural=True)


class RenameColumnCommand(_DatasetCommand):
    def __init__(self, model, column_id: str, label: str) -> None:
        before = model.dataset
        if not label.strip():
            raise DatasetError("dataset.blank_column")
        normalized = normalize_column_id(label)
        conflicting = {
            normalize_column_id(column.label)
            for column in before.columns
            if column.column_id != column_id
        }
        if normalized in conflicting:
            raise DatasetError("dataset.duplicate_column_label")
        found = False
        columns: list[Column] = []
        for column in before.columns:
            if column.column_id == column_id:
                columns.append(replace(column, label=label.strip()))
                found = True
            else:
                columns.append(column)
        if not found:
            raise DatasetError("dataset.unknown_column")
        after = replace(
            before,
            columns=tuple(columns),
            revision=before.revision + 1,
        )
        super().__init__(model, before, after, model._catalogs.text("data.command_rename_column"), structural=True)


def _row_with_added_column(row: DataRow, column_id: str) -> DataRow:
    values = dict(row.values)
    displays = dict(row.display_values or {})
    values[column_id] = ""
    displays[column_id] = ""
    return replace(row, values=values, display_values=displays)


def _row_without_column(row: DataRow, column_id: str) -> DataRow:
    values = {key: value for key, value in row.values.items() if key != column_id}
    displays = {
        key: value for key, value in (row.display_values or {}).items() if key != column_id
    }
    return replace(row, values=values, display_values=displays)


def _issue_icon(issues: Iterable[Issue]) -> QIcon:
    severe = any(issue.severity is Severity.ERROR for issue in issues)
    pixmap = QPixmap(10, 10)
    pixmap.fill(QColor("#B42318" if severe else "#9A5A00"))
    return QIcon(pixmap)
