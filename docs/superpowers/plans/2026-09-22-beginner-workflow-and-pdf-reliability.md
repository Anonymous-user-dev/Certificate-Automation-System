# Beginner Workflow and PDF Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make custom fields, date mapping, previews, and PDF output understandable and dependable for a first-time offline Windows operator.

**Architecture:** Keep the existing dataset, template-inspection, typed-mapping, and transactional batch services. Repair missing UI connections and make output artifacts explicit in `BatchResult`; isolate preview files per application session so a displayed Windows PDF is never deleted during regeneration.

**Tech Stack:** Python 3.12+, PySide6, lxml, pypdf, pytest, pytest-qt, PyInstaller, Inno Setup.

**Spec:** `docs/superpowers/specs/2026-09-20-operator-workspace-i18n-multisource-design.md`

## Global Constraints

- Runtime remains fully offline.
- Imported files and Word templates remain read-only.
- No partial or unverified official batch may be published.
- Advanced mapping choices remain available.
- All new operator text must exist in English, Simplified Chinese, and Russian.
- Work on the existing user-authorized `master` worktree and commit each one-to-two feature slice.

## Review Focus

- A custom template field such as `{{EMPLOYEE_ID}}` must appear automatically and map to a renamed or newly added data column without code changes.
- Renaming must preserve a column's stable identifier and be undoable.
- Regenerating a preview after a data revision must not delete a PDF still held open by Qt.
- Individual PDFs must be selected by default when Word is available and explicitly unavailable when Word is not.
- The combined-PDF button must open only the exact combined artifact returned by generation.

---

### Task 1: Beginner data and custom-field workflow

**Files:**
- Modify: `src/certificate_automation/ui/data_page.py`
- Modify: `src/certificate_automation/ui/template_page.py`
- Modify: `src/certificate_automation/ui/match_page.py`
- Modify: `src/certificate_automation/locales/en.json`
- Modify: `src/certificate_automation/locales/zh_CN.json`
- Modify: `src/certificate_automation/locales/ru.json`
- Test: `tests/test_data_page.py`
- Test: `tests/test_operator_workflow.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `DatasetTableModel.rename_column(column_id: str, label: str)` and `TemplateInspection.names`.
- Produces: a visible rename action, concise source explanations, custom-field cards, and type-specific mapping controls.

- [ ] Write failing tests proving visible rename preserves the stable column ID and is undoable; custom `{{EMPLOYEE_ID}}` appears automatically; and date help uses concrete examples while non-date mappings hide date controls.
- [ ] Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest tests/test_data_page.py tests/test_operator_workflow.py tests/test_i18n.py -q`; expect failures for missing controls and guidance.
- [ ] Add translated `Rename column` via `QInputDialog`; explain paste as copying rows and headings from another table; explain automatic `{{FIELD}}` detection; show only controls relevant to the selected type; keep advanced editable date format strings.
- [ ] Re-run the focused tests; expect all to pass.
- [ ] Commit as `feat: simplify custom field setup`.

### Task 2: Lock-safe preview regeneration

**Files:**
- Modify: `src/certificate_automation/preview.py`
- Modify: `src/certificate_automation/ui/review_page.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Test: `tests/test_preview.py`
- Test: `tests/test_operator_workflow.py`

**Interfaces:**
- Consumes: `PreviewService.generate(...) -> PreviewRecord` and the `QPdfDocument` lifecycle.
- Produces: session-isolated preview paths and `ReviewPage.clear_preview()`.

- [ ] Write a failing test proving a new dataset revision leaves the old live preview untouched and a workspace test proving Qt unloads the current PDF before regeneration.
- [ ] Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest tests/test_preview.py tests/test_operator_workflow.py -q`; expect deletion/unload failures.
- [ ] Create a UUID session directory, invalidate only in-memory cache records on revision changes, unload before generation, and make final cleanup best-effort.
- [ ] Re-run the focused tests; expect all to pass.
- [ ] Commit as `fix: make preview regeneration lock safe`.

### Task 3: Clear and reliable PDF output

**Files:**
- Modify: `src/certificate_automation/domain.py`
- Modify: `src/certificate_automation/batch.py`
- Modify: `src/certificate_automation/ui/output_page.py`
- Modify: `src/certificate_automation/ui/results_page.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Modify: `src/certificate_automation/locales/en.json`
- Modify: `src/certificate_automation/locales/zh_CN.json`
- Modify: `src/certificate_automation/locales/ru.json`
- Test: `tests/test_batch.py`
- Test: `tests/test_operator_workflow.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Produces: `BatchResult.combined_pdf_path: Path | None`, exact result-button behavior, DOCX-plus-individual-PDF defaults, and a live output summary.
- Consumes: verified `CombinedPdfRecord.path`, translated output labels, and `WordAvailability`.

- [ ] Write failing tests for PDF-by-default, unavailable-Word handling, output counts, the returned final combined path, and exact combined-artifact opening.
- [ ] Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest tests/test_batch.py tests/test_operator_workflow.py tests/test_workspace.py -q`; expect failures for current defaults and missing result path.
- [ ] Default to DOCX plus individual PDF; show translated counts; disable and uncheck PDF when Word is unavailable; return the published combined path; enable/open only that exact file.
- [ ] Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q`; expect all non-Windows tests to pass and Windows-only tests to skip in WSL.
- [ ] Commit as `feat: make PDF output explicit and reliable`.

### Task 4: Windows release verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/certificate_automation/__init__.py`
- Modify: `packaging/installer.iss`
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Test: `tests/windows/test_packaged_application.py`

**Interfaces:**
- Consumes: completed application behavior from Tasks 1-3.
- Produces: version `2.1.0`, a Windows installer, and release evidence.

- [ ] Update metadata and document renaming, arbitrary fields, date examples, PDF defaults, combined printing, and the Word requirement.
- [ ] Build with PyInstaller and compile `packaging/installer.iss` using Inno Setup.
- [ ] Run packaged smoke tests, clean installer launch, a custom-field batch with individual and combined PDF, exact combined-PDF opening, and uninstall cleanup.
- [ ] Commit as `build: release Certificate Automation 2.1.0` and tag `v2.1.0`.
