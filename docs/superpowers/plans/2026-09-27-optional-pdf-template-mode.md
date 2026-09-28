# Optional PDF Template Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simple, optional PDF-background certificate workflow that generates verified PDFs without Microsoft Word while preserving the existing DOCX/Word workflow.

**Architecture:** Introduce an explicit `TemplateMode` boundary and a versioned PDF field-layout model. A native overlay renderer uses bundled redistribution-safe fonts and the existing PySide6/pypdf stack, while the workflow routes DOCX projects through the current Word converter and PDF projects through the new renderer; both reuse existing validation, approval, staging, integrity, merging, history, and recovery.

**Tech Stack:** Python 3.12+, PySide6 6.8.3 (`QtPdf`, `QPainter`, `QPdfWriter`), pypdf 6.x, pytest/pytest-qt, PyInstaller, Inno Setup 6.

**Spec:** `docs/superpowers/specs/2026-09-27-pdf-native-template-mode-design.md`

## Global Constraints

- Runtime is fully offline; no network calls, activation, downloads, telemetry, or cloud conversion.
- Support 64-bit Windows 10 version 1809 or later and 64-bit Windows 11.
- PDF mode never launches or requires Microsoft Word; Word mode remains available and behavior-compatible.
- Original PDF and DOCX templates are never modified.
- Rendering never silently truncates, shrinks, wraps, substitutes, or moves text.
- Every new visible string ships in English, Russian, and Simplified Chinese with catalog parity.
- Official output remains staged, verified, revisioned, audited, and transactionally published.
- Keep the simple path visible; numeric coordinates and expert typography remain collapsed under Advanced field settings.
- Use strict TDD and commit after each task with only Faridun as author and no AI/Codex attribution.

## Review Focus

- A PDF with a non-zero crop-box origin or page rotation must preserve visual field placement; pin this in Task 1 inspection/coordinate tests and Task 2 rendered-image tests.
- A recipient value containing unsupported Chinese, Cyrillic, emoji, combining marks, or right-to-left text must never become missing boxes; pin supported scripts and explicit missing-glyph rejection in Task 2.
- A saved project whose PDF bytes change externally must clear layout review and approval rather than reuse stale coordinates; pin this in Task 1 reconciliation and Task 4 workflow tests.
- Cancellation or failure between rendering and publication must leave no official-looking final batch; pin this in Task 5 transactional tests.
- A machine with no Word installation must still preview and publish PDF-template batches while clearly disabling DOCX output; pin this in Task 4 UI tests and Task 6 packaged Windows acceptance.

---

### Task 1: PDF template domain, inspection, and project persistence

**Files:**
- Create: `src/certificate_automation/pdf_template.py`
- Modify: `src/certificate_automation/project.py`
- Modify: `src/certificate_automation/project_migration.py`
- Test: `tests/test_pdf_template.py`
- Test: `tests/test_project.py`
- Test: `tests/test_project_migration.py`

**Interfaces:**
- Produces: `TemplateMode`, `PdfFieldLayout`, `PdfTemplateLayout`, `PdfTemplateInspection`, `inspect_pdf_template(path: Path) -> PdfTemplateInspection`, and `PdfTemplateLayout.digest() -> str`.
- Persists: `ProjectState.template_mode: str` and `ProjectState.pdf_layout: Mapping[str, object] | None` in schema version 3.

- [ ] **Step 1: Write failing PDF inspection and immutable layout tests**

Add tests for page count, media/crop boxes, rotation, encryption, invalid field names, duplicate names, rectangles outside crop boxes, deterministic JSON/digest, and rotated/non-zero-origin coordinate normalization. Assert encryption and existing signatures are blocking, while forms, annotations, transparency, and embedded-file indicators receive the spec's explicit supported/warning/blocking classification rather than disappearing silently.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest tests/test_pdf_template.py -q`  
Expected: FAIL because `certificate_automation.pdf_template` does not exist.

- [ ] **Step 3: Implement the PDF domain and fail-closed inspection**

Use frozen dataclasses with `to_json()`/`from_json()` validation. `inspect_pdf_template` uses pypdf read-only access, hashes the original file, rejects unreadable/zero-page/encrypted templates, and records page boxes and rotation without mutating the PDF.

- [ ] **Step 4: Write failing project schema-3 migration tests**

Assert schema-2 projects migrate to `template_mode="docx"` with no PDF layout, schema-3 round-trips PDF layout, newer schemas remain read-only, and changed PDF bytes invalidate layout review, mapping, output options, acknowledgements, and approval.

- [ ] **Step 5: Implement schema-3 persistence and verified backup migration**

Update `ProjectState`, payload serialization, and `ProjectMigrationService` without weakening the existing SQLite lease, hash, WAL/SHM, and backup rules.

- [ ] **Step 6: Verify and commit**

Run: `python -m pytest tests/test_pdf_template.py tests/test_project.py tests/test_project_migration.py -q`  
Expected: PASS.

```bash
git add src/certificate_automation/pdf_template.py src/certificate_automation/project.py src/certificate_automation/project_migration.py tests/test_pdf_template.py tests/test_project.py tests/test_project_migration.py
git commit -m "feat: add versioned PDF template layouts"
```

### Task 2: Native overlay renderer and multilingual font safety

**Files:**
- Create: `src/certificate_automation/pdf_overlay.py`
- Create: `src/certificate_automation/assets/fonts/README.md`
- Create: `src/certificate_automation/assets/fonts/OFL.txt`
- Create: approved pinned font files under `src/certificate_automation/assets/fonts/`
- Modify: `pyproject.toml`
- Modify: `packaging/certificate-automation.spec`
- Modify: `packaging/requirements-build.lock` only if dependency resolution changes
- Test: `tests/test_pdf_overlay.py`
- Test fixtures: `tests/fixtures/pdf_templates/`

**Interfaces:**
- Consumes: `PdfTemplateLayout` and mapped `Mapping[str, str]` values from Task 1.
- Produces: `FontRegistry`, `PdfOverlayRenderer.inspect_fit(layout, values) -> tuple[PdfOverlayIssue, ...]`, and `PdfOverlayRenderer.render(template_path: Path, destination: Path, layout: PdfTemplateLayout, values: Mapping[str, str]) -> None`.

- [ ] **Step 1: Add pinned font provenance and failing registry tests**

Record upstream URL, version, licence, SHA-256, supported families, and covered scripts. Tests require exact packaged hashes and successful Latin/Cyrillic/Simplified-Chinese glyph lookup; unsupported emoji must return `pdf.missing_glyph` rather than fallback.

- [ ] **Step 2: Run registry tests and confirm RED**

Run: `python -m pytest tests/test_pdf_overlay.py -k font -q`  
Expected: FAIL because `FontRegistry` does not exist.

- [ ] **Step 3: Implement the read-only font registry**

Load only pinned bundled fonts. Expose stable family identifiers and SHA-256 values; never search the internet or silently choose an installed font.

- [ ] **Step 4: Write failing fit and render tests**

Cover exact-fit, horizontal overflow, vertical overflow, explicit multi-line wrapping, combining marks, missing glyphs, portrait/landscape/rotated/cropped/multi-page templates, preserved page geometry, embedded/subset font evidence, extracted text, stale destination rejection, and closed file handles.

- [ ] **Step 5: Implement strict measurement and rendering**

Use Qt font metrics for fit checks, `QPdfWriter`/`QPainter` for transparent point-sized overlays, and pypdf to merge each overlay page onto the untouched background. Write to a sibling temporary file, verify it, then atomically publish only to a previously absent staging destination.

- [ ] **Step 6: Add deterministic rendered-image golden checks**

Render the fixture set and compare page size, extracted text, font resources, and rasterized field bounds within documented one-point/one-pixel tolerances. Do not use whole-file PDF hashes because metadata/object ordering may differ.

- [ ] **Step 7: Verify and commit**

Run: `python -m pytest tests/test_pdf_overlay.py tests/test_verification.py -q`  
Expected: PASS.

```bash
git add src/certificate_automation/pdf_overlay.py src/certificate_automation/assets pyproject.toml packaging tests/test_pdf_overlay.py tests/fixtures/pdf_templates
git commit -m "feat: render verified PDF template overlays"
```

### Task 3: Simple visual PDF field designer

**Files:**
- Create: `src/certificate_automation/ui/pdf_designer_page.py`
- Modify: `src/certificate_automation/ui/theme.py`
- Modify: `src/certificate_automation/locales/en.json`
- Modify: `src/certificate_automation/locales/ru.json`
- Modify: `src/certificate_automation/locales/zh_CN.json`
- Test: `tests/test_pdf_designer_page.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `PdfTemplateInspection`, `PdfTemplateLayout`, and `FontRegistry` from Tasks 1–2.
- Produces: `PdfDesignerPage.layout_changed`, `PdfDesignerPage.layout_accepted`, `set_template(path, inspection)`, `set_layout(layout)`, and `layout() -> PdfTemplateLayout`.

- [ ] **Step 1: Write failing beginner-flow widget tests**

Assert the visible default flow is `Add field` → field name → drag/resize → sample preview → Continue; page navigation and zoom remain visible; numeric coordinates, color, and line spacing begin collapsed under Advanced field settings.

- [ ] **Step 2: Run widget tests and confirm RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pdf_designer_page.py -q`  
Expected: FAIL because `PdfDesignerPage` does not exist.

- [ ] **Step 3: Implement the page canvas and point-coordinate transform**

Use a `QGraphicsView` overlay above page images rendered by `QPdfDocument`. Store all rectangles in PDF points; zoom changes only the view transform. Add, select, drag, resize, rename, duplicate, remove, undo, and redo operate through a `QUndoStack`.

- [ ] **Step 4: Write failing usability and accessibility tests**

Cover keyboard focus, arrow-key movement, delete confirmation, duplicate-name rejection, off-page rejection, locale switch without state loss, accessible names/descriptions, multi-page field navigation, and programmatic focus of the first failing field.

- [ ] **Step 5: Implement the compact properties panel and live sample preview**

Keep name, font, size, alignment, and single/multi-line mode visible. Put coordinates, color, and line spacing in the translated disclosure panel. Show fit status next to the selected field without hiding other fields.

- [ ] **Step 6: Verify and commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pdf_designer_page.py tests/test_i18n.py -q`  
Expected: PASS with catalog parity.

```bash
git add src/certificate_automation/ui/pdf_designer_page.py src/certificate_automation/ui/theme.py src/certificate_automation/locales tests/test_pdf_designer_page.py tests/test_i18n.py
git commit -m "feat: add simple PDF field designer"
```

### Task 4: Optional template mode in the guided workspace

**Files:**
- Create: `src/certificate_automation/ui/template_configuration_page.py`
- Modify: `src/certificate_automation/ui/template_page.py`
- Modify: `src/certificate_automation/ui/output_page.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Modify: `src/certificate_automation/app.py`
- Modify: locale catalogs
- Test: `tests/test_template_drop.py`
- Test: `tests/test_workspace.py`
- Test: `tests/test_ui_workflow.py`

**Interfaces:**
- Consumes: domain, renderer, and designer interfaces from Tasks 1–3.
- Produces: an explicit project-level choice between `docx` and `pdf_overlay`, with the existing `template_health` navigation slot hosting Word health or PDF design as appropriate.

- [ ] **Step 1: Write failing mode-selection and drag/drop tests**

Assert `.docx` and `.pdf` are accepted by picker and drop; unsupported files remain rejected; the two choices are plainly labelled; saved mode restores; selecting a replacement template clears downstream state.

- [ ] **Step 2: Run focused workflow tests and confirm RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_template_drop.py tests/test_ui_workflow.py -q`  
Expected: FAIL because PDF templates are not accepted.

- [ ] **Step 3: Implement the mode-aware template configuration container**

Keep one navigation step: Word mode displays existing `TemplateHealthPage`; PDF mode displays `PdfDesignerPage`. Do not add another permanent step or expose renderer terminology to beginners.

- [ ] **Step 4: Write failing output and no-Word tests**

Assert PDF mode enables individual/combined PDF, disables DOCX with a plain explanation, never queries or launches Word, and can proceed when `WordAvailability.available` is false. Word mode must retain current output defaults and checks.

- [ ] **Step 5: Implement mode-aware output and project hydration**

Route previews through `PdfOverlayRenderer` in PDF mode and current `WordPdfConverter` in Word mode. Changing mode invalidates preview/reviewer approval. Read-only projects may inspect the designer but cannot modify it.

- [ ] **Step 6: Verify and commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_template_drop.py tests/test_workspace.py tests/test_ui_workflow.py tests/test_progressive_disclosure.py -q`  
Expected: PASS.

```bash
git add src/certificate_automation/ui src/certificate_automation/app.py src/certificate_automation/locales tests/test_template_drop.py tests/test_workspace.py tests/test_ui_workflow.py
git commit -m "feat: offer Word-free PDF template workflow"
```

### Task 5: Approval, batch publication, audit, and recovery integration

**Files:**
- Modify: `src/certificate_automation/approval.py`
- Modify: `src/certificate_automation/batch.py`
- Modify: `src/certificate_automation/batch_journal.py`
- Modify: `src/certificate_automation/audit.py`
- Modify: `src/certificate_automation/integrity.py`
- Modify: `src/certificate_automation/diagnostics.py`
- Modify: `src/certificate_automation/preview.py`
- Modify: `src/certificate_automation/ui/approval_page.py`
- Test: `tests/test_approval.py`
- Test: `tests/test_batch.py`
- Test: `tests/test_audit.py`
- Test: `tests/test_integrity.py`
- Test: `tests/test_recovery_journal.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: frozen `TemplateMode`, layout digest/font hashes, and `PdfOverlayRenderer`.
- Produces: mode-bound approval snapshots and manifests whose renderer identity is `PdfOverlayRenderer/<version>` or the existing Word converter identity.

- [ ] **Step 1: Write failing approval-binding tests**

Assert template mode, PDF layout digest, exact field formatting, font hashes, geometry, previews reviewed, and renderer identity enter the immutable approval digest; any change invalidates approval.

- [ ] **Step 2: Implement approval and localized summary fields**

Show `PDF background — no Word required` or `Word template` plainly. Never label an overlay render as Word-converted or a typed name as a digital signature.

- [ ] **Step 3: Write failing transactional PDF-batch tests**

Cover 50 mixed-script recipients, fit failure before publication, cancellation mid-render, renderer exception, stale/partial output, individual and combined PDF verification, separator pages, manifest/report counts, recovery journal, retry, and no DOCX artifacts in PDF mode.

- [ ] **Step 4: Implement explicit batch routing and reuse publication safety**

Branch once at the renderer boundary from frozen approval facts. Feed overlay PDFs through the existing verification, merge, staging, intent journal, integrity, history, and final atomic publication path; do not create a parallel publication system.

- [ ] **Step 5: Write and implement audit/diagnostic privacy tests**

Manifest/report include mode, template/layout/font hashes, renderer version, geometry, and counts. Default diagnostics omit recipient values and PDF contents while retaining stable error codes and converter facts.

- [ ] **Step 6: Verify and commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_approval.py tests/test_batch.py tests/test_audit.py tests/test_integrity.py tests/test_recovery_journal.py tests/test_diagnostics.py tests/test_preview.py -q`  
Expected: PASS.

```bash
git add src/certificate_automation tests
git commit -m "feat: publish auditable PDF template batches"
```

### Task 6: Documentation, packaged no-Word acceptance, and release candidate

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `packaging/certificate-automation.spec`
- Modify: `packaging/verify-payload.ps1`
- Modify: `scripts/windows-release-acceptance.ps1`
- Modify: `tests/windows/test_packaged_application.py`
- Modify: `tests/windows/test_release_acceptance.py`
- Modify: `release-status.json`

**Interfaces:**
- Consumes: the complete optional PDF mode.
- Produces: an exact Windows installer whose isolated installed payload generates a verified PDF-template batch with Word absent.

- [ ] **Step 1: Write failing packaged no-Word acceptance**

The packaged test creates a PDF-background project, places Latin/Cyrillic/Chinese fields, generates individual and combined PDFs without Word, checks page geometry/text/font resources/manifest/report, and proves no Word process was required.

- [ ] **Step 2: Update packaging and exact-payload verification**

Include font assets and licence/provenance files in PyInstaller and Inno Setup. Extend payload verification so missing or changed fonts fail the release gate.

- [ ] **Step 3: Update the beginner documentation**

Document the four-action PDF path: choose PDF, place fields, preview, generate. Keep Word mode instructions separately available and explain why DOCX output is unavailable for PDF templates.

- [ ] **Step 4: Run full source verification**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -m "not word_integration" -q`  
Expected: all source tests pass; packaged-only tests may skip only when `--exe` is absent.

- [ ] **Step 5: Build and verify the Windows package**

Run PyInstaller from the pinned Windows build environment, run `tests/windows/test_packaged_application.py --exe ...`, compile the Inno installer, perform isolated installation, compare the installed payload exactly, and rerun packaged tests against the installed executable.

- [ ] **Step 6: Run native Word regression and Windows matrix honestly**

Run existing `word_integration` tests on a Word-equipped host to prove the optional mode did not break DOCX. Record unavailable Windows 10/11 scale rows as `machine_verification_pending`; do not tag a final release until required evidence and signing policy pass.

- [ ] **Step 7: Final review, release metadata, commit, and push**

Record the exact installer size/SHA-256 and evidence in `release-status.json`. Request an independent whole-branch safety review, fix all Critical/Important findings test-first, then commit and push both synchronized branches.

```bash
git add README.md docs/user-guide.md packaging scripts tests/windows release-status.json
git commit -m "build: prepare optional PDF template candidate"
git push origin master:master master:main
```
