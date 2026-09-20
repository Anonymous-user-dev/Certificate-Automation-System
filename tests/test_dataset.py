from datetime import datetime, timezone

import pytest

from certificate_automation.dataset import (
    Column,
    DataRow,
    DatasetError,
    SourceSnapshot,
    TabularDataset,
)


def _dataset() -> TabularDataset:
    columns = (Column("full_name", "Full Name"), Column("award", "Award"))
    rows = (
        DataRow("row-1", 2, {"full_name": "Li Ming", "award": "Gold"}),
        DataRow("row-2", 3, {"full_name": "Chen Wei", "award": "Silver"}),
    )
    source = SourceSnapshot(
        kind="manual",
        label="Untitled table",
        path=None,
        sha256="a" * 64,
        imported_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        options={},
    )
    return TabularDataset(columns, rows, source)


def test_dataset_preserves_row_identity_when_reordered():
    dataset = _dataset()

    reordered = dataset.with_order(tuple(reversed(dataset.order)))

    assert reordered.row("row-2").value("full_name") == "Chen Wei"
    assert reordered.order == ("row-2", "row-1")
    assert reordered.revision == dataset.revision + 1


def test_edit_returns_new_revision_without_mutating_imported_snapshot():
    dataset = _dataset()

    edited = dataset.with_cell("row-2", "award", "Platinum")

    assert dataset.row("row-2").value("award") == "Silver"
    assert edited.row("row-2").value("award") == "Platinum"
    assert edited.revision == 1


def test_dataset_rejects_missing_cells_and_duplicate_ids():
    dataset = _dataset()
    bad_row = DataRow("row-1", 4, {"full_name": "Duplicate"})

    with pytest.raises(DatasetError) as caught:
        TabularDataset(dataset.columns, dataset.rows + (bad_row,), dataset.source)

    assert caught.value.code == "dataset.duplicate_row_id"


def test_canonical_hash_is_stable_and_changes_after_edit():
    dataset = _dataset()

    assert dataset.canonical_sha256() == _dataset().canonical_sha256()
    assert dataset.with_cell("row-1", "award", "Bronze").canonical_sha256() != (
        dataset.canonical_sha256()
    )


def test_invalid_generation_order_is_rejected():
    with pytest.raises(DatasetError) as caught:
        _dataset().with_order(("row-1", "missing"))

    assert caught.value.code == "dataset.invalid_order"
