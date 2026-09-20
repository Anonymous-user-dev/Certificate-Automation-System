# Certificate Automation 2.0 Operator Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a reliable, fully offline Windows desktop application that lets nontechnical staff import or enter recipient tables, map Word placeholders, preview and validate every record, generate selected official outputs, and optionally publish one verified combined PDF in English, Simplified Chinese, or Russian.

**Architecture:** Introduce one source-independent `TabularDataset`, typed mapping plans, structured issue codes, and a versioned local project store beneath a redesigned PySide6 workspace. Preserve the proven OOXML renderer, isolated Word conversion, transactional staging, redacted diagnostics, and recovery behavior, then extend the batch transaction with selectable outputs and verified PDF merging.

**Tech Stack:** Python 3.12+, PySide6 6.8+/6.11+, openpyxl 3.1+, lxml 6+, pypdf 6+, SQLite via the standard library, pywin32 on Windows, pytest, pytest-qt, PyInstaller, Inno Setup.

**Spec:** `docs/superpowers/specs/2026-09-20-operator-workspace-i18n-multisource-design.md`

## Global Constraints

- Runtime operation remains fully offline: no accounts, telemetry, network calls, cloud storage, remote translation, or online validation.
- Never modify an imported source file or the selected Word template.
- Never publish a partial or unverified official batch; generation remains an all-or-nothing staging transaction.
- Do not silently guess ambiguous encodings, delimiters, mappings, dates, merged cells, formula values, or hidden data.
- Supported direct inputs are `.xlsx`, `.csv`, `.tsv`, clipboard tables, and tables created in the application.
- Supported locales are exactly `en`, `zh_CN`, and `ru`; English is the fallback.
- PDF generation requires 64-bit Windows with desktop Microsoft Word; DOCX-only generation does not.
- Arbitrary scripts, formulas, macros, plug-ins, regular-expression transformations, and executable extensions are excluded.
- Preserve the user's unrelated modifications in `.test`, `system/data/students.xlsx`, `system/src/main.py`, and `system/templates/certificate_template.docx`; never stage them.
- Use test-driven development and commit each completed task before beginning the next task.

## Review Focus

- A CSV that decodes as both Windows-1251 and GB18030 must stop at an import preview instead of choosing a lossy or low-confidence interpretation; Task 3 pins this behavior.
- Editing a sorted table must retain stable row identities so previews, filename errors, and generated output still refer to the correct person; Task 4 pins this behavior.
- Changing the template after saving a draft must invalidate inspection, mappings, previews, and generation until the new hash is reviewed; Task 5 pins this behavior.
- A merged PDF whose page count or readable structure differs from the verified individual inputs must prevent publication of the entire batch; Task 7 pins this behavior.
- Russian text at 200% scaling and long translated validation messages must remain reachable without clipping the primary action; Task 10 pins this behavior with layout and packaged-app acceptance checks.

## File Structure

New core files:

- `src/certificate_automation/i18n.py` — locale loading, fallback, parameter-safe formatting, and catalog validation.
- `src/certificate_automation/locales/en.json` — canonical English keys and text.
- `src/certificate_automation/locales/zh_CN.json` — complete Simplified Chinese catalog.
- `src/certificate_automation/locales/ru.json` — complete Russian catalog.
- `src/certificate_automation/dataset.py` — immutable source snapshot, stable row/column records, edits, ordering, and canonical hash.
- `src/certificate_automation/importers/excel.py` — `.xlsx` discovery and safe import into `TabularDataset`.
- `src/certificate_automation/importers/delimited.py` — encoding/delimiter inspection and CSV/TSV import.
- `src/certificate_automation/importers/clipboard.py` — clipboard text preview and import.
- `src/certificate_automation/project.py` — schema-versioned SQLite draft persistence and rotating backups.
- `src/certificate_automation/output_options.py` — immutable output-selection and batch naming records.
- `src/certificate_automation/pdf_merge.py` — ordered PDF merge and post-merge verification.
- `src/certificate_automation/ui/theme.py` — professional stylesheet and scaling-safe visual tokens.
- `src/certificate_automation/ui/workspace.py` — home screen, step navigation, persistent header, and page coordination.
- `src/certificate_automation/ui/table_model.py` — editable Qt table model with stable IDs and undo/redo commands.
- `src/certificate_automation/ui/data_page.py` — import cards, preview decisions, table editor, and cell issues.
- `src/certificate_automation/ui/template_page.py` — template inspection and placeholder cards.
- `src/certificate_automation/ui/match_page.py` — typed mapping editor and representative samples.
- `src/certificate_automation/ui/review_page.py` — recipient selector, resolved fields, PDF preview, and issue navigation.
- `src/certificate_automation/ui/output_page.py` — format, combined-PDF, order, batch name, and destination controls.
- `src/certificate_automation/ui/results_page.py` — phase progress, cancellation, failure recovery, and result actions.

Existing files retained and modified:

- `src/certificate_automation/domain.py` — structured, localizable issues and stable cell locations.
- `src/certificate_automation/workbook.py` — compatibility facade that delegates to the Excel importer.
- `src/certificate_automation/mapping.py` — typed mapping sources and deterministic evaluation.
- `src/certificate_automation/validation.py` — dataset-wide mapping/output preflight.
- `src/certificate_automation/batch.py` — dataset request, selectable outputs, merged PDF, and transactional publication.
- `src/certificate_automation/audit.py` — locale-neutral manifest schema 2 and localized HTML summary.
- `src/certificate_automation/app.py` — service composition, settings, project store, and workspace entry point.
- `src/certificate_automation/ui/main_window.py` — compatibility import that exposes the new workspace window.
- `packaging/certificate-automation.spec` — include locale catalogs and updated guide/examples.
- `packaging/installer.iss` and `pyproject.toml` — version 2.0.0 and release metadata.
- `docs/user-guide.md` and `README.md` — three-locale workflow, offline guarantees, and supported-source matrix.

---

### Task 1: Structured Issues and Complete Translation Runtime

**Files:**
- Create: `src/certificate_automation/i18n.py`
- Create: `src/certificate_automation/locales/en.json`
- Create: `src/certificate_automation/locales/zh_CN.json`
- Create: `src/certificate_automation/locales/ru.json`
- Modify: `src/certificate_automation/domain.py`
- Modify: `src/certificate_automation/audit.py`
- Modify: `src/certificate_automation/validation.py`
- Modify: `src/certificate_automation/ui/validation_page.py`
- Test: `tests/test_i18n.py`
- Test: `tests/test_domain.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: no new interfaces.
- Produces: `Issue(severity, source, code, parameters={}, row_id=None, column_id=None)`, `TranslationCatalog.load(locale)`, `TranslationCatalog.text(key, **parameters)`, `CatalogSet.set_locale(locale)`, `CatalogSet.changed`, and `validate_catalogs(package_root) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing tests for structured issues, fallback, parameter parity, and privacy**

```python
def test_catalogs_have_identical_keys_and_parameters():
    assert validate_catalogs(PACKAGE_ROOT) == ()

def test_unknown_locale_falls_back_to_english():
    catalogs = CatalogSet.load(PACKAGE_ROOT, locale="de")
    assert catalogs.locale == "en"
    assert catalogs.text("nav.data") == "Recipient Data"

def test_issue_is_language_neutral_and_located():
    issue = Issue(
        Severity.ERROR,
        "dataset",
        "validation.blank_mapped_value",
        {"placeholder": "FULL_NAME"},
        row_id="row-7",
        column_id="full_name",
    )
    assert not hasattr(issue, "message")
    assert issue.parameters["placeholder"] == "FULL_NAME"

def test_manifest_contains_codes_but_not_localized_issue_text(tmp_path):
    path = write_manifest(audit_context_with_warning(), tmp_path / "manifest.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["warnings"][0]["code"] == "validation.blank_mapped_value"
    assert "message" not in payload["warnings"][0]
```

- [ ] **Step 2: Run the focused tests and confirm the old message-bearing model fails**

Run: `python -m pytest tests/test_i18n.py tests/test_domain.py tests/test_audit.py -q`

Expected: FAIL because `certificate_automation.i18n` does not exist and `Issue` still stores preformatted English.

- [ ] **Step 3: Implement immutable structured issues and the catalog runtime**

```python
@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    source: str
    code: str
    parameters: Mapping[str, str | int] = field(default_factory=dict)
    row_id: str | None = None
    column_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.ERROR

class TranslationCatalog:
    def text(self, key: str, **parameters: object) -> str:
        template = self._messages.get(key, self._fallback[key])
        return template.format_map(_StrictParameters(parameters))

def validate_catalogs(package_root: Path) -> tuple[str, ...]:
    catalogs = {
        locale: json.loads((package_root / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        for locale in ("en", "zh_CN", "ru")
    }
    errors: list[str] = []
    english_keys = set(catalogs["en"])
    for locale, messages in catalogs.items():
        if set(messages) != english_keys:
            errors.append(f"{locale}: key set differs from en")
        for key in english_keys & set(messages):
            expected = {name for _, name, _, _ in Formatter().parse(catalogs["en"][key]) if name}
            actual = {name for _, name, _, _ in Formatter().parse(messages[key]) if name}
            if actual != expected:
                errors.append(f"{locale}:{key}: parameters differ")
    return tuple(errors)
```

Populate the catalogs with the navigation, home, import, mapping, review, output, generation, recovery, accessibility, and every existing validation/error key. Translate user actions and explanations; retain product name, placeholder text, file paths, and recipient values unchanged.

- [ ] **Step 4: Migrate audit warnings and existing call sites to codes plus parameters**

```python
"warnings": [
    {
        "code": issue.code,
        "source": issue.source,
        "row_id": issue.row_id,
        "column_id": issue.column_id,
        "parameters": dict(issue.parameters),
    }
    for issue in context.warnings
]
```

Pass a `TranslationCatalog` and locale into `write_summary`; render warning text there while keeping manifest and support-log records language-neutral. Convert every existing `Issue(...)` construction in `validation.py` to a code and parameter mapping, and convert `ValidationPage.set_report()` to call the active catalog. This keeps the complete existing application runnable immediately after the issue-model migration.

- [ ] **Step 5: Run localization, domain, audit, and full regression tests**

Run: `python -m pytest tests/test_i18n.py tests/test_domain.py tests/test_audit.py -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: all existing tests PASS after their issue assertions use codes and parameters.

- [ ] **Step 6: Commit and push the localization foundation**

```bash
git add src/certificate_automation/i18n.py src/certificate_automation/locales src/certificate_automation/domain.py src/certificate_automation/audit.py src/certificate_automation/validation.py src/certificate_automation/ui/validation_page.py tests/test_i18n.py tests/test_domain.py tests/test_audit.py tests/test_validation.py tests/test_ui_workflow.py
git commit -m "feat: add offline localization foundation"
git push origin main
```

### Task 2: Canonical Dataset and Defensive Excel Import

**Files:**
- Create: `src/certificate_automation/dataset.py`
- Create: `src/certificate_automation/importers/__init__.py`
- Create: `src/certificate_automation/importers/excel.py`
- Modify: `src/certificate_automation/workbook.py`
- Test: `tests/test_dataset.py`
- Test: `tests/test_excel_importer.py`
- Modify: `tests/test_workbook.py`

**Interfaces:**
- Consumes: `Issue` from Task 1.
- Produces: `Column(column_id, label)`, `DataRow(row_id, source_row, values, display_values)`, `SourceSnapshot(kind, label, path, sha256, imported_at, options)`, `TabularDataset(columns, rows, source, revision=0, order=())`, `ExcelInspection`, `inspect_excel(path)`, and `import_excel(path, sheet_name, include_hidden=False) -> TabularDataset`.

- [ ] **Step 1: Write failing model and Excel safety tests**

```python
def test_dataset_preserves_row_identity_when_reordered():
    dataset = make_dataset(names=("Li Ming", "Chen Wei"))
    reordered = dataset.with_order(tuple(reversed(dataset.order)))
    assert reordered.row("row-2").value("full_name") == "Chen Wei"
    assert reordered.revision == dataset.revision + 1

def test_excel_formula_without_cached_value_is_rejected(tmp_path):
    path = workbook_with_formula(tmp_path, cached_value_missing=True)
    with pytest.raises(ExcelImportError) as caught:
        import_excel(path, "Recipients")
    assert caught.value.code == "import.excel.formula_cache_missing"

def test_excel_reports_hidden_rows_before_import(tmp_path):
    path = workbook_with_hidden_row(tmp_path)
    inspection = inspect_excel(path)
    assert inspection.hidden_rows == (3,)
    assert inspection.requires_hidden_data_choice is True

def test_excel_rejects_merged_cells_intersecting_data(tmp_path):
    path = workbook_with_merge(tmp_path, "A2:B2")
    with pytest.raises(ExcelImportError) as caught:
        import_excel(path, "Recipients")
    assert caught.value.code == "import.excel.merged_data_cells"
```

- [ ] **Step 2: Run the focused tests and confirm imports are missing**

Run: `python -m pytest tests/test_dataset.py tests/test_excel_importer.py -q`

Expected: FAIL with missing `certificate_automation.dataset` and `certificate_automation.importers.excel`.

- [ ] **Step 3: Implement immutable dataset records and edit-returning methods**

```python
@dataclass(frozen=True, slots=True)
class TabularDataset:
    columns: tuple[Column, ...]
    rows: tuple[DataRow, ...]
    source: SourceSnapshot
    revision: int = 0
    order: tuple[str, ...] = ()

    def row(self, row_id: str) -> DataRow:
        return next(row for row in self.rows if row.row_id == row_id)

    def with_cell(self, row_id: str, column_id: str, value: str) -> "TabularDataset":
        rows = tuple(
            row.with_value(column_id, value) if row.row_id == row_id else row
            for row in self.rows
        )
        return replace(self, rows=rows, revision=self.revision + 1)

    def with_order(self, order: tuple[str, ...]) -> "TabularDataset":
        if set(order) != {row.row_id for row in self.rows} or len(order) != len(self.rows):
            raise DatasetError("dataset.invalid_order")
        return replace(self, order=order, revision=self.revision + 1)

    def canonical_sha256(self) -> str:
        payload = json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()
```

Each method validates unique IDs, rectangular values, and complete order membership; returns a new instance; and increments `revision` exactly once.

- [ ] **Step 4: Implement two-pass Excel inspection and import**

```python
@dataclass(frozen=True, slots=True)
class ExcelInspection:
    sheet_names: tuple[str, ...]
    hidden_sheets: tuple[str, ...]
    hidden_rows: tuple[int, ...]
    hidden_columns: tuple[str, ...]
    merged_ranges: tuple[str, ...]
    formula_cells: tuple[str, ...]
    requires_hidden_data_choice: bool

def import_excel(path: Path, sheet_name: str, *, include_hidden: bool = False) -> TabularDataset:
    formulas = load_workbook(path, read_only=False, data_only=False)
    cached = load_workbook(path, read_only=False, data_only=True)
    try:
        inspection = inspect_loaded_sheet(formulas[sheet_name], cached[sheet_name])
        inspection.require_importable(include_hidden=include_hidden)
        return dataset_from_excel_sheets(
            formulas[sheet_name], cached[sheet_name], inspection, Path(path), include_hidden
        )
    finally:
        formulas.close()
        cached.close()
```

Implement the private `inspect_loaded_sheet` and `dataset_from_excel_sheets` helpers in the same module; the former compares formulas with cached values and records hidden/merged state, while the latter normalizes headers, creates stable IDs, preserves display values, and hashes the unchanged source file.

Keep `workbook.py` as a deprecated facade exposing `list_worksheets` and `load_workbook_data`. Until Task 6 migrates the remaining callers, `load_workbook_data` converts the canonical import back into the current `WorkbookData` record without rereading the source; `import_excel` is the only new-code entry point and always returns `TabularDataset`.

- [ ] **Step 5: Run model, Excel, compatibility, and full regression tests**

Run: `python -m pytest tests/test_dataset.py tests/test_excel_importer.py tests/test_workbook.py -q`

Expected: PASS, including visible/hidden choice, formulas, merges, Unicode, duplicate headers, and unchanged source hash.

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit and push the canonical data layer**

```bash
git add src/certificate_automation/dataset.py src/certificate_automation/importers src/certificate_automation/workbook.py tests/test_dataset.py tests/test_excel_importer.py tests/test_workbook.py
git commit -m "feat: add canonical dataset and safe Excel import"
git push origin main
```

### Task 3: CSV, TSV, Clipboard, and Manual Data Sources

**Files:**
- Create: `src/certificate_automation/importers/delimited.py`
- Create: `src/certificate_automation/importers/clipboard.py`
- Test: `tests/test_delimited_importer.py`
- Test: `tests/test_clipboard_importer.py`
- Modify: `tests/fixtures.py`

**Interfaces:**
- Consumes: `TabularDataset` and `SourceSnapshot` from Task 2.
- Produces: `DelimitedInspection`, `inspect_delimited(path)`, `import_delimited(path, encoding, delimiter)`, `inspect_clipboard(text)`, `import_clipboard(text, mode)`, and `create_manual_dataset(column_labels)`.

- [ ] **Step 1: Write failing tests for exact decoding and rectangular tables**

```python
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1251", "gb18030"])
def test_supported_encodings_round_trip(tmp_path, encoding):
    path = encoded_table(tmp_path, encoding)
    inspection = inspect_delimited(path)
    dataset = import_delimited(path, inspection.encoding, inspection.delimiter)
    assert dataset.rows[0].display_values[dataset.columns[0].column_id]

def test_ambiguous_legacy_encoding_requires_operator_choice(tmp_path):
    inspection = inspect_delimited(ambiguous_legacy_bytes(tmp_path))
    assert inspection.requires_choice is True
    assert len(inspection.encoding_candidates) >= 2

def test_inconsistent_width_is_never_padded(tmp_path):
    path = write_bytes(tmp_path, b"name,award\nLi,Gold,extra\n")
    with pytest.raises(DelimitedImportError) as caught:
        import_delimited(path, "utf-8", ",")
    assert caught.value.code == "import.delimited.inconsistent_width"

def test_multiline_quoted_cell_and_tabular_paste_are_preserved():
    dataset = import_clipboard('name,award\n"Li\nMing",Gold\n', mode="csv")
    assert dataset.rows[0].value(dataset.columns[0].column_id) == "Li\nMing"
```

- [ ] **Step 2: Run the focused tests and confirm the adapters are absent**

Run: `python -m pytest tests/test_delimited_importer.py tests/test_clipboard_importer.py -q`

Expected: FAIL with missing importer modules.

- [ ] **Step 3: Implement lossless inspection with explicit choice records**

```python
@dataclass(frozen=True, slots=True)
class DelimitedInspection:
    encoding_candidates: tuple[str, ...]
    delimiter_candidates: tuple[str, ...]
    encoding: str | None
    delimiter: str | None
    preview_rows: tuple[tuple[str, ...], ...]
    requires_choice: bool

def inspect_delimited(path: Path) -> DelimitedInspection:
    raw = Path(path).read_bytes()
    candidates = strict_decode_candidates(raw, ("utf-8", "cp1251", "gb18030"))
    scored = tuple(score_tabular_candidate(text, encoding) for encoding, text in candidates)
    best = unambiguous_best(scored)
    return DelimitedInspection.from_scored_candidates(scored, best)
```

Define `strict_decode_candidates`, `score_tabular_candidate`, and `unambiguous_best` in this module. BOM detection returns only its declared Unicode encoding; non-BOM candidates survive only strict decoding and rectangular delimiter parsing; a best choice exists only when one candidate has a unique non-lossy score.

Use `csv.reader(io.StringIO(decoded_text, newline=""), delimiter=selected_delimiter, strict=True)` for quoted delimiters and multiline values. Compare every row length to the header before constructing the dataset. Reject NUL bytes, empty input, blank headers, and normalized header collisions with stable issue codes.

- [ ] **Step 4: Implement clipboard preview, replace/append, and blank manual tables**

```python
def import_clipboard(text: str, mode: Literal["tabs", "csv"]) -> TabularDataset:
    delimiter = "\t" if mode == "tabs" else ","
    rows = tuple(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    return dataset_from_rectangular_rows(rows, SourceSnapshot.clipboard(text))

def append_clipboard(dataset: TabularDataset, text: str, mode: str) -> TabularDataset:
    incoming = import_clipboard(text, mode)
    if tuple(column.label for column in incoming.columns) != tuple(
        column.label for column in dataset.columns
    ):
        raise ClipboardImportError("import.clipboard.header_mismatch")
    return dataset.with_rows(dataset.rows + remap_rows(incoming, dataset.columns))

def create_manual_dataset(column_labels: tuple[str, ...]) -> TabularDataset:
    columns = columns_from_labels(column_labels)
    source = SourceSnapshot.manual(imported_at=utc_now())
    return TabularDataset(columns=columns, rows=(), source=source, order=())
```

- [ ] **Step 5: Run adapter contracts and full regression tests**

Run: `python -m pytest tests/test_delimited_importer.py tests/test_clipboard_importer.py -q`

Expected: PASS for BOMs, Cyrillic, CJK, embedded newlines, quoted delimiters, ambiguous choices, and inconsistent widths.

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit and push all non-Excel sources**

```bash
git add src/certificate_automation/importers tests/test_delimited_importer.py tests/test_clipboard_importer.py tests/fixtures.py
git commit -m "feat: import offline tables from text and clipboard"
git push origin main
```

### Task 4: Editable Table Model, Undo/Redo, and Stable Identity

**Files:**
- Create: `src/certificate_automation/ui/table_model.py`
- Create: `src/certificate_automation/ui/data_page.py`
- Test: `tests/test_table_model.py`
- Test: `tests/test_data_page.py`

**Interfaces:**
- Consumes: immutable dataset edits from Task 2 and source adapters from Task 3.
- Produces: `DatasetTableModel.dataset_changed(TabularDataset)`, `DatasetTableModel.issue_activated(row_id, column_id)`, `SetCellCommand`, `InsertRowsCommand`, `RemoveRowsCommand`, `InsertColumnCommand`, `RemoveColumnCommand`, `RenameColumnCommand`, and `DataPage.dataset_accepted(TabularDataset)`.

- [ ] **Step 1: Write failing Qt model tests for sorting, edits, and undo**

```python
def test_edit_after_sort_updates_stable_row(qtbot):
    model = DatasetTableModel(make_dataset(names=("Zulu", "Alpha")))
    model.sort(0, Qt.SortOrder.AscendingOrder)
    assert model.row_id_at(0) == "row-2"
    assert model.setData(model.index(0, 0), "Alice", Qt.ItemDataRole.EditRole)
    assert model.dataset.row("row-2").value("full_name") == "Alice"
    assert model.dataset.row("row-1").value("full_name") == "Zulu"

def test_multi_cell_paste_is_one_undoable_command(qtbot):
    model = DatasetTableModel(make_blank_dataset(2, 2))
    model.paste_matrix(0, 0, (("Li", "Gold"), ("Chen", "Silver")))
    model.undo_stack.undo()
    assert all(not value for row in model.dataset.rows for value in row.values.values())

def test_issue_decoration_uses_icon_and_accessible_description(qtbot):
    model = DatasetTableModel(make_dataset(names=("",)))
    model.set_issues((blank_name_issue("row-1", "full_name"),))
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole) is not None
    assert "required" in model.data(model.index(0, 0), Qt.ItemDataRole.AccessibleDescriptionRole)
```

- [ ] **Step 2: Run table tests and verify failure**

Run: `python -m pytest tests/test_table_model.py tests/test_data_page.py -q`

Expected: FAIL because the table model and data page do not exist.

- [ ] **Step 3: Implement a Qt model that translates view positions to stable IDs**

```python
class DatasetTableModel(QAbstractTableModel):
    dataset_changed = Signal(object)
    issue_activated = Signal(str, str)

    def row_id_at(self, view_row: int) -> str:
        return self._view_order[view_row]

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        row_id = self.row_id_at(index.row())
        column_id = self._columns[index.column()].column_id
        self.undo_stack.push(SetCellCommand(self, row_id, column_id, str(value)))
        return True
```

Every command stores IDs and before/after immutable datasets, emits the smallest valid Qt model signal, and exposes a translated action label. Sorting changes only `_view_order`; generation order changes only through an explicit `set_generation_order` action.

- [ ] **Step 4: Implement the data-source cards, import-preview dialog, and editor toolbar**

```python
class DataPage(QWidget):
    dataset_accepted = Signal(object)
    import_requested = Signal(str)
    paste_requested = Signal()

    def set_dataset(self, dataset: TabularDataset) -> None:
        self.model.replace_dataset(dataset)
        self.source_label.setText(dataset.source.label)
        self.count_label.setText(self._catalog.text(
            "data.counts", rows=len(dataset.rows), columns=len(dataset.columns)
        ))

    def set_issues(self, issues: tuple[Issue, ...]) -> None:
        self.model.set_issues(issues)
        self.issue_list.set_issues(issues)

    def focus_cell(self, row_id: str, column_id: str) -> None:
        index = self.model.index_for_ids(row_id, column_id)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index)

    def retranslate(self, catalog: TranslationCatalog) -> None:
        self._catalog = catalog
        self.title.setText(catalog.text("data.title"))
        self.continue_button.setText(catalog.text("action.continue"))
```

The page contains four clearly labeled source cards, a source summary, row/column counts, search field, add/remove row and column actions, undo/redo, and a primary Continue action. Import-preview acceptance must show selected encoding, delimiter, worksheet, and hidden-data policy before replacing current edits.

- [ ] **Step 5: Run Qt and full regression tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_table_model.py tests/test_data_page.py -q`

Expected: PASS, including the Review Focus sorted-edit case.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit and push the editable data workspace**

```bash
git add src/certificate_automation/ui/table_model.py src/certificate_automation/ui/data_page.py tests/test_table_model.py tests/test_data_page.py
git commit -m "feat: add safe in-app recipient table editor"
git push origin main
```

### Task 5: Versioned Draft Projects, Autosave, and Recovery

**Files:**
- Create: `src/certificate_automation/project.py`
- Test: `tests/test_project.py`
- Modify: `src/certificate_automation/recovery.py`
- Modify: `tests/test_shutdown.py`

**Interfaces:**
- Consumes: dataset records from Task 2; serialized typed mappings are accepted as an opaque schema object until Task 6.
- Produces: `ProjectState`, `ProjectStore.create(path)`, `ProjectStore.open(path)`, `ProjectStore.save(state)`, `ProjectStore.backup()`, `ProjectStore.recover_latest(path)`, and `ProjectCoordinator.mark_dirty(state)`.

- [ ] **Step 1: Write failing transactional persistence and invalidation tests**

```python
def test_project_round_trip_preserves_ids_order_and_unicode(tmp_path):
    state = make_project_state(dataset=unicode_dataset())
    store = ProjectStore.create(tmp_path / "awards.certproject")
    store.save(state)
    reopened = ProjectStore.open(store.path).load()
    assert reopened.dataset == state.dataset
    assert reopened.dataset.order == state.dataset.order

def test_failed_save_leaves_last_valid_revision(tmp_path, monkeypatch):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    store.save(make_project_state(revision=1))
    monkeypatch.setattr(store, "_commit", raise_disk_full)
    with pytest.raises(ProjectSaveError):
        store.save(make_project_state(revision=2))
    assert ProjectStore.open(store.path).load().revision == 1

def test_changed_template_hash_invalidates_downstream_state(tmp_path):
    state = make_project_state(template_hash="old", mappings={"FULL_NAME": {}})
    reopened = state.reconcile_template(template_path_with_hash(tmp_path, "new"))
    assert reopened.template_inspection is None
    assert reopened.mapping_plan is None
    assert reopened.preview_revision is None

def test_newer_schema_is_opened_read_only(tmp_path):
    path = sqlite_project(tmp_path, schema_version=999)
    opened = ProjectStore.open(path)
    assert opened.read_only is True
    assert opened.issue_code == "project.newer_schema"
```

- [ ] **Step 2: Run project tests and verify failure**

Run: `python -m pytest tests/test_project.py tests/test_shutdown.py -q`

Expected: FAIL because `ProjectStore` is missing.

- [ ] **Step 3: Implement schema 1 using SQLite transactions and JSON payloads**

```sql
PRAGMA journal_mode=WAL;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE revisions (
    revision INTEGER PRIMARY KEY,
    saved_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL
);
```

Serialize canonical dataset IDs, rows, display values, source metadata, order, mapping plan, template path/hash, output options, locale, acknowledgements, and active step. Verify the payload hash before deserialization. Retain the newest three valid revisions and create backups with `sqlite3.Connection.backup()` only after a committed save.

- [ ] **Step 4: Implement debounced autosave and close safety**

```python
class ProjectCoordinator(QObject):
    save_failed = Signal(object)
    saved = Signal(int)

    def mark_dirty(self, state: ProjectState) -> None:
        self._pending = state
        self._timer.start(750)

    def flush(self) -> bool:
        if self._pending is None:
            return True
        self._store.save(self._pending)
        self._pending = None
        return True
```

On application close, flush before accepting the event. If save fails, keep the window open and present a localized Save As, Retry, or Discard Draft choice. Extend `RecoveryService` to list both incomplete output transactions and recoverable project backups without mixing their actions.

- [ ] **Step 5: Run project, shutdown, and full regression tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_project.py tests/test_shutdown.py -q`

Expected: PASS for atomic save, three-backup rotation, corruption fallback, newer-schema read-only mode, template invalidation, and close flushing.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit and push draft persistence**

```bash
git add src/certificate_automation/project.py src/certificate_automation/recovery.py tests/test_project.py tests/test_shutdown.py
git commit -m "feat: add autosaved local draft projects"
git push origin main
```

### Task 6: Typed Mapping Plans and Dataset-Wide Validation

**Files:**
- Create: `src/certificate_automation/output_options.py`
- Modify: `src/certificate_automation/mapping.py`
- Modify: `src/certificate_automation/validation.py`
- Modify: `src/certificate_automation/filenames.py`
- Test: `tests/test_mapping.py`
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: `TabularDataset`, `Issue`, and `TemplateInspection`.
- Produces: `ColumnValue`, `FixedValue`, `SequenceValue`, `SourceRowValue`, `FormattedDateValue`, `JoinValue`, `MappingPlan`, `MappingSuggestion`, `evaluate_plan(plan, dataset, row_id)`, `OutputOptions`, and `validate_preflight(dataset, template, plan, output_options)`.

- [ ] **Step 1: Write failing typed-mapping and all-row validation tests**

```python
def test_typed_mapping_evaluates_deterministically():
    plan = MappingPlan({
        "FULL_NAME": JoinValue(("given", "family"), " "),
        "CERT_NO": SequenceValue(start=41, step=1, width=4, prefix="C-", suffix=""),
        "DATE": FormattedDateValue(ColumnValue("date"), "%Y-%m-%d", "%d %B %Y"),
    })
    values = evaluate_plan(plan, dataset_with_dates(), "row-2")
    assert values == {"FULL_NAME": "Chen Wei", "CERT_NO": "C-0042", "DATE": "20 September 2026"}

def test_sequence_follows_generation_order_not_visual_sort():
    dataset = make_dataset().with_order(("row-3", "row-1", "row-2"))
    plan = MappingPlan({"N": SequenceValue(1, 1, 2, "", "")})
    assert evaluate_plan(plan, dataset, "row-3")["N"] == "01"
    assert evaluate_plan(plan, dataset, "row-1")["N"] == "02"

def test_ambiguous_date_blocks_exact_cell():
    report = validate_preflight(dataset_with_value("date", "01/02/2026"), template(), date_plan(), options())
    issue = next(issue for issue in report.issues if issue.code == "mapping.date_ambiguous")
    assert (issue.row_id, issue.column_id) == ("row-1", "date")

def test_normalization_filename_collision_blocks_both_rows():
    report = validate_preflight(unicode_collision_dataset(), template(), name_plan(), options())
    assert sum(i.code == "output.filename_collision" for i in report.issues) == 2
```

- [ ] **Step 2: Run mapping and validation tests and verify old mappings fail**

Run: `python -m pytest tests/test_mapping.py tests/test_validation.py -q`

Expected: FAIL because typed mapping records and dataset-aware validation are missing.

- [ ] **Step 3: Implement the closed mapping union and serialization**

```python
MappingSource = ColumnValue | FixedValue | SequenceValue | SourceRowValue | FormattedDateValue | JoinValue

@dataclass(frozen=True, slots=True)
class MappingPlan:
    sources: Mapping[str, MappingSource]

    def unresolved(self, placeholders: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in placeholders if name not in self.sources)

    def to_json(self) -> dict[str, object]:
        return {
            name: {"type": source.kind, **source.parameters()}
            for name, source in sorted(self.sources.items())
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "MappingPlan":
        return cls({name: mapping_source_from_json(record) for name, record in value.items()})
```

Date parsing uses explicitly selected `input_format`; it never invokes locale-dependent fuzzy parsing. `JoinValue` accepts only existing columns and a literal separator. Suggestion returns exact normalized matches as `exact`, single close-label matches as `suggested`, and all others as `unresolved`; only exact mappings may be accepted without a user click.

Create the immutable `OutputOptions` record here with `docx`, `individual_pdf`, `combined_pdf`, `destination`, `batch_name`, and ordered row IDs. Its constructor rejects an empty output selection, missing destination, duplicate/missing row IDs, and combined PDF without a Windows-safe batch name before validation performs filesystem checks.

- [ ] **Step 4: Migrate preflight to stable row IDs and selected output options**

```python
@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[Issue, ...]
    filename_stems: Mapping[str, str]
    estimated_bytes: int
    dataset_revision: int
    template_sha256: str

    @property
    def ready(self) -> bool:
        return not any(issue.blocking for issue in self.issues)
```

Evaluate every placeholder for every generation-ordered row. Detect blanks, overlong values, exact duplicate resolved records, Windows reserved names, NFC/casefold filename collisions, path-length overflow, unsupported output combinations, missing Word, destination equality, write access, and disk space. Return all issues in deterministic source/order sequence.

- [ ] **Step 5: Run mapping, validation, and full regression tests**

Run: `python -m pytest tests/test_mapping.py tests/test_validation.py -q`

Expected: PASS for all six mapping types, JSON round trips, all-row validation, ambiguous dates, duplicate data, Unicode filename collisions, and unsafe paths.

Run: `python -m pytest -q`

Expected: PASS after callers use `MappingPlan` and `TabularDataset`.

- [ ] **Step 6: Commit and push the mapping engine**

```bash
git add src/certificate_automation/output_options.py src/certificate_automation/mapping.py src/certificate_automation/validation.py src/certificate_automation/filenames.py tests/test_mapping.py tests/test_validation.py
git commit -m "feat: add reviewed typed field mappings"
git push origin main
```

### Task 7: Selectable Outputs and Verified Combined PDF Transaction

**Files:**
- Modify: `src/certificate_automation/output_options.py`
- Create: `src/certificate_automation/pdf_merge.py`
- Modify: `src/certificate_automation/batch.py`
- Modify: `src/certificate_automation/audit.py`
- Modify: `src/certificate_automation/verification.py`
- Test: `tests/test_pdf_merge.py`
- Modify: `tests/test_batch.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Consumes: dataset, mapping plan, validation report, existing template renderer, and `PdfConverter`.
- Produces: `OutputOptions(docx, individual_pdf, combined_pdf, destination, batch_name, order)`, `merge_verified_pdfs(inputs, destination) -> CombinedPdfRecord`, and expanded `BatchRequest(dataset, template, mappings, outputs, locale)`.

- [ ] **Step 1: Write failing merge and transaction tests**

```python
def test_merge_preserves_selected_order_and_total_pages(tmp_path):
    inputs = (pdf_with_text(tmp_path, "second", pages=2), pdf_with_text(tmp_path, "first", pages=1))
    record = merge_verified_pdfs(inputs, tmp_path / "batch.pdf")
    assert record.page_count == 3
    assert read_page_markers(record.path) == ("second", "second", "first")
    assert len(record.sha256) == 64

def test_page_count_mismatch_blocks_publication(tmp_path, monkeypatch):
    request = combined_pdf_request(tmp_path)
    monkeypatch.setattr("certificate_automation.batch.merge_verified_pdfs", corrupt_merge)
    with pytest.raises(BatchGenerationError) as caught:
        generator().generate(request)
    assert caught.value.code == "output.combined_pdf_verification_failed"
    assert not published_directories(tmp_path)

def test_combined_only_does_not_publish_temporary_individual_pdfs(tmp_path):
    result = generator().generate(combined_only_request(tmp_path))
    assert list(result.output_dir.glob("*.pdf")) == [result.output_dir / "Awards.pdf"]
    assert not list(result.output_dir.glob("*.docx"))

def test_cancel_between_merge_and_publish_removes_staging(tmp_path):
    result = generator(cancel_after_phase="combined_pdf").generate(request(tmp_path))
    assert result.state is BatchState.CANCELLED
    assert not staging_directories(tmp_path)
```

- [ ] **Step 2: Run merge and batch tests and verify failure**

Run: `python -m pytest tests/test_pdf_merge.py tests/test_batch.py tests/test_audit.py -q`

Expected: FAIL because selectable outputs and PDF merging do not exist.

- [ ] **Step 3: Implement output records and strict PDF merging**

```python
@dataclass(frozen=True, slots=True)
class OutputOptions:
    docx: bool
    individual_pdf: bool
    combined_pdf: bool
    destination: Path
    batch_name: str
    order: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (self.docx or self.individual_pdf or self.combined_pdf):
            raise ValueError("output.none_selected")

def merge_verified_pdfs(inputs: tuple[Path, ...], destination: Path) -> CombinedPdfRecord:
    expected_pages = sum(len(PdfReader(path).pages) for path in inputs)
    writer = PdfWriter()
    for path in inputs:
        writer.append(path)
    write_fsync_close(writer, destination)
    actual = PdfReader(destination, strict=True)
    if len(actual.pages) != expected_pages:
        raise CombinedPdfError("output.combined_pdf_page_count_mismatch")
    return CombinedPdfRecord(destination, expected_pages, sha256_file(destination))
```

- [ ] **Step 4: Extend the staging transaction without weakening existing verification**

Render DOCX once per row and verify it. Convert to individual staged PDFs only when either PDF option requires them and verify each PDF. Merge after all individual PDFs pass. Write audit files after merge verification. Remove unpublished per-recipient formats only inside staging. Reopen and rehash every selected artifact immediately before `os.replace(staging, final_directory)`.

Manifest schema 2 records source kind/hash, dataset revision/hash, template hash, typed mapping plan, selected outputs, locale, ordered row IDs, every published artifact hash/page count, and combined-PDF source order. It does not record recipient cell values.

- [ ] **Step 5: Run transaction fault injection and full regression tests**

Run: `python -m pytest tests/test_pdf_merge.py tests/test_batch.py tests/test_audit.py tests/test_verification.py -q`

Expected: PASS for DOCX-only, individual-PDF-only, combined-only, all outputs, every cancellation boundary, corrupt input, corrupt merge, page mismatch, disk/write failure, and no partial publication.

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit and push combined output generation**

```bash
git add src/certificate_automation/output_options.py src/certificate_automation/pdf_merge.py src/certificate_automation/batch.py src/certificate_automation/audit.py src/certificate_automation/verification.py tests/test_pdf_merge.py tests/test_batch.py tests/test_audit.py tests/test_verification.py
git commit -m "feat: publish selectable outputs and combined PDFs"
git push origin main
```

### Task 8: Professional Home Screen and Guided Workspace Shell

**Files:**
- Create: `src/certificate_automation/ui/theme.py`
- Create: `src/certificate_automation/ui/workspace.py`
- Modify: `src/certificate_automation/ui/main_window.py`
- Modify: `src/certificate_automation/app.py`
- Test: `tests/test_workspace.py`
- Modify: `tests/test_ui_workflow.py`

**Interfaces:**
- Consumes: `CatalogSet`, `ProjectStore`, `RecoveryService`, and existing background worker behavior.
- Produces: `WorkspaceWindow`, `HomePage`, `StepRail`, `WorkspaceState`, `WorkspaceWindow.open_project(path)`, `WorkspaceWindow.new_project()`, `WorkspaceWindow.set_locale(locale)`, and `WorkspaceWindow.navigate(step)`.

- [ ] **Step 1: Write failing home, navigation, localization, and accessibility tests**

```python
def test_home_has_four_clear_primary_actions(qtbot, workspace):
    assert workspace.home.new_batch_button.isVisible()
    assert workspace.home.continue_draft_button.isVisible()
    assert workspace.home.recover_button.isVisible()
    assert workspace.home.open_results_button.isVisible()

def test_language_switch_retranslates_without_losing_edits(qtbot, workspace):
    workspace.new_project()
    workspace.data_page.model.setData(workspace.data_page.model.index(0, 0), "Li Ming")
    workspace.set_locale("zh_CN")
    assert workspace.step_rail.text_for("data") == "收件人数据"
    assert workspace.data_page.model.dataset.rows[0].value("column-1") == "Li Ming"

def test_blocked_step_explains_required_action(qtbot, workspace):
    workspace.navigate("review")
    assert workspace.current_step == "data"
    assert workspace.banner.issue_code == "navigation.complete_data_first"

def test_every_interactive_control_has_accessible_name(workspace):
    missing = [w for w in interactive_descendants(workspace) if not w.accessibleName()]
    assert missing == []
```

- [ ] **Step 2: Run workspace tests and verify the old wizard fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_workspace.py tests/test_ui_workflow.py -q`

Expected: FAIL because the home/workspace shell does not exist and labels are hard-coded English.

- [ ] **Step 3: Implement the visual tokens and responsive shell**

```python
TOKENS = {
    "canvas": "#F5F7FA",
    "surface": "#FFFFFF",
    "text": "#172033",
    "muted": "#5D687A",
    "accent": "#2457D6",
    "success": "#197044",
    "warning": "#9A5A00",
    "error": "#B42318",
    "focus": "#7AA2FF",
}

def application_stylesheet(scale: float = 1.0) -> str:
    primary_height = round(44 * scale)
    radius = round(8 * scale)
    return f"""
        QWidget {{ color: {TOKENS['text']}; background: {TOKENS['canvas']}; }}
        QFrame[role='surface'] {{ background: {TOKENS['surface']}; border-radius: {radius}px; }}
        QPushButton[role='primary'] {{ min-height: {primary_height}px; background: {TOKENS['accent']}; color: white; }}
        QPushButton:focus, QComboBox:focus, QLineEdit:focus {{ border: 2px solid {TOKENS['focus']}; }}
        QLabel[state='error'] {{ color: {TOKENS['error']}; }}
    """
```

`WorkspaceWindow` uses a top bar with product/draft name, save state, and locale selector; a width-bounded step rail; a scrollable page surface; a persistent contextual banner; and a bottom navigation bar. At narrow widths the step rail collapses to numbered status buttons without hiding labels from accessibility APIs.

- [ ] **Step 4: Compose services and replace the old main window entry point**

```python
def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setOrganizationName("Certificate Automation")
    application.setApplicationName("Certificate Automation")
    settings = QSettings()
    services = create_default_services(locale=str(settings.value("locale", "en")))
    window = WorkspaceWindow(services, settings=settings)
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(250, application.quit)
    return application.exec()
```

Expand `ApplicationServices` with explicit callables for Excel inspection/import, delimited inspection/import, clipboard import, manual dataset creation, template inspection, validation, preview, batch generation, project-store opening, recovery, path opening, and confirmation dialogs. `create_default_services(locale)` binds only local functions and `WordPdfConverter`; the tests inject deterministic fakes for each field.

Keep `ui.main_window.MainWindow = WorkspaceWindow` for third-party and test imports during 2.0. Start on Home, not the first form page. Persist only locale and the recent-project path list in `QSettings`; never persist recipient values there.

- [ ] **Step 5: Run workspace, keyboard, and full regression tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_workspace.py tests/test_ui_workflow.py tests/test_shutdown.py -q`

Expected: PASS in `en`, `zh_CN`, and `ru`, with preserved edits after live switching, blocked-step guidance, focus traversal, and safe close behavior.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit and push the redesigned application shell**

```bash
git add src/certificate_automation/ui/theme.py src/certificate_automation/ui/workspace.py src/certificate_automation/ui/main_window.py src/certificate_automation/app.py tests/test_workspace.py tests/test_ui_workflow.py tests/test_shutdown.py
git commit -m "feat: add professional guided workspace"
git push origin main
```

### Task 9: Template, Mapping, Review, Output, and Results Pages

**Files:**
- Create: `src/certificate_automation/ui/template_page.py`
- Create: `src/certificate_automation/ui/match_page.py`
- Create: `src/certificate_automation/ui/review_page.py`
- Create: `src/certificate_automation/ui/output_page.py`
- Create: `src/certificate_automation/ui/results_page.py`
- Modify: `src/certificate_automation/template.py`
- Modify: `src/certificate_automation/word.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Modify: `src/certificate_automation/ui/worker.py`
- Modify: `src/certificate_automation/app.py`
- Test: `tests/test_operator_workflow.py`
- Modify: `tests/test_template.py`
- Modify: `tests/test_word.py`
- Modify: `tests/test_workers.py`

**Interfaces:**
- Consumes: all core interfaces from Tasks 1–8.
- Produces: a complete six-step operator workflow, coded `WordAvailability`, typed `TemplateInputError`, and `PreviewService.generate(dataset, row_id, template, plan) -> PreviewRecord`.

- [ ] **Step 1: Write failing end-to-end UI tests with injected offline services**

```python
@pytest.mark.parametrize("locale", ["en", "zh_CN", "ru"])
def test_operator_can_complete_manual_combined_pdf_workflow(qtbot, services, locale):
    window = WorkspaceWindow(services)
    window.set_locale(locale)
    window.new_project()
    enter_manual_rows(window.data_page, (("Li Ming", "Gold"), ("Chen Wei", "Silver")))
    choose_template(window.template_page, services.template)
    map_column(window.match_page, "FULL_NAME", "Name")
    map_column(window.match_page, "AWARD", "Award")
    select_recipient(window.review_page, "row-2")
    window.output_page.combined_pdf.setChecked(True)
    window.results_page.generate_button.click()
    qtbot.waitUntil(lambda: window.results_page.state == "published")
    assert services.batch_requests[-1].outputs.combined_pdf is True

def test_issue_action_focuses_exact_table_cell(qtbot, prepared_window):
    prepared_window.review_page.activate_issue("row-2", "award")
    assert prepared_window.current_step == "data"
    assert prepared_window.data_page.current_cell_ids() == ("row-2", "award")

def test_warning_acknowledgement_is_bound_to_revision(prepared_window):
    prepared_window.review_page.acknowledge_warnings()
    prepared_window.data_page.model.setData(prepared_window.data_page.model.index(0, 0), "Changed")
    assert prepared_window.project_state.warning_ack_revision is None

def test_result_actions_are_disabled_until_atomic_publication(prepared_window):
    prepared_window.start_generation()
    assert not prepared_window.results_page.open_output_button.isEnabled()

def test_protected_template_is_rejected(tmp_path):
    with pytest.raises(TemplateInputError) as caught:
        inspect_template(unsafe_template(tmp_path, protection=True))
    assert caught.value.code == "template.protected"
```

- [ ] **Step 2: Run workflow tests and verify page modules are absent**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_operator_workflow.py tests/test_template.py tests/test_word.py tests/test_workers.py -q`

Expected: FAIL because the five workspace pages and workflow coordinator are missing.

- [ ] **Step 3: Implement the template and typed-mapping pages**

```python
class TemplatePage(QWidget):
    template_selected = Signal(Path)
    def set_inspection(self, inspection: TemplateInspection) -> None:
        self.file_name.setText(inspection.path.name)
        self.hash_label.setText(inspection.sha256)
        self.placeholder_model.replace(inspection.placeholders)

    def show_template_error(self, code: str, parameters: Mapping[str, object]) -> None:
        self.error_banner.show_error(self._catalog.text(code, **parameters))

    def retranslate(self, catalog: TranslationCatalog) -> None:
        self._catalog = catalog
        self.title.setText(catalog.text("template.title"))
        self.choose_button.setText(catalog.text("template.choose"))

class MatchPage(QWidget):
    plan_changed = Signal(object)
    def set_context(self, dataset: TabularDataset, placeholders: tuple[str, ...]) -> None:
        self._dataset = dataset
        self.cards.replace(mapping_cards(dataset, placeholders))

    def mapping_plan(self) -> MappingPlan:
        return MappingPlan({card.placeholder: card.mapping_source() for card in self.cards if card.is_resolved()})

    def focus_placeholder(self, name: str) -> None:
        card = self.cards.card(name)
        card.setFocus()
        self.scroll.ensureWidgetVisible(card)
```

Extend `TemplateInspection` with `sha256`, placeholder occurrence counts, location categories, protection state, and preview page count when Word preview is available. Reject `.docm`, embedded VBA projects, editing protection, malformed OOXML, and ambiguous placeholder tokens with distinct codes. Template cards display filename, SHA-256, detected placeholders, occurrence counts, and location categories. Each mapping card exposes only the six typed source choices, displays three representative resolved values when available, marks Exact/Suggested/Manual/Fixed/Unresolved in text and icon, and blocks Continue while unresolved.

- [ ] **Step 4: Implement multi-recipient review and output choices**

```python
class PreviewService:
    def generate(self, dataset, row_id, template, plan) -> PreviewRecord:
        row = dataset.row(row_id)
        replacements = evaluate_plan(plan, dataset, row_id)
        cache_key = preview_cache_key(dataset.revision, template.sha256, plan, row.row_id)
        docx_path, pdf_path = self._paths(cache_key)
        render_template(template.path, docx_path, replacements)
        verify_docx(docx_path, set(template.names))
        self._converter.convert(docx_path, pdf_path)
        verify_pdf(pdf_path)
        return PreviewRecord(row.row_id, dataset.revision, template.sha256, pdf_path)

class OutputPage(QWidget):
    options_changed = Signal(object)
    def options(self, generation_order: tuple[str, ...]) -> OutputOptions:
        return OutputOptions(
            docx=self.docx.isChecked(),
            individual_pdf=self.individual_pdf.isChecked(),
            combined_pdf=self.combined_pdf.isChecked(),
            destination=Path(self.destination.text()),
            batch_name=self.batch_name.text().strip(),
            order=generation_order,
        )

    def set_word_availability(self, availability: WordAvailability) -> None:
        for control in (self.individual_pdf, self.combined_pdf):
            control.setEnabled(availability.available)
            control.setToolTip("" if availability.available else self._catalog.text(availability.code))
```

Render the PDF inside the app with `PySide6.QtPdf.QPdfDocument` and `PySide6.QtPdfWidgets.QPdfView`; do not open an external viewer during review. The preview cache lives under the OS temporary directory, contains only the current project revision, and is deleted on replacement and normal shutdown.

Review shows the chosen row's source values, resolved values, planned filename, PDF preview, and complete batch issue list. PDF controls explain and disable themselves when Word is unavailable while leaving DOCX available. Combined PDF defaults off and displays the selected row order.

- [ ] **Step 5: Implement generation/results coordination and revision guards**

```python
def start_generation(self) -> None:
    current = self.project_state
    report = self.services.validate(current)
    if report.dataset_revision != current.dataset.revision:
        self.show_issue("validation.revision_changed")
        return
    if report.template_sha256 != current.template.sha256:
        self.invalidate_template_and_return()
        return
    self._run_generation_worker(current.to_batch_request())
```

Display named phases and `current / total`; cancellation only requests the existing boundary-safe token. On failure show withheld status, code-localized recovery action, and a button to open the diagnostic folder. On publication enable Open Output Folder, Open Combined PDF when present, Open Summary, and Open Manifest.

- [ ] **Step 6: Run three-locale workflows, revision races, and full tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_operator_workflow.py tests/test_template.py tests/test_word.py tests/test_workers.py tests/test_ui_workflow.py -q`

Expected: PASS for manual, Excel, CSV, TSV, and clipboard flows; every locale; recipient switching; issue navigation; warning acknowledgement invalidation; Word unavailable; cancellation; safe failure; and result actions.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: PASS.

- [ ] **Step 7: Commit and push the complete operator workflow**

```bash
git add src/certificate_automation/template.py src/certificate_automation/word.py src/certificate_automation/ui/template_page.py src/certificate_automation/ui/match_page.py src/certificate_automation/ui/review_page.py src/certificate_automation/ui/output_page.py src/certificate_automation/ui/results_page.py src/certificate_automation/ui/workspace.py src/certificate_automation/ui/worker.py src/certificate_automation/app.py tests/test_template.py tests/test_word.py tests/test_operator_workflow.py tests/test_workers.py tests/test_ui_workflow.py
git commit -m "feat: complete reviewed certificate workflow"
git push origin main
```

### Task 10: Release Hardening, Documentation, Packaging, and Live Acceptance

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/certificate_automation/__init__.py`
- Modify: `packaging/certificate-automation.spec`
- Modify: `packaging/installer.iss`
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Create: `examples/sample_recipients.csv`
- Modify: `tests/test_i18n.py`
- Modify: `tests/test_operator_workflow.py`
- Modify: `tests/windows/test_packaged_application.py`
- Modify: `tests/windows/test_word_integration.py`

**Interfaces:**
- Consumes: the complete 2.0 application.
- Produces: version 2.0.0 source, packaged EXE, installer, acceptance evidence, and offline operator documentation.

- [ ] **Step 1: Add failing packaging, translation-usage, and scaling acceptance tests**

```python
def test_every_translation_key_is_used_or_explicitly_report_only():
    used = scan_python_translation_calls(SOURCE_ROOT)
    catalog = load_json(LOCALES / "en.json")
    assert set(catalog) - used == REPORT_ONLY_KEYS

@pytest.mark.parametrize("locale", ["en", "zh_CN", "ru"])
def test_principal_pages_keep_primary_action_reachable_at_200_percent(qtbot, locale):
    window = sized_workspace(locale=locale, logical_scale=2.0, size=(1280, 800))
    for step in WORKFLOW_STEPS:
        window.navigate_for_test(step)
        assert window.page(step).primary_action.isVisibleTo(window)
        assert window.page(step).minimumSizeHint().width() <= window.viewport().width()

def test_packaged_application_contains_all_locale_catalogs(packaged_root):
    for locale in ("en", "zh_CN", "ru"):
        assert packaged_catalog(packaged_root, locale).is_file()
```

- [ ] **Step 2: Run the release-focused tests and verify version/package gaps**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_i18n.py tests/test_operator_workflow.py tests/windows/test_packaged_application.py -q`

Expected: FAIL until version metadata, package data, and scaling behavior are finalized.

- [ ] **Step 3: Finalize version metadata, package data, guide, and examples**

Set `pyproject.toml`, `certificate_automation.__version__`, and Inno Setup `AppVersion` to `2.0.0`. Add `locales/*.json` as package data and PyInstaller data. Document the fully offline guarantee, source compatibility matrix, hidden Excel data choice, ambiguous text import preview, manual table editing, sensitive draft handling, typed mappings, warnings, combined PDF, recovery, and redacted diagnostics. Include matching menu/control names in all three supported languages.

- [ ] **Step 4: Run the complete automated suite with coverage**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --cov=certificate_automation --cov-report=term-missing --cov-fail-under=90 -q`

Expected: PASS with at least 90% statement coverage and no skipped non-Windows tests.

- [ ] **Step 5: Build and smoke-test the Windows distribution**

Run from Windows PowerShell in the repository:

```powershell
py -3.14 -m pytest tests\windows\test_word_integration.py -m word_integration -q
py -3.14 -m PyInstaller --noconfirm --clean packaging\certificate-automation.spec
& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
py -3.14 -m pytest tests\windows\test_packaged_application.py -q
```

Expected: real Word integration PASS; EXE starts and exits through `--smoke-test`; catalogs and examples exist; installer installs, launches, and uninstalls without admin rights.

- [ ] **Step 6: Perform visual and keyboard acceptance on the packaged app**

Use the packaged application, not the Python source launcher. Capture and inspect Home plus all six principal steps in `en`, `zh_CN`, and `ru` at 100% and 200% Windows scaling. Confirm no clipped labels, overlapped controls, inaccessible primary actions, untranslated keys, or color-only states. Complete one workflow with keyboard only, including table entry, mapping, preview selection, warning acknowledgement, output selection, generation, and opening results.

- [ ] **Step 7: Run live source and 50-recipient official-output acceptance**

Run one batch each from `.xlsx`, UTF-8 CSV, Windows-1251 CSV, UTF-16 TSV, clipboard paste, and manual entry. Run a 50-recipient mixed Latin/Cyrillic/CJK batch with DOCX, individual PDF, and combined PDF selected. Verify:

```text
published DOCX count = 50
published individual PDF count = 50
combined PDF page count = sum(individual PDF page counts)
manifest artifact hashes = freshly computed hashes
unreplaced placeholder count = 0
staging directory count after success = 0
recipient values in support.log = 0
```

- [ ] **Step 8: Commit, push, tag, and publish the verified installer artifact**

```bash
git add pyproject.toml src/certificate_automation/__init__.py src/certificate_automation/locales packaging README.md docs/user-guide.md examples tests
git commit -m "build: verify Certificate Automation 2.0 release"
git tag -a v2.0.0 -m "Certificate Automation 2.0.0"
git push origin main
git push origin v2.0.0
```

Copy the final installer to `C:\Users\Faridun\Documents\Codex\2026-09-20\w\outputs\CertificateAutomation-Setup-2.0.0.exe` and report the SHA-256 hash with the test, visual, Word, package, and 50-recipient acceptance results.
