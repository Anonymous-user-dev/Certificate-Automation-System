# Certificate Automation Desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an offline Windows PySide6 application that safely turns a mapped Excel workbook and Word template into a verified, auditable batch of DOCX and PDF certificates.

**Architecture:** Build a UI-independent Python package for workbook parsing, OOXML template handling, mapping, validation, batch transactions, Word conversion, verification, and auditing. Put the PySide6 guided workflow on top of those services, then package and verify the same entry point on Windows.

**Tech Stack:** Python 3.12+, PySide6, openpyxl, lxml, pywin32, pypdf, pytest, pytest-qt, pytest-cov, PyInstaller, Inno Setup

**Spec:** `docs/superpowers/specs/2026-09-20-certificate-automation-desktop-design.md`

## Global Constraints

- The application and all certificate processing must work without internet access.
- Target supported 64-bit Windows systems with an installed desktop Microsoft Word.
- Never modify the selected workbook or template.
- Never silently overwrite a previous output batch.
- Publish a batch only after every required DOCX and PDF passes verification.
- Keep PySide6 and Word COM imports out of the core domain modules.
- Preserve existing user work and stage only files belonging to the current task.
- Run relevant tests before every commit and push after every one or two verified features.

## Review Focus

- A workbook with two names that normalize to the same filename must be blocked before generation; covered in Task 4.
- A placeholder split across multiple Word runs or inside a text box must still be discovered and replaced without deleting surrounding text; covered in Task 3.
- Word failing after some PDFs exist must not publish a partial batch and must record retry attempts; covered in Tasks 6 and 7.
- Unicode recipient names and Windows-reserved device names must produce safe, distinct filenames; covered in Task 4.
- Closing or cancelling during generation must stop only at a safe boundary and leave no successful-looking partial output; covered in Task 9.

---

## Planned File Structure

```text
pyproject.toml                         build metadata, dependencies, entry points, pytest settings
src/certificate_automation/
  __init__.py                          package version
  app.py                               application composition and GUI entry point
  domain.py                            immutable records, issue severities, batch states
  workbook.py                          XLSX loading and normalized cell values
  template.py                          OOXML placeholder discovery and replacement
  mapping.py                           normalized automatic mapping
  validation.py                        preflight rules and filename plan
  filenames.py                         Windows-safe deterministic names
  audit.py                             hashes, manifest, summary report, support logging
  verification.py                      DOCX/PDF readability and count checks
  word.py                              Word COM adapter and bounded recovery
  batch.py                             staged transactional batch orchestration
  ui/
    main_window.py                     guided page container and navigation state
    files_page.py                      workbook/template/destination controls
    mapping_page.py                    editable placeholder mappings
    validation_page.py                 grouped issues and readiness state
    preview_page.py                    sample selection and preview action
    generation_page.py                 progress, safe cancellation, results
    worker.py                          background Qt worker bridge
tests/
  fixtures.py                          temporary XLSX/DOCX builders and fake converter
  test_workbook.py
  test_template.py
  test_mapping.py
  test_validation.py
  test_audit.py
  test_verification.py
  test_word.py
  test_batch.py
  test_ui_workflow.py
packaging/certificate-automation.spec  PyInstaller build
packaging/installer.iss                Inno Setup installer
README.md                              developer setup and architecture
docs/user-guide.md                     offline staff guide and recovery instructions
```

### Task 1: Package Foundation and Domain Contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/certificate_automation/__init__.py`
- Create: `src/certificate_automation/domain.py`
- Create: `tests/test_domain.py`
- Modify: `.gitignore`
- Modify: `system/requirements.txt`

**Interfaces:**
- Consumes: no product interfaces.
- Produces: `Severity`, `Issue`, `Recipient`, `MappingSelection`, `BatchState`, and `BatchResult` dataclasses used by all later tasks.

- [ ] **Step 1: Write failing domain tests**

```python
def test_issue_exposes_blocking_state():
    assert Issue(Severity.ERROR, "workbook", "Missing name").blocking is True
    assert Issue(Severity.WARNING, "workbook", "Long value").blocking is False

def test_recipient_retains_source_row_and_values():
    recipient = Recipient(source_row=7, values={"full_name": "Ana García"})
    assert recipient.source_row == 7
    assert recipient.values["full_name"] == "Ana García"
```

- [ ] **Step 2: Run the tests and confirm the package does not exist**

Run: `.venv/bin/python -m pytest tests/test_domain.py -v`
Expected: collection fails with `ModuleNotFoundError: certificate_automation`.

- [ ] **Step 3: Add build metadata and immutable domain types**

Define `Issue.blocking` as `severity is Severity.ERROR`; use frozen dataclasses and enums so worker and UI code cannot silently mutate validated data. Configure the `certificate-automation` entry point as `certificate_automation.app:main`, pytest `pythonpath = ["src"]`, and dependencies for openpyxl, lxml, PySide6, pywin32 on Windows, and pypdf.

- [ ] **Step 4: Ignore generated and local state**

Add `.pytest_cache/`, `.coverage`, `htmlcov/`, `build/`, `dist/`, `*.spec.local`, `.venv-win/`, `system/output/`, `*.log`, and staging directory patterns. Keep source fixtures trackable.

- [ ] **Step 5: Run the domain tests**

Run: `.venv/bin/python -m pip install -e '.[test]' && .venv/bin/python -m pytest tests/test_domain.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add pyproject.toml src/certificate_automation tests/test_domain.py .gitignore system/requirements.txt
git commit -m "build: establish tested application package"
git push origin main
```

### Task 2: Workbook Import and Value Normalization

**Files:**
- Create: `src/certificate_automation/workbook.py`
- Create: `tests/fixtures.py`
- Create: `tests/test_workbook.py`

**Interfaces:**
- Consumes: `Recipient` and `Issue` from `domain.py`.
- Produces: `normalize_field_name(value: str) -> str`, `WorkbookData`, `list_worksheets(path: Path) -> tuple[str, ...]`, and `load_workbook_data(path: Path, sheet_name: str) -> WorkbookData`.

- [ ] **Step 1: Test headers, blank rows, dates, formulas, duplicate normalized headers, and corruption**

```python
def test_loads_rows_and_normalizes_headers(xlsx_factory):
    path = xlsx_factory([["Full Name", "Award-Type"], [" Ana ", "Gold"], [None, None]])
    data = load_workbook_data(path, "Students")
    assert data.headers == ("full_name", "award_type")
    assert data.recipients[0].values == {"full_name": "Ana", "award_type": "Gold"}
    assert data.recipients[0].source_row == 2

def test_duplicate_normalized_headers_are_reported(xlsx_factory):
    path = xlsx_factory([["Full Name", "full_name"], ["Ana", "Other"]])
    with pytest.raises(WorkbookInputError, match="same field name"):
        load_workbook_data(path, "Students")
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_workbook.py -v`
Expected: fail because `certificate_automation.workbook` is absent.

- [ ] **Step 3: Implement read-only workbook loading**

Load with `read_only=True, data_only=True`. Normalize headers with Unicode case folding and `[^0-9a-z]+` separators while retaining a display header map. Strip string cells, convert Excel date/datetime/time values to stable ISO strings, skip fully blank rows, reject missing sheets and duplicate normalized headers, and wrap ZIP/XML/openpyxl failures in `WorkbookInputError` with plain-language messages.

- [ ] **Step 4: Run workbook and domain tests**

Run: `.venv/bin/python -m pytest tests/test_domain.py tests/test_workbook.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/certificate_automation/workbook.py tests/fixtures.py tests/test_workbook.py
git commit -m "feat: add safe workbook import"
```

### Task 3: OOXML Placeholder Discovery and Replacement

**Files:**
- Create: `src/certificate_automation/template.py`
- Create: `tests/test_template.py`

**Interfaces:**
- Consumes: normalized field names from `workbook.py`.
- Produces: `Placeholder`, `TemplateInspection`, `inspect_template(path: Path) -> TemplateInspection`, and `render_template(source: Path, destination: Path, replacements: Mapping[str, str]) -> None`.

- [ ] **Step 1: Test ordinary, split-run, table, header/footer, text-box, repeated, malformed, and surrounding-text cases**

```python
def test_replaces_placeholder_split_across_runs(docx_factory, tmp_path):
    source = docx_factory(paragraph_runs=[["Issued to ", "{{FULL_", "NAME}}", "."]])
    output = tmp_path / "out.docx"
    render_template(source, output, {"FULL_NAME": "Ana García"})
    assert document_text(output) == "Issued to Ana García."

def test_discovers_placeholders_in_text_boxes(ooxml_docx_factory):
    source = ooxml_docx_factory(text_box="{{CERTIFICATE_ID}}")
    assert inspect_template(source).names == ("CERTIFICATE_ID",)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_template.py -v`
Expected: fail because `certificate_automation.template` is absent.

- [ ] **Step 3: Implement OOXML traversal without rewriting document formatting**

Open the DOCX as a ZIP, parse relevant `word/*.xml` parts with hardened lxml settings, and inspect each WordprocessingML paragraph's ordered `w:t` nodes. Find `{{NAME}}` spans in concatenated paragraph text; replace the span in the first involved text node while retaining prefix/suffix text and clear only the consumed characters in subsequent nodes. Copy untouched ZIP members byte-for-byte and write changed XML to a new archive. Reject invalid ZIPs, malformed XML, blank placeholders, and replacement keys absent from the template.

- [ ] **Step 4: Reopen the rendered DOCX and verify no requested placeholders remain**

Use `inspect_template(destination)` after rendering; raise `TemplateRenderError` if any mapped placeholder remains. Tests must reopen with `python-docx` and with `zipfile.ZipFile.testzip()`.

- [ ] **Step 5: Run template, workbook, and domain tests**

Run: `.venv/bin/python -m pytest tests/test_template.py tests/test_workbook.py tests/test_domain.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit and push Tasks 2-3**

```bash
git add src/certificate_automation/template.py tests/test_template.py
git commit -m "feat: add formatting-safe template engine"
git push origin main
```

### Task 4: Flexible Mapping, Validation, and Filename Planning

**Files:**
- Create: `src/certificate_automation/mapping.py`
- Create: `src/certificate_automation/filenames.py`
- Create: `src/certificate_automation/validation.py`
- Create: `tests/test_mapping.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Consumes: `WorkbookData`, `TemplateInspection`, `Recipient`, and `Issue`.
- Produces: `suggest_mappings(headers, placeholders) -> MappingSelection`, `safe_stem(value: str) -> str`, `ValidationReport`, and `validate_preflight(workbook, template, mappings, destination) -> ValidationReport`.

- [ ] **Step 1: Test exact normalized mappings and unresolved ambiguity**

```python
def test_suggests_separator_insensitive_mapping():
    selection = suggest_mappings(("full_name", "award_type"), ("FULL-NAME", "AWARD TYPE"))
    assert selection.columns == {"FULL-NAME": "full_name", "AWARD TYPE": "award_type"}

def test_unmatched_placeholder_is_not_guessed():
    selection = suggest_mappings(("student",), ("FULL_NAME",))
    assert selection.columns["FULL_NAME"] is None
```

- [ ] **Step 2: Test preflight collision and Windows filename rules**

```python
@pytest.mark.parametrize("name", ["CON", "con.txt", "AUX", "NUL", "COM1"])
def test_reserved_windows_names_are_rewritten(name):
    assert safe_stem(name).casefold().split(".")[0] not in RESERVED_NAMES

def test_duplicate_output_names_block_batch(valid_inputs):
    workbook = dataclasses.replace(
        valid_inputs.workbook,
        recipients=recipients("Ana", " ana "),
    )
    report = validate_preflight(**{**valid_inputs.as_kwargs(), "workbook": workbook})
    assert any(i.code == "duplicate_output_filename" and i.blocking for i in report.issues)
```

- [ ] **Step 3: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_mapping.py tests/test_validation.py -v`
Expected: imports fail for the new modules.

- [ ] **Step 4: Implement mapping and deterministic filename planning**

Normalize mapping candidates using the same function as workbook headers. Sanitize control characters and Windows-invalid characters, trim trailing spaces/dots, guard reserved device names, cap stems while retaining a stable short hash, and use `FULL_NAME` when mapped or `certificate-row-<row>` otherwise. Detect collisions case-insensitively before generation rather than auto-renaming official documents.

- [ ] **Step 5: Implement preflight aggregation**

Return all issues in one `ValidationReport` rather than stopping at the first. Validate nonempty recipients, complete mappings, nonblank mapped values, duplicates, excessive values, template/source/output separation, output write probe, estimated disk requirement, and filename collisions. Use stable issue codes and include source rows in issue context.

- [ ] **Step 6: Run the complete core test set**

Run: `.venv/bin/python -m pytest tests/test_domain.py tests/test_workbook.py tests/test_template.py tests/test_mapping.py tests/test_validation.py -v`
Expected: all tests pass.

- [ ] **Step 7: Commit and push**

```bash
git add src/certificate_automation/mapping.py src/certificate_automation/filenames.py src/certificate_automation/validation.py tests/test_mapping.py tests/test_validation.py
git commit -m "feat: add flexible mapping and batch preflight"
git push origin main
```

### Task 5: Audit Records and Artifact Verification

**Files:**
- Create: `src/certificate_automation/audit.py`
- Create: `src/certificate_automation/verification.py`
- Create: `tests/test_audit.py`
- Create: `tests/test_verification.py`

**Interfaces:**
- Consumes: validated batch plan, output paths, and issues.
- Produces: `sha256_file(path) -> str`, `write_manifest(context, destination) -> Path`, `write_summary(context, destination) -> Path`, `verify_docx(path, forbidden_placeholders)`, and `verify_pdf(path)`.

- [ ] **Step 1: Test deterministic hashes and privacy-conscious manifest structure**

```python
def test_manifest_contains_sources_mappings_outputs_and_status(audit_context, tmp_path):
    path = write_manifest(audit_context, tmp_path / "manifest.json")
    payload = json.loads(path.read_text("utf-8"))
    assert payload["status"] == "verified"
    assert payload["sources"]["workbook"]["sha256"]
    assert payload["mappings"]["FULL_NAME"] == "full_name"
    assert payload["outputs"][0]["pdf_sha256"]
```

- [ ] **Step 2: Test corrupt and empty DOCX/PDF verification**

```python
def test_zero_page_pdf_is_rejected(empty_pdf):
    with pytest.raises(ArtifactVerificationError, match="page"):
        verify_pdf(empty_pdf)

def test_remaining_placeholder_is_rejected(rendered_docx):
    with pytest.raises(ArtifactVerificationError, match="placeholder"):
        verify_docx(rendered_docx, {"FULL_NAME"})
```

- [ ] **Step 3: Implement checksums, JSON manifest, escaped offline HTML summary, and verification**

Use atomic file writes (`temporary sibling -> os.replace`) for reports. The summary contains batch status, source basenames, counts, mappings, warnings, and output table, but no raw exception traceback. Verify DOCX ZIP integrity and placeholder absence; verify the PDF header, parseability, nonzero pages, and nonempty page boxes with pypdf.

- [ ] **Step 4: Run audit and verification tests with the complete core suite**

Run: `.venv/bin/python -m pytest tests/test_audit.py tests/test_verification.py tests/test_*.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/certificate_automation/audit.py src/certificate_automation/verification.py tests/test_audit.py tests/test_verification.py
git commit -m "feat: add artifact verification and audit reports"
```

### Task 6: Microsoft Word Conversion Adapter

**Files:**
- Create: `src/certificate_automation/word.py`
- Create: `tests/test_word.py`
- Create: `tests/windows/test_word_integration.py`

**Interfaces:**
- Consumes: staged DOCX and destination PDF paths.
- Produces: `PdfConverter` protocol, `WordPdfConverter.is_available() -> Availability`, and `WordPdfConverter.convert(docx, pdf, on_attempt=None) -> None`.

- [ ] **Step 1: Test bounded retries, cleanup, ownership, and error classification with a fake COM gateway**

```python
def test_transient_failure_restarts_owned_word_and_retries(tmp_path):
    gateway = FakeWordGateway(outcomes=[TransientWordError("busy"), SUCCESS])
    converter = WordPdfConverter(gateway=gateway, max_attempts=2)
    converter.convert(tmp_path / "a.docx", tmp_path / "a.pdf")
    assert gateway.started_instances == 2
    assert gateway.quit_calls == 2

def test_permanent_failure_is_not_retried(tmp_path):
    gateway = FakeWordGateway(outcomes=[PermanentWordError("invalid document")])
    with pytest.raises(PdfConversionError):
        WordPdfConverter(gateway=gateway).convert(tmp_path / "a.docx", tmp_path / "a.pdf")
    assert gateway.started_instances == 1
```

- [ ] **Step 2: Implement a lazy Windows COM gateway**

Import `pythoncom` and `win32com.client` only inside Windows adapter methods. Initialize COM in the calling worker thread, start a private Word instance with `DispatchEx`, set `Visible=False` and `DisplayAlerts=0`, open the staged document read-only, call `ExportAsFixedFormat` for PDF, close only the opened document, quit only the private instance, and uninitialize COM in `finally`.

- [ ] **Step 3: Implement bounded recovery**

Classify Word-busy/RPC-rejected errors as transient, retry at most two times with a short bounded backoff, discard an invalid partial PDF between attempts, and surface `PdfConversionError` with a stable code and user action. Never enumerate or terminate global WINWORD processes.

- [ ] **Step 4: Run fake adapter tests on WSL and real integration test on Windows**

Run WSL: `.venv/bin/python -m pytest tests/test_word.py -v`
Run Windows: `python -m pytest tests/windows/test_word_integration.py -m word_integration -v`
Expected: fake tests all pass; installed Word produces a readable one-page PDF.

- [ ] **Step 5: Commit and push Tasks 5-6**

```bash
git add src/certificate_automation/word.py tests/test_word.py tests/windows/test_word_integration.py
git commit -m "feat: add recoverable Word PDF conversion"
git push origin main
```

### Task 7: Transactional Batch Orchestrator

**Files:**
- Create: `src/certificate_automation/batch.py`
- Create: `tests/test_batch.py`

**Interfaces:**
- Consumes: validated inputs, template renderer, `PdfConverter`, verifiers, and audit writers.
- Produces: `CancellationToken`, `ProgressEvent`, `BatchRequest`, and `BatchGenerator.generate(request, progress, cancellation) -> BatchResult`.

- [ ] **Step 1: Test a complete two-recipient transaction**

```python
def test_success_publishes_complete_timestamped_batch(batch_request, fake_converter):
    result = BatchGenerator(converter=fake_converter).generate(batch_request)
    assert result.state is BatchState.PUBLISHED
    assert len(list(result.output_dir.glob("*.docx"))) == 2
    assert len(list(result.output_dir.glob("*.pdf"))) == 2
    assert (result.output_dir / "manifest.json").exists()
    assert not any(batch_request.destination.glob(".certificate-staging-*"))
```

- [ ] **Step 2: Test rollback after partial conversion and safe cancellation**

```python
def test_conversion_failure_never_publishes_partial_batch(batch_request, failing_converter):
    with pytest.raises(BatchGenerationError) as error:
        BatchGenerator(converter=failing_converter).generate(batch_request)
    assert not list(batch_request.destination.glob("Certificate Batch *"))
    assert error.value.diagnostic_path.exists()

def test_cancellation_occurs_between_recipients(batch_request, cancelling_progress):
    result = BatchGenerator(converter=FakeConverter()).generate(batch_request, progress=cancelling_progress)
    assert result.state is BatchState.CANCELLED
    assert result.output_dir is None
```

- [ ] **Step 3: Implement staged generation and progress events**

Create the staging directory as a unique child of the selected destination, build every DOCX, verify it, convert and verify every PDF, write reports, then publish via a single same-volume `os.replace`. Emit immutable progress events at preflight, DOCX, PDF, verification, and publication boundaries. Check cancellation only before beginning a recipient or publication, never halfway through a file write.

- [ ] **Step 4: Implement failure diagnostics and cleanup**

Catch expected domain failures, write a redacted diagnostic JSON/text record, remove misleading partial report files, and rename retained staging to `.certificate-incomplete-<batch-id>` only when diagnostics require artifacts. Otherwise remove it. Return or raise a typed result that the UI can render without parsing traceback text.

- [ ] **Step 5: Run all non-Windows tests**

Run: `.venv/bin/python -m pytest -m 'not word_integration' --cov=certificate_automation --cov-report=term-missing`
Expected: all tests pass and core service coverage is at least 90%.

- [ ] **Step 6: Commit and push**

```bash
git add src/certificate_automation/batch.py tests/test_batch.py
git commit -m "feat: generate certificates transactionally"
git push origin main
```

### Task 8: PySide6 Guided Desktop Workflow

**Files:**
- Create: `src/certificate_automation/app.py`
- Create: `src/certificate_automation/ui/__init__.py`
- Create: `src/certificate_automation/ui/main_window.py`
- Create: `src/certificate_automation/ui/files_page.py`
- Create: `src/certificate_automation/ui/mapping_page.py`
- Create: `src/certificate_automation/ui/validation_page.py`
- Create: `src/certificate_automation/ui/preview_page.py`
- Create: `src/certificate_automation/ui/generation_page.py`
- Create: `src/certificate_automation/ui/worker.py`
- Create: `tests/test_ui_workflow.py`

**Interfaces:**
- Consumes: all core services through an `ApplicationServices` frozen dataclass defined in `app.py`, containing workbook loader, template inspector/renderer, validator, preview generator, batch generator, and recovery service callables.
- Produces: `ApplicationServices`, `MainWindow`, background `GenerationWorker`, and `main() -> int` entry point.

- [ ] **Step 1: Test the happy-path navigation and blocking validation**

```python
def test_user_can_select_map_validate_preview_and_generate(qtbot, fake_services):
    window = MainWindow(fake_services)
    qtbot.addWidget(window)
    select_valid_files(window)
    qtbot.mouseClick(window.files_page.continue_button, Qt.LeftButton)
    assert window.current_page is window.mapping_page
    accept_mappings(window)
    assert window.validation_page.generate_allowed is True

def test_errors_disable_preview_and_generation(qtbot, services_with_error):
    window = MainWindow(services_with_error)
    qtbot.addWidget(window)
    assert not window.validation_page.preview_button.isEnabled()
    assert not window.validation_page.generate_button.isEnabled()
```

- [ ] **Step 2: Implement accessible pages and state-driven navigation**

Use a `QStackedWidget`, visible step names, standard file dialogs, persistent recent non-sensitive directories through `QSettings`, editable mapping combo boxes, grouped error/warning cards, explicit confirmation, progress by recipient, and a results page. Use clear labels, keyboard focus order, accessible names, and no color-only status signals.

- [ ] **Step 3: Implement background work and safe UI states**

Move preflight, preview, and generation work into `QObject` workers on `QThread`. Communicate only through typed Qt signals. Disable inputs during work, expose cancellation through `CancellationToken`, prevent duplicate starts, and always re-enable or transition controls from a single completion handler.

- [ ] **Step 4: Add preview using a one-recipient non-published request**

Generate preview artifacts under the system temporary directory, verify them, and open the PDF through `QDesktopServices.openUrl`. Mark preview filenames and content as preview-only in the audit context; delete old previews on next run and application startup.

- [ ] **Step 5: Run UI tests offscreen and the full non-Windows suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -v`
Expected: all tests pass without a display server.

- [ ] **Step 6: Commit and push**

```bash
git add src/certificate_automation/app.py src/certificate_automation/ui tests/test_ui_workflow.py
git commit -m "feat: add guided PySide6 desktop workflow"
git push origin main
```

### Task 9: Shutdown Recovery, Packaging, Documentation, and Release Verification

**Files:**
- Create: `packaging/certificate-automation.spec`
- Create: `packaging/installer.iss`
- Create: `README.md`
- Create: `docs/user-guide.md`
- Create: `tests/test_shutdown.py`
- Create: `tests/windows/test_packaged_application.py`
- Modify: `src/certificate_automation/ui/main_window.py`
- Modify: `src/certificate_automation/app.py`

**Interfaces:**
- Consumes: application entry point and batch cancellation contract.
- Produces: packaged Windows executable/installer and offline operating guide.

- [ ] **Step 1: Test close-during-generation behavior and stale staging discovery**

```python
def test_close_during_generation_requests_safe_cancel(qtbot, running_window):
    running_window.close()
    assert running_window.cancellation.requested is True
    assert running_window.isVisible() is True

def test_startup_lists_incomplete_staging_records(tmp_path, app_services):
    (tmp_path / ".certificate-incomplete-example").mkdir()
    assert app_services.recovery.find_incomplete(tmp_path)[0].batch_id == "example"
```

- [ ] **Step 2: Implement close coordination and startup recovery notice**

Intercept `closeEvent` while a worker is active, request cancellation, keep the window open until the worker reaches a safe boundary, then allow close. On startup or destination selection, list incomplete diagnostic directories with buttons to view the diagnostic report or remove that exact staging directory after confirmation.

- [ ] **Step 3: Add reproducible Windows packaging**

Configure PyInstaller to collect PySide6 plugins, application metadata, icons, and the offline guide while excluding test modules and development fixtures. Build from a clean Windows virtual environment, then use Inno Setup to install per user, add Start Menu shortcuts, and include an uninstaller. Do not bundle Word or claim Word-less PDF support.

- [ ] **Step 4: Write operator and developer documentation**

Document installation, the six-step workflow, supported placeholder syntax, Excel preparation, preview, batch folder contents, warnings versus errors, recovery steps, privacy, offline operation, and support-log location. Document developer commands for WSL unit/UI tests, Windows Word integration tests, packaging, and release verification.

- [ ] **Step 5: Run release checks on both environments**

Run WSL: `.venv/bin/python -m pytest -m 'not word_integration' --cov=certificate_automation --cov-fail-under=90`

Run Windows: `python -m pytest tests/windows -m word_integration -v`

Run packaged smoke test: `python -m pytest tests/windows/test_packaged_application.py -v --exe dist/CertificateAutomation/CertificateAutomation.exe`

Manual acceptance: process the representative 50-recipient workbook offline, confirm 50 DOCX + 50 PDF files, verify manifest hashes and counts, inspect samples with long/Unicode names, then repeat with a deliberately locked output and interrupted Word conversion to confirm no partial batch is published.

- [ ] **Step 6: Commit and push final product artifacts**

```bash
git add packaging README.md docs/user-guide.md src/certificate_automation tests/test_shutdown.py tests/windows/test_packaged_application.py
git commit -m "release: package offline certificate desktop app"
git push origin main
```

- [ ] **Step 7: Tag only after every release check passes**

```bash
git tag -a v1.0.0 -m "Certificate Automation Desktop v1.0.0"
git push origin v1.0.0
```

Do not create or push the tag if any automated or manual acceptance check fails.
