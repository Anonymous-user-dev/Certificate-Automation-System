from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.domain import Issue, Severity
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.table_model import DatasetTableModel


def _dataset(names=("Zulu", "Alpha"), *, blank_awards=False):
    columns = (Column("full_name", "Full Name"), Column("award", "Award"))
    rows = tuple(
        DataRow(
            f"row-{index}",
            index + 1,
            {"full_name": name, "award": "" if blank_awards else "Gold"},
        )
        for index, name in enumerate(names, start=1)
    )
    source = SourceSnapshot(
        "manual",
        "Test table",
        None,
        "a" * 64,
        datetime(2026, 9, 20, tzinfo=timezone.utc),
        {},
    )
    return TabularDataset(columns, rows, source)


def test_edit_after_sort_updates_stable_row(qtbot):
    model = DatasetTableModel(_dataset())
    changed = QSignalSpy(model.dataset_changed)

    model.sort(0, Qt.SortOrder.AscendingOrder)
    assert model.row_id_at(0) == "row-2"
    assert model.setData(model.index(0, 0), "Alice", Qt.ItemDataRole.EditRole)

    assert model.dataset.row("row-2").value("full_name") == "Alice"
    assert model.dataset.row("row-1").value("full_name") == "Zulu"
    assert changed.count() == 1


def test_multi_cell_paste_is_one_undoable_command(qtbot):
    model = DatasetTableModel(_dataset(("", ""), blank_awards=True))
    changed = QSignalSpy(model.dataChanged)

    model.paste_matrix(0, 0, (("Li", "Gold"), ("Chen", "Silver")))

    assert model.undo_stack.count() == 1
    assert changed.count() == 1
    assert model.dataset.row("row-1").value("full_name") == "Li"
    model.undo_stack.undo()
    assert all(not value for row in model.dataset.rows for value in row.values.values())
    model.undo_stack.redo()
    assert model.dataset.row("row-2").value("award") == "Silver"


def test_issue_decoration_and_accessible_description_identify_cell(qtbot):
    model = DatasetTableModel(_dataset(("",)))
    model.set_issues(
        (
            Issue(
                Severity.ERROR,
                "dataset",
                "validation.missing_name",
                row_id="row-1",
                column_id="full_name",
            ),
        )
    )

    index = model.index(0, 0)
    assert model.data(index, Qt.ItemDataRole.DecorationRole) is not None
    assert "required name" in model.data(
        index, Qt.ItemDataRole.AccessibleDescriptionRole
    ).casefold()


def test_filter_and_sort_never_change_generation_order(qtbot):
    model = DatasetTableModel(_dataset(("Zulu", "Alpha", "Beta")))
    original_order = model.dataset.order

    model.sort(0, Qt.SortOrder.AscendingOrder)
    model.set_filter("be")

    assert model.rowCount() == 1
    assert model.row_id_at(0) == "row-3"
    assert model.dataset.order == original_order


def test_insert_remove_and_rename_are_individually_undoable(qtbot):
    model = DatasetTableModel(_dataset(("Ana",)))

    model.insert_rows(1, 1)
    inserted_id = model.dataset.rows[-1].row_id
    model.insert_column(2, "Certificate Number")
    model.rename_column("certificate_number", "Official Number")
    model.remove_rows((inserted_id,))

    assert len(model.dataset.rows) == 1
    assert model.dataset.columns[-1].label == "Official Number"
    assert model.undo_stack.count() == 4
    model.undo_stack.undo()
    assert len(model.dataset.rows) == 2
    model.undo_stack.undo()
    assert model.dataset.columns[-1].label == "Certificate Number"


def test_issue_activation_emits_stable_ids(qtbot):
    model = DatasetTableModel(_dataset(("",)))
    observed = QSignalSpy(model.issue_activated)

    model.activate_issue("row-1", "full_name")

    assert observed.count() == 1
    assert observed.at(0) == ["row-1", "full_name"]


def test_undo_command_label_uses_active_locale(qtbot):
    catalogs = CatalogSet.load(package_root(), "ru")
    model = DatasetTableModel(_dataset(("Ana",)), catalogs=catalogs)

    model.setData(model.index(0, 0), "Anna")

    assert model.undo_stack.undoText() == "Изменить ячейку"
