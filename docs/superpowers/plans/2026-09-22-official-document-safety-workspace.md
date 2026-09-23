# Certificate Automation 3.0 Official Document Safety Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a fully offline, recoverable, auditable certificate workspace for nontechnical operators, verified on 64-bit Windows 10 and Windows 11.

**Architecture:** Extend the existing immutable domain records and transactional project/batch services with narrow services for cataloging, migration, profiles, template health, approval, duplicate history, journaling, integrity, diagnostics, and printing. Keep core logic free of dialogs; compose it through `ApplicationServices` and small PySide6 pages, with every official batch bound to one immutable project revision digest.

**Tech Stack:** Python 3.14 x64 release toolchain, PySide6/Qt 6.11.x (`>=6.11,<6.12`), SQLite, python-docx-compatible OOXML processing through lxml, Microsoft Word COM through pywin32, pypdf, PyInstaller, Inno Setup 6, Windows DPAPI, PowerShell/SignTool, pytest, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-22-official-document-safety-workspace-design.md`

## Global Constraints

- Runtime remains fully offline: no network client dependency, account, telemetry, remote storage, or background update check.
- Support 64-bit Windows 10 version 1809 or later and 64-bit Windows 11; acceptance targets Windows 10 22H2 and Windows 11 24H2/25H2.
- Build with Python 3.14 x64 and PySide6/Qt `>=6.11,<6.12`, which officially supports Windows 10 1809+ and Windows 11; do not accept an unreviewed Python or Qt major/minor upgrade.
- Microsoft Word desktop is the only official PDF renderer; missing or unhealthy Word disables PDF publication instead of selecting another renderer.
- Official staging and publication require a fixed local NTFS volume. Network, cloud-synchronized, removable, and non-NTFS locations are export destinations only.
- Never mutate source data or template files, silently overwrite a published revision, silently map a fuzzy field, silently resize template text, or label typed workflow approval as a digital signature.
- English, Simplified Chinese, and Russian catalogs must have identical keys and format parameters.
- Standard-user install and operation use `asInvoker`; no routine step requires administrator rights.
- Every implementation task starts with a failing test, ends with focused plus full non-platform tests, and commits no more than two cohesive features.
- Preserve unrelated user changes in the main checkout. Work only in the existing `operator-workspace-v2` worktree on `master`.

## Review Focus

- **Unicode, long, and locked paths:** Cyrillic/Chinese names, paths over 260 characters, spaces, and transient Windows locks produce deterministic success or a localized recoverable error; Tasks 1, 7, and 10 pin these cases.
- **Power loss at publication boundaries:** interruption after each journal transition never exposes a batch labeled official without a valid manifest; Task 7 injects each boundary failure.
- **Corrupt migration source and backup:** migration refuses to replace the original project unless the backup and migrated copy both validate; Task 1 exercises truncated SQLite, wrong hashes, and disk-full replacement.
- **Word returns stale or partial output:** template/layout and generation checks reject unchanged, unreadable, extra-page, or partially written PDFs; Tasks 4 and 7 use fake converters plus real-Word acceptance.
- **Unavailable DPAPI/history key:** cross-batch duplicate checking becomes visibly unavailable and never reports a false clean result; Task 5 exercises user mismatch, corrupt ciphertext, and missing key.

---

## File Structure

### New core modules

- `src/certificate_automation/project_catalog.py` — recent-project metadata and health only.
- `src/certificate_automation/project_migration.py` — backup-first schema migrations.
- `src/certificate_automation/profiles.py` — mapping-profile records, storage, and compatibility comparison.
- `src/certificate_automation/template_health.py` — structural issues and representative-record selection.
- `src/certificate_automation/history.py` — privacy-minimal batch index and duplicate lookup.
- `src/certificate_automation/windows_protection.py` — injectable DPAPI byte protection boundary.
- `src/certificate_automation/approval.py` — frozen revision digest and workflow approval records.
- `src/certificate_automation/batch_journal.py` — durable monotonic batch lifecycle journal.
- `src/certificate_automation/integrity.py` — published manifest and artifact verification.
- `src/certificate_automation/diagnostics.py` — redacted local support ZIP creation.
- `src/certificate_automation/print_readiness.py` — count, order, page geometry, and hash checks.
- `src/certificate_automation/platform_report.py` — normalized Windows, Word, Qt, Python, and filesystem facts.

### New UI modules

- `src/certificate_automation/ui/project_home_page.py` — new/open/recent/recover/example entry point.
- `src/certificate_automation/ui/template_health_page.py` — health issues and representative previews.
- `src/certificate_automation/ui/approval_page.py` — final summary, acknowledgements, preparer/reviewer flow.
- `src/certificate_automation/ui/history_page.py` — completed/incomplete batch actions and integrity status.
- `src/certificate_automation/ui/support_dialog.py` — redacted diagnostic package controls.

### Existing modules with focused changes

- `src/certificate_automation/project.py` — schema-2 project fields and coordinator integration.
- `src/certificate_automation/template.py` — richer location/protection metadata, without UI policy.
- `src/certificate_automation/validation.py` — health, history, destination, approval, and readiness gates.
- `src/certificate_automation/batch.py` — journal-driven staging, revision publication, and audit v3.
- `src/certificate_automation/audit.py` — audit schema 3 and localized official report.
- `src/certificate_automation/recovery.py` — journal-aware recovery actions.
- `src/certificate_automation/output_options.py` — separator and print geometry settings.
- `src/certificate_automation/app.py` — dependency composition only.
- `src/certificate_automation/ui/workspace.py` — orchestration and invalidation only; nested home UI moves out.
- `src/certificate_automation/ui/output_page.py` and `results_page.py` — print settings and exact verified artifact actions.
- `src/certificate_automation/locales/{en,zh_CN,ru}.json` — all new operator strings.
- `packaging/certificate-automation.spec`, `packaging/installer.iss`, `pyproject.toml` — locked Windows release.
- `packaging/windows-app.manifest`, `packaging/sign-release.ps1`, `packaging/verify-release.ps1` — Windows declarations and signing.
- `docs/user-guide.md`, `README.md` — operator and release documentation.

### New tests

- `tests/test_project_catalog.py`, `test_project_migration.py`, `test_profiles.py`, `test_template_health.py`, `test_history.py`, `test_windows_protection.py`, `test_approval.py`, `test_batch_journal.py`, `test_integrity.py`, `test_diagnostics.py`, `test_print_readiness.py`, `test_platform_report.py`.
- `tests/test_project_home_page.py`, `test_template_health_page.py`, `test_approval_page.py`, `test_history_page.py`, `test_support_dialog.py`.
- `tests/windows/test_windows_matrix_acceptance.py`, `test_signing_pipeline.py`, and `scripts/windows-release-acceptance.ps1`.

---

### Task 1: Project Catalog and Backup-First Schema Migration

**Files:**
- Create: `src/certificate_automation/project_catalog.py`
- Create: `src/certificate_automation/project_migration.py`
- Modify: `src/certificate_automation/project.py`
- Test: `tests/test_project_catalog.py`
- Test: `tests/test_project_migration.py`
- Modify: `tests/test_project.py`

**Interfaces:**
- Consumes: existing `ProjectStore.open(path)`, `ProjectStore.load()`, `ProjectState`, and SQLite project files.
- Produces: `ProjectCatalog(path: Path)`, `ProjectSummary`, `ProjectHealth`, `ProjectMigrationService.migrate(path: Path) -> MigrationResult`, and project schema version 2.

- [ ] **Step 1: Pin catalog behavior with failing tests**

```python
def test_catalog_does_not_store_recipient_values(tmp_path, project_state):
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    catalog.remember(tmp_path / "people.certproject", project_state)
    text = catalog.path.read_text("utf-8")
    assert "Ana García" not in text
    assert catalog.list()[0].recipient_count == len(project_state.dataset.rows)

def test_catalog_reports_missing_project_without_removing_entry(tmp_path):
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    path = tmp_path / "missing.certproject"
    catalog.remember_path(path)
    summary = catalog.list()[0]
    assert summary.health is ProjectHealth.MISSING
    assert summary.path == path
```

- [ ] **Step 2: Run catalog tests and verify the missing module failure**

Run: `.venv/bin/python -m pytest tests/test_project_catalog.py -q`

Expected: collection fails with `ModuleNotFoundError: certificate_automation.project_catalog`.

- [ ] **Step 3: Implement atomic privacy-minimal catalog persistence**

```python
class ProjectHealth(str, Enum):
    READY = "ready"
    MISSING = "missing"
    UNREADABLE = "unreadable"
    NEWER_SCHEMA = "newer_schema"

@dataclass(frozen=True, slots=True)
class ProjectSummary:
    path: Path
    last_saved_at: datetime | None
    recipient_count: int | None
    active_step: str | None
    template_name: str | None
    health: ProjectHealth

class ProjectCatalog:
    def remember(self, path: Path, state: ProjectState) -> None: ...
    def remember_path(self, path: Path) -> None: ...
    def list(self) -> tuple[ProjectSummary, ...]: ...
    def forget(self, path: Path) -> None: ...
```

Write JSON through a sibling temporary file, flush and `os.fsync`, then `os.replace`. Store path, timestamps, counts, step, template basename, and schema only. Cap the catalog at 12 entries.

- [ ] **Step 4: Pin safe migration with failing tests**

```python
def test_migration_creates_valid_backup_before_replacing_source(tmp_path, schema1_project):
    result = ProjectMigrationService().migrate(schema1_project)
    assert result.from_version == 1
    assert result.to_version == 2
    assert result.backup_path.is_file()
    assert ProjectStore.open(result.backup_path).load().revision >= 0
    assert ProjectStore.open(schema1_project).load().schema_version == 2

@pytest.mark.parametrize("failure", ["backup_invalid", "disk_full", "replacement_locked"])
def test_migration_failure_keeps_original_bytes(tmp_path, schema1_project, failure, fault_fs):
    before = schema1_project.read_bytes()
    with pytest.raises(ProjectMigrationError):
        ProjectMigrationService(files=fault_fs(failure)).migrate(schema1_project)
    assert schema1_project.read_bytes() == before
```

- [ ] **Step 5: Implement schema-2 migration and project-state fields**

```python
@dataclass(frozen=True, slots=True)
class MigrationResult:
    path: Path
    backup_path: Path
    from_version: int
    to_version: int

class ProjectMigrationService:
    def migrate(self, path: Path) -> MigrationResult: ...
```

Add `schema_version`, `project_name`, `profile_path`, `approval`, `published_revisions`, and `print_settings` to `ProjectState`. Read schema 1 with defaults. Migration copies the database to `.pre-v2-backup`, validates it through `ProjectStore`, builds and validates a separate migrated database, then atomically replaces the source.

- [ ] **Step 6: Exercise corrupt and Unicode path cases**

Add tests for truncated SQLite, newest revision with a wrong payload hash, `项目 Анна.certproject`, a path over 260 characters on a long-path-capable test filesystem, and a locked replacement. Every failure must carry a stable `project.*` issue code and preserve the original bytes.

- [ ] **Step 7: Run focused and full tests**

Run: `.venv/bin/python -m pytest tests/test_project.py tests/test_project_catalog.py tests/test_project_migration.py -q`

Run: `.venv/bin/python -m pytest -m 'not word_integration' -q`

Expected: all tests pass.

- [ ] **Step 8: Commit the catalog and migration checkpoint**

```bash
git add src/certificate_automation/project.py src/certificate_automation/project_catalog.py src/certificate_automation/project_migration.py tests/test_project.py tests/test_project_catalog.py tests/test_project_migration.py
git commit -m "feat: add safe project catalog and migration"
git push origin master
```

---

### Task 2: Project Home, Save Status, and Guided Example

**Files:**
- Create: `src/certificate_automation/ui/project_home_page.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Modify: `src/certificate_automation/app.py`
- Modify: `src/certificate_automation/locales/en.json`
- Modify: `src/certificate_automation/locales/zh_CN.json`
- Modify: `src/certificate_automation/locales/ru.json`
- Create: `tests/test_project_home_page.py`
- Modify: `tests/test_workspace.py`
- Modify: `tests/test_shutdown.py`
- Modify: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `ProjectCatalog`, `ProjectMigrationService`, `ProjectCoordinator`, installed `examples/` files.
- Produces: `ProjectHomePage`, `WorkspaceWindow.load_project(path)`, visible save-state enum, and safe sample-copy workflow.

- [ ] **Step 1: Write failing home-page interaction tests**

```python
def test_home_exposes_five_beginner_actions(qtbot, catalogs):
    page = ProjectHomePage(catalogs)
    qtbot.addWidget(page)
    assert [button.objectName() for button in page.primary_buttons()] == [
        "newProject", "openProject", "recentProjects", "recoverProject", "tryExample"
    ]

def test_missing_recent_project_stays_visible_with_repair_action(qtbot, catalogs):
    page = ProjectHomePage(catalogs)
    page.set_projects((missing_summary(),))
    assert page.project_status(0) == catalogs.text("project.health.missing")
    assert page.repair_button(0).isVisible()
```

- [ ] **Step 2: Run the home-page test and observe the import failure**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_project_home_page.py -q`

Expected: collection fails because `project_home_page.py` does not exist.

- [ ] **Step 3: Extract the nested home widget and add save-state UI**

```python
class SaveState(str, Enum):
    SAVED = "saved"
    SAVING = "saving"
    FAILED = "failed"
    READ_ONLY = "read_only"

class ProjectHomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    recover_requested = Signal()
    example_requested = Signal()
    project_requested = Signal(Path)
```

Move home-only widgets out of `workspace.py`. Add a persistent accessible save-state label. Connect coordinator `saved` and `save_failed` signals. A failed close-time flush presents retry or explicit discard; cancel keeps the window open.

- [ ] **Step 4: Write and implement guided-example safety tests**

```python
def test_example_is_copied_and_installed_files_remain_unchanged(tmp_path, app_services):
    originals = hashes(app_services.example_root)
    project = app_services.create_example(tmp_path / "My Example")
    assert project.is_file()
    assert hashes(app_services.example_root) == originals

def test_example_refuses_nonempty_destination(tmp_path, app_services):
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_text("mine")
    with pytest.raises(ExampleProjectError, match="example.destination_not_empty"):
        app_services.create_example(destination)
```

Implement `create_example_project(example_root, destination) -> Path` with an exact empty-directory requirement, copied sample files, and a schema-2 project pointing at the copies.

- [ ] **Step 5: Add complete translations and accessibility assertions**

Add keys for home actions, health states, save states, migration outcomes, example guidance, and close-time save failure. Test 200% font scaling with `QFont` enlargement, tab order, visible focus, unique accessible names, and catalog parity.

- [ ] **Step 6: Run focused and full tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_project_home_page.py tests/test_workspace.py tests/test_shutdown.py tests/test_i18n.py -q`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

- [ ] **Step 7: Commit the project-home checkpoint**

```bash
git add src/certificate_automation/app.py src/certificate_automation/ui/project_home_page.py src/certificate_automation/ui/workspace.py src/certificate_automation/locales tests
git commit -m "feat: add recoverable project home"
git push origin master
```

---

### Task 3: Reusable Mapping Profiles

**Files:**
- Create: `src/certificate_automation/profiles.py`
- Modify: `src/certificate_automation/mapping.py`
- Modify: `src/certificate_automation/ui/mapping_page.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Create: `tests/test_profiles.py`
- Modify: `tests/test_mapping.py`
- Modify: `tests/test_ui_workflow.py`
- Modify: `src/certificate_automation/locales/{en,zh_CN,ru}.json`

**Interfaces:**
- Consumes: `MappingPlan.to_json()`, `MappingPlan.from_json()`, template placeholder names, and dataset columns.
- Produces: `MappingProfile`, `ProfileStore`, `ProfileComparison`, and explicit `ProfileMatch` statuses.

- [ ] **Step 1: Pin profile privacy and compatibility with failing tests**

```python
def test_profile_omits_recipient_rows_and_sensitive_fixed_values(tmp_path):
    profile = MappingProfile.from_plan("Annual awards", plan_with_fixed("Secret"))
    with pytest.raises(ProfileError, match="profile.sensitive_fixed_value"):
        ProfileStore(tmp_path).save(profile)

def test_profile_comparison_never_commits_fuzzy_match():
    result = compare_profile(profile_for("FULL_NAME"), columns("Student Name"), ("FULL_NAME",))
    assert result.matches["FULL_NAME"].status is ProfileMatchStatus.REVIEW_REQUIRED
    assert result.applied_plan.sources == {}
```

- [ ] **Step 2: Run tests to verify the missing profile module failure**

Run: `.venv/bin/python -m pytest tests/test_profiles.py -q`

- [ ] **Step 3: Implement versioned profile records and atomic store**

```python
class ProfileMatchStatus(str, Enum):
    EXACT = "exact"
    REVIEW_REQUIRED = "review_required"
    MISSING = "missing"
    UNUSED = "unused"

@dataclass(frozen=True, slots=True)
class MappingProfile:
    schema_version: int
    name: str
    description: str
    expected_placeholders: tuple[str, ...]
    mappings: Mapping[str, object]
    template_sha256: str | None
    defaults: Mapping[str, object]

class ProfileStore:
    def save(self, profile: MappingProfile, *, allow_fixed_values: bool = False) -> Path: ...
    def load(self, path: Path) -> MappingProfile: ...
    def list(self) -> tuple[ProfileSummary, ...]: ...
```

Use `.certprofile` JSON with deterministic serialization and a payload SHA-256. Reject extra or missing schema fields and never load code or pickle data.

- [ ] **Step 4: Implement stable semantic comparison**

`compare_profile(profile, columns, placeholders) -> ProfileComparison` applies only exact normalized column-ID or unique exact label matches. Similarity scoring may populate a suggestion label but returns `REVIEW_REQUIRED`; it never enters `applied_plan` until the operator chooses it.

- [ ] **Step 5: Add mapping-page profile controls and comparison panel**

Add **Save profile**, **Apply profile**, and a table with `Applied`, `Review`, `Missing`, and `Unused`. Require explicit confirmation before saving fixed values. Applying or changing a profile invalidates preview, warning acknowledgement, and approval.

- [ ] **Step 6: Run focused, catalog, and full tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_profiles.py tests/test_mapping.py tests/test_ui_workflow.py tests/test_i18n.py -q`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

- [ ] **Step 7: Commit the mapping-profile checkpoint**

```bash
git add src/certificate_automation/profiles.py src/certificate_automation/mapping.py src/certificate_automation/ui/mapping_page.py src/certificate_automation/ui/workspace.py src/certificate_automation/locales tests/test_profiles.py tests/test_mapping.py tests/test_ui_workflow.py tests/test_i18n.py
git commit -m "feat: add safe reusable mapping profiles"
git push origin master
```

---

### Task 4: Template Health and Representative Layout Review

**Files:**
- Create: `src/certificate_automation/template_health.py`
- Create: `src/certificate_automation/ui/template_health_page.py`
- Modify: `src/certificate_automation/template.py`
- Modify: `src/certificate_automation/preview.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Create: `tests/test_template_health.py`
- Create: `tests/test_template_health_page.py`
- Modify: `tests/test_template.py`
- Modify: `tests/test_preview.py`
- Modify: `tests/windows/test_word_integration.py`
- Modify: `src/certificate_automation/locales/{en,zh_CN,ru}.json`

**Interfaces:**
- Consumes: `TemplateInspection`, `TabularDataset`, `MappingPlan`, `PreviewService`, and `verify_pdf`.
- Produces: `TemplateHealthReport`, `RepresentativeRecord`, `TemplateHealthService.inspect(...)`, and `TemplateHealthPage`.

- [ ] **Step 1: Pin malformed placeholder and location reporting**

```python
def test_health_reports_malformed_and_duplicate_locations(template_factory):
    path = template_factory(body="{{FULL_NAME} {{AWARD}}", header="{{AWARD}}")
    report = TemplateHealthService().inspect_structure(path)
    assert issue_codes(report) == {"template.malformed_placeholder", "template.duplicate_placeholder"}
    assert any(location.part == "header1.xml" for location in report.locations("AWARD"))
```

- [ ] **Step 2: Run the structural test and confirm failure**

Run: `.venv/bin/python -m pytest tests/test_template_health.py::test_health_reports_malformed_and_duplicate_locations -q`

- [ ] **Step 3: Implement structural report without changing replacement behavior**

```python
@dataclass(frozen=True, slots=True)
class TemplateLocation:
    part: str
    paragraph_index: int
    table_path: tuple[int, ...] = ()

@dataclass(frozen=True, slots=True)
class TemplateHealthReport:
    template_sha256: str
    issues: tuple[Issue, ...]
    placeholders: Mapping[str, tuple[TemplateLocation, ...]]
    section_geometries: tuple[PageGeometry, ...]
    representative_rows: tuple[str, ...] = ()
```

Extend OOXML inspection to report malformed braces, duplicates and locations, protection, macros/linked content when present, comments/tracked changes, section sizes, and orientation. Do not reject a repeated placeholder merely because it appears in multiple intended places; classify it as informational unless the mappings or document structure make it ambiguous.

- [ ] **Step 4: Pin representative-record selection and conservative layout status**

```python
def test_representatives_cover_longest_value_per_mapped_field(dataset, plan):
    selected = TemplateHealthService().select_representatives(dataset, plan, limit=8)
    assert row_with_longest(dataset, "full_name") in selected
    assert row_with_longest(dataset, "award") in selected

def test_partial_or_stale_pdf_never_marks_layout_reviewed(tmp_path, fake_converter):
    fake_converter.write_then_leave_old_timestamp()
    result = TemplateHealthService(converter=fake_converter).render_representatives(...)
    assert result.ready is False
    assert "preview.stale_output" in issue_codes(result)
```

- [ ] **Step 5: Implement rendering and health-page review state**

Select the union of rows with the longest rendered value for each mapped placeholder, then reduce deterministically to eight rows while keeping first, last, and highest-risk rows. Render through Word into isolated UUID directories. Require a newly created PDF, stable file size across two reads, readable pages, expected geometry, and expected page count. Unknown clipping remains `template.layout_review_required` until the operator reviews each representative preview.

- [ ] **Step 6: Integrate a distinct Template Health workflow step**

Change `STEP_IDS` to include `template_health` after template selection and before mapping completion review. The page groups **Must fix**, **Review**, and **Information**, explains limitations, and provides direct navigation to each representative preview. Any template, data, or mapping revision clears layout review.

- [ ] **Step 7: Run focused, full, and real-Word tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_template.py tests/test_template_health.py tests/test_template_health_page.py tests/test_preview.py tests/test_workspace.py tests/test_i18n.py -q`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

On Windows: `python -m pytest tests/windows/test_word_integration.py -m word_integration -q`

- [ ] **Step 8: Commit the template-health checkpoint**

```bash
git add src/certificate_automation/template.py src/certificate_automation/template_health.py src/certificate_automation/preview.py src/certificate_automation/ui/template_health_page.py src/certificate_automation/ui/workspace.py src/certificate_automation/locales tests
git commit -m "feat: add template health and layout review"
git push origin master
```

---

### Task 5: Privacy-Protected Duplicate History

**Files:**
- Create: `src/certificate_automation/windows_protection.py`
- Create: `src/certificate_automation/history.py`
- Modify: `src/certificate_automation/validation.py`
- Modify: `src/certificate_automation/project.py`
- Create: `tests/test_windows_protection.py`
- Create: `tests/test_history.py`
- Modify: `tests/test_validation.py`
- Modify: `src/certificate_automation/locales/{en,zh_CN,ru}.json`

**Interfaces:**
- Consumes: normalized values from `TabularDataset`, configured identity column IDs, published batch metadata.
- Produces: `ByteProtector`, `DpapiProtector`, `HistoryIndex`, `DuplicatePolicy`, `DuplicateMatch`, and validation issues.

- [ ] **Step 1: Write failing protector and false-clean prevention tests**

```python
def test_history_uses_keyed_hashes_not_plain_names(tmp_path, memory_protector):
    index = HistoryIndex(tmp_path / "history.sqlite", memory_protector)
    index.record(batch("B-1"), identities=("Ana García",))
    assert b"Ana" not in (tmp_path / "history.sqlite").read_bytes()

@pytest.mark.parametrize("mode", ["missing_key", "corrupt_ciphertext", "wrong_user"])
def test_unavailable_key_returns_unknown_not_clean(tmp_path, broken_protector, mode):
    result = HistoryIndex(tmp_path / "history.sqlite", broken_protector(mode)).check(("Ana",))
    assert result.status is HistoryStatus.UNAVAILABLE
    assert result.matches == ()
```

- [ ] **Step 2: Run tests and verify missing modules**

Run: `.venv/bin/python -m pytest tests/test_windows_protection.py tests/test_history.py -q`

- [ ] **Step 3: Implement injectable Windows protection boundary**

```python
class ByteProtector(Protocol):
    def protect(self, value: bytes, *, purpose: str) -> bytes: ...
    def unprotect(self, value: bytes, *, purpose: str) -> bytes: ...

class DpapiProtector:
    def protect(self, value: bytes, *, purpose: str) -> bytes:
        return win32crypt.CryptProtectData(value, purpose, None, None, None, 0)[1]
```

Keep pywin32 import inside methods so non-Windows unit tests use `MemoryProtector`. Map DPAPI failures to stable `history.protection_unavailable` codes without logging secret bytes.

- [ ] **Step 4: Implement minimal history index and duplicate policy**

Generate a random HMAC-SHA256 key once, protect it with DPAPI, and store only protected key bytes, keyed identity hashes, certificate-ID hashes, batch ID, revision, UTC completion, and folder path. Use explicit transactions and schema versioning.

```python
@dataclass(frozen=True, slots=True)
class DuplicatePolicy:
    certificate_id_column: str | None
    identity_columns: tuple[str, ...]
    check_history: bool

class HistoryIndex:
    def check(self, identities: tuple[str, ...]) -> HistoryCheck: ...
    def record(self, batch: PublishedBatch, identities: tuple[str, ...]) -> None: ...
    def clear(self) -> None: ...
```

- [ ] **Step 5: Extend validation with exact and likely duplicate rules**

Exact certificate-ID and output-filename collisions are errors. Exact normalized selected-identity matches are warnings requiring acknowledgement. A `HistoryStatus.UNAVAILABLE` result is a warning that explicitly says history was not checked; it is never rendered as “no duplicates found.”

- [ ] **Step 6: Run focused and full tests**

Run: `.venv/bin/python -m pytest tests/test_windows_protection.py tests/test_history.py tests/test_validation.py -q`

Run: `.venv/bin/python -m pytest -m 'not word_integration' -q`

- [ ] **Step 7: Commit the duplicate-history checkpoint**

```bash
git add src/certificate_automation/windows_protection.py src/certificate_automation/history.py src/certificate_automation/validation.py src/certificate_automation/project.py src/certificate_automation/locales tests/test_windows_protection.py tests/test_history.py tests/test_validation.py
git commit -m "feat: add privacy-protected duplicate history"
git push origin master
```

---

### Task 6: Frozen Final Approval and Optional Two-Person Review

**Files:**
- Create: `src/certificate_automation/approval.py`
- Create: `src/certificate_automation/ui/approval_page.py`
- Modify: `src/certificate_automation/project.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Modify: `src/certificate_automation/validation.py`
- Create: `tests/test_approval.py`
- Create: `tests/test_approval_page.py`
- Modify: `tests/test_workspace.py`
- Modify: `src/certificate_automation/locales/{en,zh_CN,ru}.json`

**Interfaces:**
- Consumes: project revision, source/template hashes, mapping plan, health review, warnings, output options, Word availability, and representative preview hashes.
- Produces: `ApprovalSnapshot`, `WorkflowApproval`, `ApprovalService.freeze(...)`, `ApprovalService.verify(...)`, and `ApprovalPage`.

- [ ] **Step 1: Write failing digest and invalidation tests**

```python
def test_approval_digest_is_deterministic_and_value_sensitive(approval_input):
    first = ApprovalService.freeze(approval_input)
    second = ApprovalService.freeze(approval_input)
    changed = ApprovalService.freeze(replace(approval_input, recipient_count=51))
    assert first.digest == second.digest
    assert first.digest != changed.digest

@pytest.mark.parametrize("field", ["dataset_revision", "template_sha256", "mapping", "outputs", "warnings", "preview_hashes"])
def test_any_relevant_change_invalidates_approval(approved_project, field):
    changed = mutate(approved_project, field)
    assert ApprovalService.verify(changed.approval, changed.approval_input).valid is False
```

- [ ] **Step 2: Run approval tests and confirm missing module**

Run: `.venv/bin/python -m pytest tests/test_approval.py -q`

- [ ] **Step 3: Implement canonical snapshot digest and records**

```python
@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    digest: str
    project_revision: int
    recipient_count: int
    output_counts: Mapping[str, int]
    warning_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class WorkflowApproval:
    snapshot: ApprovalSnapshot
    preparer_name: str
    prepared_at: datetime
    reviewer_name: str | None = None
    reviewed_at: datetime | None = None
```

Canonicalize JSON with sorted keys, UTF-8, and compact separators. Require nonblank display names. In two-person mode require distinct case-folded names and a reviewer action after freeze. Do not store passwords or describe this as identity authentication.

- [ ] **Step 4: Write failing approval-page summary tests**

Assert exact recipient, excluded, DOCX, PDF, combined, separator, report, warning, page, destination, template hash, and Word status values. Assert the generate action remains disabled until required acknowledgements and reviewer approval are complete.

- [ ] **Step 5: Implement page and workflow integration**

Insert `approval` between output and generate steps. Recompute the snapshot whenever the page opens. Any upstream state change clears the stored approval. `start_generation()` must call `ApprovalService.verify` again immediately before constructing `BatchRequest`.

- [ ] **Step 6: Run focused and full tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_approval.py tests/test_approval_page.py tests/test_workspace.py tests/test_validation.py tests/test_i18n.py -q`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

- [ ] **Step 7: Commit the approval checkpoint**

```bash
git add src/certificate_automation/approval.py src/certificate_automation/project.py src/certificate_automation/validation.py src/certificate_automation/ui/approval_page.py src/certificate_automation/ui/workspace.py src/certificate_automation/locales tests
git commit -m "feat: add frozen two-person approval workflow"
git push origin master
```

---

### Task 7: Durable Batch Journal, Integrity Verification, and Protected Revisions

**Files:**
- Create: `src/certificate_automation/batch_journal.py`
- Create: `src/certificate_automation/integrity.py`
- Modify: `src/certificate_automation/batch.py`
- Modify: `src/certificate_automation/audit.py`
- Modify: `src/certificate_automation/recovery.py`
- Modify: `src/certificate_automation/domain.py`
- Modify: `src/certificate_automation/validation.py`
- Create: `tests/test_batch_journal.py`
- Create: `tests/test_integrity.py`
- Modify: `tests/test_batch.py`
- Modify: `tests/test_audit.py`
- Modify: `tests/test_operator_workflow.py`

**Interfaces:**
- Consumes: verified `WorkflowApproval`, `BatchRequest`, fixed-local-NTFS destination report, output verifiers.
- Produces: `BatchJournal`, `JournalState`, `IntegrityService.verify_revision(path)`, revisioned `BatchResult`, and recoverable `IncompleteBatch` actions.

- [ ] **Step 1: Pin monotonic durable journal behavior**

```python
@pytest.mark.parametrize("current,next_state", [
    ("created", "verifying"),
    ("rendering", "created"),
    ("published", "verifying"),
])
def test_journal_rejects_skipped_or_backward_transitions(tmp_path, current, next_state):
    journal = journal_at(tmp_path, current)
    with pytest.raises(JournalError, match="journal.invalid_transition"):
        journal.transition(JournalState(next_state))

def test_journal_atomic_write_leaves_previous_valid_record_on_failure(tmp_path, fault_fs):
    journal = BatchJournal.create(tmp_path, request_summary())
    fault_fs.fail_replace_once()
    with pytest.raises(JournalError):
        journal.transition(JournalState.RENDERING)
    assert BatchJournal.open(journal.path).state is JournalState.CREATED
```

- [ ] **Step 2: Implement journal states and synchronized atomic writes**

```python
class JournalState(str, Enum):
    CREATED = "created"
    RENDERING = "rendering"
    VERIFYING = "verifying"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"

class BatchJournal:
    @classmethod
    def create(cls, staging: Path, request: JournalRequest) -> "BatchJournal": ...
    @classmethod
    def open(cls, path: Path) -> "BatchJournal": ...
    def transition(self, state: JournalState, **facts: object) -> None: ...
```

Journal JSON includes schema, batch ID, approval digest, destination, revision, intended counts, timestamps, current state, and last verified checkpoint. Each write flushes, fsyncs, atomically replaces, and fsyncs the containing directory where supported.

- [ ] **Step 3: Pin manifest integrity failures**

```python
@pytest.mark.parametrize("mutation", ["missing", "extra", "changed", "renamed", "wrong_pages", "wrong_order"])
def test_integrity_service_rejects_mutated_revision(published_revision, mutation):
    mutate_revision(published_revision, mutation)
    report = IntegrityService().verify_revision(published_revision)
    assert report.valid is False
    assert report.issues
```

- [ ] **Step 4: Implement audit schema 3 and integrity verification**

Add revision number, approval digest, journal identity, platform report, page geometry/count, preparer/reviewer workflow records, artifact sizes, and export status. `IntegrityService` rejects manifest path traversal, duplicate entries, case-insensitive filename collisions, missing/extra artifacts, changed hashes, and combined-order/page mismatches.

- [ ] **Step 5: Integrate revisioned generation and fixed-local-NTFS validation**

Add `revision_number` and `approval_digest` to `BatchRequest`. Resolve the next revision while holding a destination lock file created with exclusive mode. Validate the destination through `PlatformReport.inspect_volume`; reject UNC, removable, cloud-marked, and non-NTFS authoritative destinations. Render into `.certificate-incomplete-<batch-id>`, transition the journal at each phase, verify, then atomically rename to `<safe-name>-revision-<n>`.

- [ ] **Step 6: Inject failure after every publication boundary**

```python
@pytest.mark.parametrize("boundary", list(JournalState))
def test_interruption_never_publishes_unverified_official_folder(tmp_path, boundary, generator):
    generator.fail_after(boundary)
    with pytest.raises(BatchGenerationError):
        generator.generate(request(tmp_path))
    assert not any(path.name.endswith("revision-1") for path in tmp_path.iterdir())
    assert RecoveryService().find_incomplete(tmp_path)
```

Also test locked files, disk full, stale Word output, a converter that writes a partial PDF before raising, and a long Unicode destination. Recovery may restart from the frozen request or discard exact app-owned staging; it never promotes partial bytes.

- [ ] **Step 7: Add protected correction workflow**

Mark published files read-only after journal state `published`. Add `IntegrityService.clone_for_correction(project, revision) -> ProjectState`, which retains lineage but clears approvals and allocates the next revision. Tests prove original bytes and manifest remain unchanged.

- [ ] **Step 8: Run focused, full, and real 50-recipient tests**

Run: `.venv/bin/python -m pytest tests/test_batch_journal.py tests/test_integrity.py tests/test_batch.py tests/test_audit.py tests/test_operator_workflow.py -q`

Run: `.venv/bin/python -m pytest -m 'not word_integration' -q`

On Windows: `python -m pytest tests/windows/test_release_acceptance.py::test_real_word_publishes_verified_50_recipient_mixed_script_batch -m word_integration -q`

- [ ] **Step 9: Commit the publication-safety checkpoint**

```bash
git add src/certificate_automation/batch_journal.py src/certificate_automation/integrity.py src/certificate_automation/batch.py src/certificate_automation/audit.py src/certificate_automation/recovery.py src/certificate_automation/domain.py src/certificate_automation/validation.py tests
git commit -m "feat: add journaled protected batch revisions"
git push origin master
```

---

### Task 8: History Center, Audit Report, and Redacted Support Packages

**Files:**
- Create: `src/certificate_automation/diagnostics.py`
- Create: `src/certificate_automation/platform_report.py`
- Create: `src/certificate_automation/ui/history_page.py`
- Create: `src/certificate_automation/ui/support_dialog.py`
- Modify: `src/certificate_automation/audit.py`
- Modify: `src/certificate_automation/history.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Create: `tests/test_diagnostics.py`
- Create: `tests/test_platform_report.py`
- Create: `tests/test_history_page.py`
- Create: `tests/test_support_dialog.py`
- Modify: `tests/test_audit.py`
- Modify: `src/certificate_automation/locales/{en,zh_CN,ru}.json`

**Interfaces:**
- Consumes: audit schema 3, `HistoryIndex`, `RecoveryService`, `IntegrityService`, exception/issue records.
- Produces: `PlatformReport`, `DiagnosticBundleService.create(...)`, `HistoryPage`, `SupportDialog`, and localized official audit HTML.

- [ ] **Step 1: Pin recursive redaction and ZIP safety**

```python
def test_default_bundle_excludes_values_paths_and_document_bytes(tmp_path):
    bundle = DiagnosticBundleService().create(context_with("Ana García", Path.home()), tmp_path / "support.zip")
    payload = read_all_zip_text(bundle)
    assert "Ana García" not in payload
    assert str(Path.home()) not in payload
    assert not any(name.endswith((".docx", ".pdf", ".xlsx")) for name in zip_names(bundle))

def test_bundle_rejects_archive_traversal_name(tmp_path):
    with pytest.raises(DiagnosticError, match="diagnostic.unsafe_name"):
        DiagnosticBundleService().create(context(), tmp_path / ".." / "support.zip")
```

- [ ] **Step 2: Implement normalized platform report and diagnostic service**

```python
@dataclass(frozen=True, slots=True)
class PlatformReport:
    application_version: str
    python_version: str
    qt_version: str
    windows_release: str
    windows_build: str
    word_version: str | None
    volume_kind: str
    filesystem: str

class DiagnosticBundleService:
    def create(self, context: DiagnosticContext, destination: Path, *, sensitive_files: tuple[Path, ...] = ()) -> Path: ...
```

Recursively replace user-profile and project paths with tokens, omit mapping values and row values, whitelist allowed diagnostic filenames, and write ZIP entries from memory with normalized names. Sensitive files require an explicit nonempty tuple supplied only after UI confirmation.

- [ ] **Step 3: Expand localized audit report tests**

Assert audit HTML shows revision, exact counts, hashes, platform/converter versions, warning acknowledgements, workflow approval disclaimer, print facts, and lineage. Assert HTML escaping with names containing `<`, `&`, Cyrillic, and Chinese.

- [ ] **Step 4: Implement history and support UI**

History lists completed/incomplete records with `Open folder`, `Open combined PDF`, `Open audit`, `Verify integrity`, `Correct as new revision`, and `Remove incomplete staging`. Missing output remains visible. Support dialog defaults to redacted mode, lists any sensitive attachment individually, and never transmits anything.

- [ ] **Step 5: Run focused and full tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_diagnostics.py tests/test_platform_report.py tests/test_history_page.py tests/test_support_dialog.py tests/test_audit.py tests/test_i18n.py -q`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

- [ ] **Step 6: Commit the audit-and-support checkpoint**

```bash
git add src/certificate_automation/diagnostics.py src/certificate_automation/platform_report.py src/certificate_automation/audit.py src/certificate_automation/history.py src/certificate_automation/ui/history_page.py src/certificate_automation/ui/support_dialog.py src/certificate_automation/ui/workspace.py src/certificate_automation/locales tests
git commit -m "feat: add auditable history and safe diagnostics"
git push origin master
```

---

### Task 9: Print Readiness and Verified Export

**Files:**
- Create: `src/certificate_automation/print_readiness.py`
- Modify: `src/certificate_automation/output_options.py`
- Modify: `src/certificate_automation/pdf_merge.py`
- Modify: `src/certificate_automation/ui/output_page.py`
- Modify: `src/certificate_automation/ui/results_page.py`
- Modify: `src/certificate_automation/ui/workspace.py`
- Create: `tests/test_print_readiness.py`
- Modify: `tests/test_pdf_merge.py`
- Modify: `tests/test_ui_workflow.py`
- Modify: `tests/test_workspace.py`
- Modify: `src/certificate_automation/locales/{en,zh_CN,ru}.json`

**Interfaces:**
- Consumes: published audit schema 3, individual PDFs, combined PDF, generation order, `OutputOptions`.
- Produces: `PrintSettings`, `PrintReadinessReport`, `PrintReadinessService.verify(...)`, separator-page policy, and post-publication `ExportService`.

- [ ] **Step 1: Pin page geometry, ordering, and separator behavior**

```python
@pytest.mark.parametrize("mutation", ["wrong_size", "wrong_orientation", "missing_row", "duplicate_row", "wrong_order", "wrong_hash"])
def test_print_readiness_rejects_mismatch(published_revision, mutation):
    mutate_revision(published_revision, mutation)
    report = PrintReadinessService().verify(published_revision)
    assert report.ready is False
    assert report.issues

def test_separator_pages_do_not_change_recipient_order(pdf_factory):
    merged = merge_with_separators(pdf_factory(3), every=2)
    assert merged.source_order == ("row-1", "row-2", "row-3")
    assert merged.separator_positions == (3,)
```

- [ ] **Step 2: Run tests and verify missing service**

Run: `.venv/bin/python -m pytest tests/test_print_readiness.py -q`

- [ ] **Step 3: Implement print settings and readiness service**

```python
@dataclass(frozen=True, slots=True)
class PrintSettings:
    expected_width_points: Decimal
    expected_height_points: Decimal
    orientation: Literal["portrait", "landscape"]
    separator_every: int | None = None

@dataclass(frozen=True, slots=True)
class PrintReadinessReport:
    ready: bool
    recipient_count: int
    individual_page_count: int
    combined_page_count: int
    issues: tuple[Issue, ...]
```

Use PDF media/crop boxes with a documented one-point tolerance. Compare manifest row IDs, source order, hashes, individual pages, combined pages, and separator positions. Never infer printer completion.

- [ ] **Step 4: Implement results-page readiness and safe export**

Show **Ready to print** only for a fresh valid report. Open the exact manifest-listed combined PDF. `ExportService.export_revision(source, destination)` allows network/cloud/removable targets only after local integrity verification, copies into a new destination folder, verifies every copied hash, and reports the local folder as authoritative.

- [ ] **Step 5: Add output-page controls and translations**

Add expected page size/orientation inherited from the template by default, optional separator pages, plain-language page-count forecast, and a note that printing occurs through the Windows PDF application.

- [ ] **Step 6: Run focused and full tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_print_readiness.py tests/test_pdf_merge.py tests/test_ui_workflow.py tests/test_workspace.py tests/test_i18n.py -q`

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

- [ ] **Step 7: Commit the print-readiness checkpoint**

```bash
git add src/certificate_automation/print_readiness.py src/certificate_automation/output_options.py src/certificate_automation/pdf_merge.py src/certificate_automation/ui/output_page.py src/certificate_automation/ui/results_page.py src/certificate_automation/ui/workspace.py src/certificate_automation/locales tests
git commit -m "feat: add verified print readiness and export"
git push origin master
```

---

### Task 10: Windows 10/11 Runtime, Installer, and Signing Pipeline

**Files:**
- Create: `packaging/windows-app.manifest`
- Create: `packaging/sign-release.ps1`
- Create: `packaging/verify-release.ps1`
- Create: `scripts/windows-release-acceptance.ps1`
- Modify: `packaging/certificate-automation.spec`
- Modify: `packaging/installer.iss`
- Modify: `pyproject.toml`
- Create: `tests/windows/test_windows_matrix_acceptance.py`
- Create: `tests/windows/test_signing_pipeline.py`
- Modify: `tests/windows/test_packaged_application.py`
- Modify: `tests/test_release_metadata.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: exact release candidate bundle and installer, optional certificate thumbprint and timestamp URL supplied at build time.
- Produces: Windows-compatible signed-or-explicitly-unsigned artifacts, `release-metadata.json`, and machine-readable acceptance evidence.

- [ ] **Step 1: Pin dependency and manifest metadata**

Add tests asserting the release version is `3.0.0`, PySide6 remains within the approved Windows 10-compatible line, the executable targets x64, installer remains `PrivilegesRequired=lowest`, and the manifest contains Windows 10/11 compatibility, `longPathAware=true`, and `asInvoker`.

```python
def test_windows_manifest_declares_supported_runtime():
    root = ET.parse("packaging/windows-app.manifest").getroot()
    text = ET.tostring(root, encoding="unicode")
    assert "8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a" in text
    assert "longPathAware" in text and "true" in text
    assert 'level="asInvoker"' in text
```

- [ ] **Step 2: Implement and embed the Windows manifest**

Create an application manifest with the supportedOS GUID, long-path awareness, per-monitor-v2 DPI awareness, UTF-8 active code page where supported, and `asInvoker`. Embed it through the PyInstaller spec and verify it from the built executable with a Windows resource inspection command.

- [ ] **Step 3: Write failing signing-script contract tests**

```python
def test_signing_requested_without_certificate_fails(powershell):
    result = powershell("packaging/sign-release.ps1", "-RequireSigning", "-Input", "fixture.exe")
    assert result.returncode != 0
    assert "SIGNING_CERTIFICATE_REQUIRED" in result.stderr

def test_unsigned_metadata_is_explicit(unsigned_release_metadata):
    assert unsigned_release_metadata["signature_status"] == "unsigned"
    assert unsigned_release_metadata["publisher"] is None
```

- [ ] **Step 4: Implement fail-closed signing and verification scripts**

`sign-release.ps1` accepts `-CertificateThumbprint`, optional `-TimestampUrl`, `-Input`, and `-RequireSigning`. It locates 64-bit SignTool, signs with `/fd SHA256`, timestamps with `/td SHA256` when configured, and calls `verify-release.ps1`. Verification checks every expected executable plus installer, signer subject/thumbprint, signature status, and final SHA-256. Requested signing with any unsigned or invalid file exits nonzero. No secret or certificate file is committed.

- [ ] **Step 5: Build the exact offline x64 bundle and installer**

On Windows:

```powershell
python -m pip install --require-hashes -r packaging\requirements-build.lock
python -m PyInstaller --noconfirm --clean packaging\certificate-automation.spec
& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Add the generated lock file to the repository. Build output must contain all dependencies and examples; runtime smoke tests run with network adapters disabled or outbound access blocked.

- [ ] **Step 6: Implement matrix acceptance script**

`scripts/windows-release-acceptance.ps1` records OS edition/build/architecture, filesystem, display scale, Word version, installer hash, signature state, and each test result into JSON. It performs silent clean install, normal responsive launch, all input families, save/recover, 50-recipient mixed-script DOCX/PDF/combined generation, Unicode and long paths, locked-file recovery, upgrade, and silent uninstall.

- [ ] **Step 7: Execute Windows 10 and Windows 11 release gates**

Run the exact installer on clean x64 Windows 10 22H2, Windows 11 24H2, and Windows 11 25H2 machines or VMs. Run 100%, 150%, and 200% display-scale UI smoke tests across the matrix. Save evidence under `dist/acceptance/<os-build>/` but do not commit machine-specific output.

If a target is unavailable, set its release metadata state to `machine_verification_pending`; do not mark the release fully Windows-verified.

- [ ] **Step 8: Run packaged and real-Word regression on the release host**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest tests\windows\test_packaged_application.py -q --exe dist\CertificateAutomation\CertificateAutomation.exe
python -m pytest tests\windows -m word_integration -q
```

- [ ] **Step 9: Commit the Windows release pipeline checkpoint**

```bash
git add packaging scripts tests/windows tests/test_release_metadata.py pyproject.toml README.md
git commit -m "build: add verified Windows 10 and 11 release pipeline"
git push origin master
```

---

### Task 11: Translation, Accessibility, Documentation, and Release 3.0.0

**Files:**
- Modify: `src/certificate_automation/locales/en.json`
- Modify: `src/certificate_automation/locales/zh_CN.json`
- Modify: `src/certificate_automation/locales/ru.json`
- Modify: all new/changed UI modules with untranslated literals found by tests
- Modify: `docs/user-guide.md`
- Modify: `README.md`
- Modify: `src/certificate_automation/__init__.py`
- Modify: `packaging/installer.iss`
- Modify: `tests/test_i18n.py`
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_ui_workflow.py`
- Modify: `tests/windows/test_release_acceptance.py`

**Interfaces:**
- Consumes: all features and release evidence from Tasks 1–10.
- Produces: complete localized operator experience, release documentation, installer 3.0.0, tag `v3.0.0`, and final checksum.

- [ ] **Step 1: Add failing catalog and source-leakage tests**

```python
def test_all_catalogs_have_identical_keys_and_parameters():
    assert validate_catalogs(package_root()) == ()

@pytest.mark.parametrize("locale", ["zh_CN", "ru"])
def test_new_workflows_do_not_display_english_fallback(locale, qtbot, services):
    window = WorkspaceWindow(services.with_locale(locale))
    qtbot.addWidget(window)
    for text in collect_visible_operator_text(window):
        assert text not in NEW_ENGLISH_ONLY_SENTENCES
```

Also scan Python UI source for user-visible string literals not routed through catalogs, with an explicit allowlist for object names and technical constants.

- [ ] **Step 2: Complete translations and accessibility behavior**

Translate every project, migration, profile, health, duplicate, approval, journal, integrity, history, diagnostic, print, signing, and platform issue. Verify format parameters, plural-safe count phrasing, keyboard navigation, focus order, accessible names/descriptions, non-color status indicators, and translated text at 200% scaling.

- [ ] **Step 3: Update the offline operator guide**

Document the full workflow with short explanations, sample project, profiles, layout-review limits, two-person disclaimer, protected corrections, integrity checks, support ZIP privacy, print readiness, export rules, Windows compatibility, Word requirement, and signed-versus-unsigned installer status.

- [ ] **Step 4: Run complete source verification**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration' -q`

Run: `.venv/bin/python -m pytest --cov=certificate_automation --cov-report=term-missing -m 'not word_integration'`

Expected: all tests pass; new safety services have branch coverage for success and every specified failure class.

- [ ] **Step 5: Build and test the final exact installer**

Build from a clean worktree at the intended release commit. Run packaged tests, real Word tests, the 50-recipient release acceptance, clean install, responsive launch, upgrade from 2.1.1, and clean uninstall. Re-run `verify-release.ps1` after copying the installer to the delivery folder.

- [ ] **Step 6: Review Windows matrix evidence and label honestly**

Confirm each declared OS row has JSON evidence for the exact installer hash. If Windows 10 22H2, Windows 11 24H2, or Windows 11 25H2 lacks evidence, list that row as `machine_verification_pending` in release metadata and release notes.

- [ ] **Step 7: Commit release metadata and documentation**

```bash
git add src/certificate_automation docs README.md packaging tests
git commit -m "build: release Certificate Automation 3.0.0"
git push origin master
```

- [ ] **Step 8: Tag only the verified release commit**

```bash
git status --short --branch
git tag -a v3.0.0 -m "Certificate Automation 3.0.0"
git push origin v3.0.0
```

Record the installer absolute path, byte size, SHA-256, signature status, Git commit, tag, source-test count, packaged-test count, Word-test count, and Windows matrix state in the final handoff.

---

## Final Verification Checklist

- [ ] Project catalog contains no recipient values and preserves missing entries for repair.
- [ ] Schema migration validates original backup and migrated copy before atomic replacement.
- [ ] Guided example never edits installed examples or a nonempty destination.
- [ ] Profiles never silently commit fuzzy mappings or sensitive fixed values.
- [ ] Template health finds structural defects and requires human review where clipping cannot be proven.
- [ ] DPAPI/key failures produce **history unavailable**, never a false clean duplicate result.
- [ ] Approval digest invalidates after every relevant upstream change.
- [ ] Two-person mode requires a distinct reviewer action and uses no signature/authentication language.
- [ ] Every injected batch interruption leaves no unverified official revision.
- [ ] Integrity checks catch missing, extra, renamed, changed, reordered, and wrong-page artifacts.
- [ ] Diagnostic ZIP is redacted by default and contains no source documents.
- [ ] Print readiness verifies count, order, hashes, geometry, and separators.
- [ ] Authoritative publication is local NTFS; exported copies are verified but identified as copies.
- [ ] Runtime makes no network requests and installs all dependencies locally.
- [ ] English, Simplified Chinese, and Russian catalogs and workflows pass parity tests.
- [ ] Exact release installer passes packaged and real-Word tests.
- [ ] Windows 10 22H2 and Windows 11 24H2/25H2 evidence matches the exact installer hash, or each unavailable target is plainly marked pending.
- [ ] Signing either verifies to the configured organization certificate or the release is plainly labeled unsigned.
- [ ] Worktree is clean, `master` equals `origin/master`, and `v3.0.0` resolves to the tested commit.
