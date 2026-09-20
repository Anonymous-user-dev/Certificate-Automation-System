import pytest

from certificate_automation.importers.clipboard import (
    ClipboardImportError,
    append_clipboard,
    create_manual_dataset,
    import_clipboard,
    inspect_clipboard,
)


def test_tabular_clipboard_preview_and_import_preserve_unicode():
    text = "Name\tAward\nИрина\tЗолото\n李明\t优秀奖\n"

    inspection = inspect_clipboard(text)
    dataset = import_clipboard(text, mode="tabs")

    assert inspection.mode == "tabs"
    assert inspection.preview_rows[1] == ("Ирина", "Золото")
    assert tuple(row.value("name") for row in dataset.rows) == ("Ирина", "李明")
    assert dataset.source.kind == "clipboard"
    assert text not in dataset.source.label


def test_multiline_quoted_csv_cell_is_preserved():
    dataset = import_clipboard('name,award\n"Li\nMing",Gold\n', mode="csv")

    assert dataset.rows[0].value("name") == "Li\nMing"


def test_append_requires_exact_display_headers():
    dataset = import_clipboard("Name\tAward\nAna\tGold\n", mode="tabs")

    with pytest.raises(ClipboardImportError) as caught:
        append_clipboard(dataset, "Full Name\tAward\nBea\tSilver\n", mode="tabs")

    assert caught.value.code == "import.clipboard.header_mismatch"


def test_append_assigns_unique_stable_ids_and_preserves_existing_rows():
    dataset = import_clipboard("Name\tAward\nAna\tGold\n", mode="tabs")

    appended = append_clipboard(dataset, "Name\tAward\nBea\tSilver\n", mode="tabs")

    assert tuple(row.value("name") for row in appended.rows) == ("Ana", "Bea")
    assert len({row.row_id for row in appended.rows}) == 2
    assert appended.rows[0].row_id == dataset.rows[0].row_id


def test_manual_dataset_has_named_columns_and_no_recipient_rows():
    dataset = create_manual_dataset(("Full Name", "Award"))

    assert tuple(column.column_id for column in dataset.columns) == ("full_name", "award")
    assert dataset.rows == ()
    assert dataset.source.kind == "manual"


def test_ambiguous_single_column_clipboard_requires_mode_choice():
    inspection = inspect_clipboard("Name\nAna\n")

    assert inspection.requires_choice is True
    assert inspection.mode is None
