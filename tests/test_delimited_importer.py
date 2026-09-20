import pytest

from certificate_automation.importers.delimited import (
    DelimitedImportError,
    import_delimited,
    inspect_delimited,
)


@pytest.mark.parametrize(
    ("encoding", "text", "expected"),
    [
        ("utf-8", "Name,Award\nAna,Gold\n", "Ana"),
        ("utf-8-sig", "Name,Award\n李明,优秀奖\n", "李明"),
        ("utf-16", "Name,Award\nИрина,Золото\n", "Ирина"),
        ("cp1251", "Имя,Награда\nАнна,Золото\n", "Анна"),
        ("gb18030", "姓名,奖项\n李明,优秀奖\n", "李明"),
    ],
)
def test_supported_encodings_round_trip(tmp_path, encoding, text, expected):
    path = tmp_path / f"recipients-{encoding}.csv"
    path.write_bytes(text.encode(encoding))

    inspection = inspect_delimited(path)
    dataset = import_delimited(path, inspection.encoding, inspection.delimiter)

    assert inspection.requires_choice is False
    assert dataset.rows[0].value(dataset.columns[0].column_id) == expected


def test_tsv_extension_and_quoted_multiline_fields_are_detected(tmp_path):
    path = tmp_path / "recipients.tsv"
    path.write_text('Name\tComment\n"Li\nMing"\t"Uses\ttab"\n', encoding="utf-8")

    inspection = inspect_delimited(path)
    dataset = import_delimited(path, inspection.encoding, inspection.delimiter)

    assert inspection.delimiter == "\t"
    assert dataset.rows[0].value("name") == "Li\nMing"
    assert dataset.rows[0].value("comment") == "Uses\ttab"


def test_ambiguous_legacy_encoding_requires_operator_choice(tmp_path):
    path = tmp_path / "ambiguous.csv"
    path.write_bytes(b"Name\n\xc0\xc1\n")

    inspection = inspect_delimited(path)

    assert inspection.requires_choice is True
    assert set(inspection.encoding_candidates) >= {"cp1251", "gb18030"}
    assert inspection.encoding is None


def test_inconsistent_width_is_never_padded_or_truncated(tmp_path):
    path = tmp_path / "broken.csv"
    path.write_bytes(b"name,award\nLi,Gold,extra\n")

    with pytest.raises(DelimitedImportError) as caught:
        import_delimited(path, "utf-8", ",")

    assert caught.value.code == "import.delimited.inconsistent_width"
    assert caught.value.row_number == 2


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"", "import.delimited.empty"),
        (b"name,award\nLi,\x00Gold\n", "import.delimited.nul_byte"),
        (b"name,name\nLi,Ming\n", "import.delimited.duplicate_header"),
        (b"name,\nLi,Gold\n", "import.delimited.blank_header"),
    ],
)
def test_malformed_tables_have_stable_codes(tmp_path, payload, code):
    path = tmp_path / "broken.csv"
    path.write_bytes(payload)

    with pytest.raises(DelimitedImportError) as caught:
        import_delimited(path, "utf-8", ",")

    assert caught.value.code == code


def test_import_never_changes_source_bytes(tmp_path):
    path = tmp_path / "recipients.csv"
    original = b"name,award\r\nAna,Gold\r\n"
    path.write_bytes(original)

    dataset = import_delimited(path, "utf-8", ",")

    assert path.read_bytes() == original
    assert dataset.source.path == path
    assert dataset.source.kind == "delimited"
