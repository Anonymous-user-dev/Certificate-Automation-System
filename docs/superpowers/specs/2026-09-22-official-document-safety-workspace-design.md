# Certificate Automation 3.0: Official Document Safety Workspace

**Status:** Approved conversational design; written specification awaiting user review  
**Date:** 2026-09-22  
**Product:** Certificate Automation, fully offline Windows desktop application

## 1. Purpose

Certificate Automation 3.0 will turn the existing certificate generator into a recoverable, auditable workspace for high-level official documents. A nontechnical operator must be able to prepare, review, generate, print, reopen, and diagnose a batch without editing code or risking silent document corruption.

The application remains fully offline at runtime. It will support 64-bit Windows 10 version 1809 or later and 64-bit Windows 11. Microsoft Word desktop remains the authoritative PDF conversion engine because substituting a different renderer can change official document layout.

## 2. Safety principles

1. **Never guess silently.** Ambiguous mappings, duplicate identities, uncertain layout, unavailable conversion, changed source files, and incomplete approvals stop publication or require an explicit recorded acknowledgement.
2. **Official output is transactional.** Work happens in staging. A selected batch becomes visible in its final folder only after every required artifact verifies.
3. **Corrections create revisions.** Published files are never silently overwritten. A correction creates a new revision linked to the earlier batch.
4. **Claims match evidence.** Workflow approval is not called a legal signature. Heuristic layout checks are not called proof. Unsigned installers are not called trusted.
5. **Privacy is the default.** Diagnostics omit recipient values and document contents unless the operator explicitly chooses to include them.
6. **Recovery is explicit.** The application explains what was saved, what was published, and what can safely be retried after a failure.
7. **The simple path stays simple.** Advanced controls remain available but do not dominate the normal guided workflow.

## 3. Scope

### 3.1 Included

- Project home, recent projects, auto-save, versioned recovery, and guided sample project.
- Reusable mapping profiles that contain configuration but no recipient records.
- Expanded template structural health checks and conservative layout-risk checks.
- Final approval summary and optional two-person workflow approval.
- Durable staged generation, crash journal, protected revisions, and integrity verification.
- Current-batch and optional cross-batch duplicate detection.
- Local batch history with minimal privacy-preserving indexes.
- Human-readable audit report, machine manifest, and privacy-safe support package.
- Print-readiness verification and controlled handoff to the Windows print workflow.
- Reproducible Windows 10/11 build, test, installer, and optional signing pipeline.
- Complete English, Simplified Chinese, and Russian interface coverage.

### 3.2 Explicitly excluded

- Cloud accounts, telemetry, remote storage, online verification, or runtime network access.
- AI-based correction or automatic content rewriting.
- Silent fallback to LibreOffice or another PDF renderer.
- Claims that a typed reviewer name is a cryptographic or legal signature.
- Password management, organization-wide identity management, or networked multi-user locking.
- Direct unattended printing of official documents.
- Modification of the operator's source workbook or Word template.

## 4. Existing foundations

The implementation must extend, not duplicate, these existing components:

- `ProjectStore` and `ProjectCoordinator` for SQLite revisions, hash checking, auto-save, and rotating backups.
- `BatchGenerator` for staged all-or-nothing output publication.
- `RecoveryService` for incomplete batch and project-backup discovery.
- `audit.py` for SHA-256 manifests, offline summaries, and privacy-conscious logs.
- Template inspection, validation, preview, Word conversion, PDF verification, PDF merging, and localized issue catalogs.

Existing project files will be migrated with explicit schema migration code. A newer unsupported schema opens read-only. Migration never destroys the original file; a verified backup is created first.

## 5. User experience

### 5.1 Project Home

Startup opens a calm home page with five primary actions:

- **New project**
- **Open project**
- **Recent projects**
- **Recover project**
- **Try an example**

Recent entries show project name, last saved time, template name, recipient count, current step, and a clear missing-file or integrity warning. The list stores paths and operational metadata only; it does not copy recipient values.

The sample project is copied to a user-chosen working folder. Installed examples remain read-only and are never edited in place.

### 5.2 Save status

The main window always shows one of: **Saved**, **Saving**, **Save failed—retry**, or **Read-only**. Closing with an unsaved revision triggers a final save attempt. If it fails, the application offers retry or an explicit exit-without-saving choice and states what would be lost.

### 5.3 Guided workflow

The supported workflow remains linear:

1. Project
2. Recipient data
3. Template health
4. Match fields
5. Validate
6. Preview
7. Output and print settings
8. Final approval
9. Generate
10. Results and history

Operators may move backward without losing work. Any upstream change invalidates dependent previews, acknowledgements, reviewer approval, and generation readiness.

## 6. Project persistence and recovery

### 6.1 Project contents

A `.certproject` file stores:

- imported dataset snapshot and stable row/column identifiers;
- source identity, hash, import choices, and dataset revision;
- template path, template hash, and inspection result;
- mapping plan and saved profile reference;
- output, filename, merge, separator, and print settings;
- warnings and acknowledgements tied to the exact project revision;
- preparer and reviewer records;
- current step and preview identity;
- links to published batch revisions, never the output bytes themselves.

### 6.2 Transaction and backup rules

- SQLite uses explicit transactions and full synchronization for project commits.
- A failed save remains pending and visible to the operator.
- Three rotating database backups are retained.
- Each backup is opened and hash-validated before it is advertised as recoverable.
- Recovery previews candidate revision, timestamp, recipient count, and source/template status before replacement.
- Restoring a backup writes a new project revision; it does not erase the damaged file.

### 6.3 External file reconciliation

On open and before approval, the application re-hashes referenced data and template files. Changed bytes invalidate inspection, mappings where necessary, previews, acknowledgements, and approval. Missing external files do not destroy the saved dataset snapshot; the project opens with a clear repair action.

## 7. Mapping profiles

A mapping profile is a separate versioned local file containing only:

- profile name and description;
- expected placeholder names;
- mapping expression types and referenced semantic column labels;
- date, sequence, joining, filename, and output defaults;
- originating template hash as advisory metadata;
- profile schema and application version.

Profiles never contain recipient rows, fixed sensitive values by default, approvals, or output history. Saving a fixed value requires an explicit warning because it may contain private information.

Applying a profile produces a comparison:

- exact matches applied automatically;
- renamed or missing columns require operator selection;
- new template placeholders remain visibly unmatched;
- profile fields absent from the template are reported as unused;
- no fuzzy match is committed without confirmation.

## 8. Template health and layout risk

### 8.1 Structural inspection

Inspection covers body paragraphs, tables, headers, footers, text boxes, and placeholders split across Word runs. It reports:

- valid detected placeholders;
- malformed braces and empty placeholders;
- duplicates, including where they occur;
- unsupported or inaccessible document parts;
- tracked changes, comments, protected documents, fields, macros, or linked content when detectable;
- unexpected section count, page orientation, and page size differences;
- placeholders not mapped and mappings unused by the template.

Blocking issues prevent generation. Warnings require review and are identified in the audit record.

### 8.2 Layout-risk analysis

The application selects representative records for preview, including longest names and longest mapped values. It renders them through Microsoft Word and verifies PDF readability, expected page count, page size, and orientation.

Where exact text clipping cannot be proven automatically, the app reports **Layout review required** and presents the risky records for human preview. Character-count heuristics may prioritize records but can never independently certify fit. The application never silently reduces font size, changes margins, or edits the template.

## 9. Duplicate protection

### 9.1 Current batch

Validation detects:

- duplicate stable certificate IDs;
- identical normalized recipient records;
- likely duplicates using configurable selected identity fields;
- filename collisions after normalization;
- duplicate generated output hashes where distinct output was expected.

Exact certificate-ID and filename collisions are blocking. Likely identity duplicates require explicit review and acknowledgement.

### 9.2 Cross-batch history

Cross-batch checking is optional and enabled per project or profile. The history index stores:

- normalized certificate-ID hashes;
- keyed hashes of selected recipient identity fields;
- batch ID, revision, completion time, and output folder reference;
- no certificate content and no raw recipient names.

The key is generated locally and protected for the current Windows user with Windows Data Protection API. If the key is unavailable, history checking is disabled with a visible explanation; the application never creates a new key and pretends old history was checked.

The operator can clear the local index without deleting official batch folders.

## 10. Approval workflow

### 10.1 Final approval screen

The screen displays:

- recipient count and excluded-row count;
- template filename and hash summary;
- exact DOCX, individual PDF, combined PDF, separator, manifest, and report counts;
- destination and proposed revision folder;
- mapping summary;
- warning count and acknowledgements;
- representative previews reviewed;
- print size, orientation, and expected combined page count;
- Word availability and converter identity.

Approval is bound to an immutable project revision digest. Any relevant change invalidates it.

### 10.2 Two-person mode

Two-person mode is optional. The preparer enters a display name and freezes a review revision. A reviewer must reopen that frozen state, inspect the summary and previews, enter a different display name, and explicitly approve. Copying or editing project files cannot preserve approval because the digest is revalidated.

This is workflow accountability, not authentication. The interface and audit report must not call it a digital signature. Strong organizational identity remains outside this offline single-user product.

## 11. Generation, crash safety, and protected revisions

### 11.1 Durable staging

Each run receives a random batch ID and a staging directory inside the selected destination. Before work begins, a durable journal records the batch ID, project revision digest, intended outputs, and state.

Journal states are monotonic:

`created -> rendering -> verifying -> ready_to_publish -> published`

Each state transition is atomically written and synchronized. Official filenames are not exposed in the final revision folder until verification is complete.

### 11.2 Publication

Publication requires:

- selected artifact counts match the approval summary;
- every DOCX has no unresolved placeholder;
- every PDF opens, has expected minimum pages, and matches required page properties;
- combined PDF order and page count match its source list;
- manifest hashes match staged bytes;
- destination revision does not already exist.

The final folder name contains a readable batch name and immutable revision number. Official publication requires a fixed local NTFS volume and uses an atomic directory rename within that volume. UNC/network paths, cloud-synchronized folders detected through Windows file attributes, removable media, and non-NTFS volumes may receive an exported copy only after successful local publication; they cannot be the authoritative staging or publication destination.

### 11.3 Recovery

On startup and when choosing a destination, incomplete journals are discovered. The operator may:

- inspect a privacy-safe failure summary;
- retry from a safe verified checkpoint when supported;
- restart the batch from the frozen project revision;
- discard the incomplete staging folder.

Recovery never merges unverified partial output into an official revision.

### 11.4 Protection and correction

Completed revision artifacts are marked read-only as an accidental-edit deterrent. Integrity is enforced by manifest verification, not by claiming filesystem read-only flags are tamper-proof.

A correction workflow clones settings into a new project revision and generates a new output revision. Earlier revisions remain referenced in history and are never overwritten by the application.

## 12. Audit, history, and diagnostics

### 12.1 Published audit package

Every official revision contains:

- localized human-readable HTML audit report;
- JSON manifest with schema version;
- input and template identities and SHA-256 hashes;
- project revision digest and batch/revision identifiers;
- mappings, selected outputs, ordering, warning codes, and acknowledgements;
- preparer/reviewer workflow records when enabled;
- filenames, sizes, page counts, and hashes for each artifact;
- application, Python, Qt, Windows, Word, and converter versions;
- completion status and UTC timestamps.

Recipient values appear only where necessary to identify the output in the human report. The machine manifest uses stable row IDs and filenames and avoids copying full input rows.

### 12.2 History center

The local history center lists completed and incomplete batches. It can open the output folder, combined PDF, audit report, project, or integrity check. Missing folders are reported without deleting their history automatically.

### 12.3 Support package

The default diagnostic ZIP contains:

- redacted support log;
- application and platform versions;
- issue codes and stack trace with user/profile paths replaced;
- configuration shape without mapped values;
- manifest structure and hash results without recipient values or document bytes;
- crash journal when present.

An optional **Include sensitive files** flow lists each file and requires explicit confirmation. The ZIP is saved locally and never transmitted by the application.

## 13. Print readiness

Before presenting **Ready to print**, the application verifies:

- requested and generated recipient counts match;
- no duplicate or missing row IDs;
- all PDFs are readable;
- page size and orientation are consistent with the approved settings;
- individual and combined page counts agree;
- combined order matches the reviewed recipient order;
- separator pages, if enabled, occur in the configured positions;
- the combined PDF hash still matches the manifest.

The operator can open the verified combined PDF or its folder. Printing is handed to the normal Windows PDF application; Certificate Automation does not perform unattended printing or claim printer success.

## 14. Internationalization and accessibility

Every user-facing string, including recovery, signing, history, approval, migration, and error text, must exist in English, Simplified Chinese, and Russian. Tests require key parity and reject source-language leakage in non-English workflows.

The UI must support keyboard navigation, visible focus, accessible names, 100–200% Windows scaling, screen-reader-friendly status text, and layouts that tolerate translated text expansion. Color is never the only status signal.

## 15. Windows compatibility

### 15.1 Supported runtime matrix

- Windows 10 x64, version 1809 or later; release acceptance targets Windows 10 22H2.
- Windows 11 x64; release acceptance targets Windows 11 24H2 and 25H2.
- Microsoft Word desktop editions that remain supported by Microsoft and expose Word COM automation.
- Standard-user, per-user installation under LocalAppData.

Windows 10 compatibility is an application claim, not a claim that Windows 10 itself remains supported by Microsoft. Documentation must state that ordinary Windows 10 support ended on 2025-10-14.

### 15.2 Build constraints

- Pin PySide6/Qt to a line that officially supports both Windows 10 and Windows 11.
- Build an x64 application and installer on Windows using a reproducible locked dependency set.
- Embed a Windows 10/11 compatibility and long-path-aware manifest.
- Use `asInvoker`; routine installation and operation must not require administrator rights.
- Package all runtime libraries locally; the installed app performs no dependency download.
- Validate Unicode paths, long paths, spaces, read-only locations, authoritative-output rejection on network/cloud/removable/non-NTFS locations, post-publication export to those locations, low disk space, antivirus locks, and concurrent file locks.

### 15.3 Release evidence

A production release is not labeled Windows-verified until the exact installer passes on clean Windows 10 and Windows 11 machines or VMs:

- install, launch, restart, upgrade, and uninstall;
- all input source families;
- project save, backup, corruption, migration, and recovery;
- Word DOCX-to-PDF conversion and COM teardown;
- 50-recipient mixed Latin/Cyrillic/Chinese batch;
- individual and combined PDF verification;
- crash/interruption recovery;
- non-ASCII and long paths;
- 100%, 150%, and 200% display scaling;
- standard-user operation;
- signature verification when signing is enabled.

If one target is unavailable, release notes state **implementation-ready, machine verification pending** for that target.

## 16. Signing and release integrity

The repository will include an opt-in signing script and release checks. Signing configuration is supplied through explicit build inputs and never committed.

When signing is enabled:

1. Build the executable bundle.
2. Sign executable binaries with SHA-256.
3. Verify every expected signature.
4. Build the installer from the signed bundle.
5. Sign the installer with SHA-256.
6. Verify the installer signature and publisher.
7. Record certificate thumbprint, subject, timestamp status, and final installer hash in release metadata.

Failure at any signing or verification step aborts the signed release. A trusted public signature requires an organization-controlled code-signing certificate. Timestamping may require build-time network access; installed application behavior remains fully offline.

When signing is disabled, artifacts and documentation are labeled **unsigned**. The application never fabricates or embeds a self-signed certificate as though it were publicly trusted.

## 17. Component boundaries

New or expanded services have narrow responsibilities:

- `ProjectCatalog`: recent-project metadata and health, separate from project contents.
- `ProjectMigrationService`: versioned, backup-first schema migrations.
- `ProfileStore`: mapping-profile persistence and compatibility comparison.
- `TemplateHealthService`: structural issues and representative-record selection.
- `HistoryIndex`: minimal protected cross-batch duplicate keys and batch references.
- `ApprovalService`: revision digest, invalidation, preparer, and reviewer records.
- `BatchJournal`: durable monotonic generation state.
- `IntegrityService`: manifest and published-artifact revalidation.
- `PrintReadinessService`: page properties, count, order, and hash checks.
- `DiagnosticBundleService`: redacted local support ZIP creation.
- `PlatformReport`: runtime and release-environment facts.

The UI consumes typed results from these services. Core services do not display dialogs and remain independently testable.

## 18. Error handling

Every operational failure maps to a stable issue code and localized message containing:

- what happened;
- whether any official files were published;
- what remains safely saved;
- the recommended next action;
- the location of recoverable diagnostics when applicable.

Raw exception text and paths do not replace the operator explanation. Technical detail is available through an expandable panel and redacted support package.

No failure handler deletes a project, source, template, published revision, or ambiguous directory. Destructive cleanup is limited to exact application-owned staging paths after validation and explicit operator choice.

## 19. Testing strategy

Implementation follows test-driven development. Required layers are:

- unit tests for migrations, profiles, hashes, approval invalidation, journals, history keys, redaction, and print checks;
- property and boundary tests for paths, names, Unicode, counts, revisions, and corrupted payloads;
- Qt tests for the project home, guided flow, accessibility, translation expansion, and failure recovery;
- integration tests for project lifecycle, frozen approval, staged publication, interrupted recovery, and revision correction;
- real Microsoft Word tests for representative previews and 50-recipient output;
- packaged executable and clean-installer tests;
- exact Windows 10/11 acceptance scripts producing machine-readable evidence.

Fault-injection tests cover disk-full errors, permissions, locked files, missing Word, Word hangs, corrupt documents, changed sources, power-loss-like interruption between journal states, malformed projects, invalid backups, and antivirus-style transient access denial.

No test may replace real Word or packaged-app acceptance while claiming those integrations are verified.

## 20. Delivery sequence and commit gates

The work is divided into reviewable checkpoints:

1. Project catalog, migrations, recovery UI, and guided example.
2. Mapping profiles and compatibility comparison.
3. Template health and representative layout review.
4. Duplicate history and privacy protection.
5. Approval workflow and two-person mode.
6. Durable batch journal, recovery, and protected revisions.
7. Audit report, history center, and diagnostic bundles.
8. Print readiness and separator controls.
9. Windows manifest, locked build, installer upgrade path, and signing pipeline.
10. Translation completion, accessibility, Windows 10/11 acceptance, and release.

Each checkpoint requires focused tests, the complete non-platform test suite, and a clean commit before the next checkpoint. One or two cohesive features per commit is the target. Failed or partially verified work is not pushed as a release.

## 21. Acceptance criteria

The release is complete only when:

- all included features are available through the GUI without editing configuration files;
- a first-time operator can complete the sample project using instructions inside the application;
- draft work survives normal close, crash simulation, and valid-backup recovery;
- changed inputs invalidate stale review and approval state;
- profiles adapt safely without silent fuzzy mapping;
- risky layouts are surfaced through representative Word-rendered previews;
- duplicates are detected according to configured local-history policy;
- two-person mode requires a distinct reviewer action on the frozen revision;
- failed batches publish no official revision;
- corrections create new immutable revision folders;
- manifests verify every published artifact and reveal later modification;
- support ZIPs contain no recipient values by default;
- print readiness proves counts, order, page properties, and current hashes;
- the application makes zero runtime network requests;
- the exact installer passes the declared Windows 10 and Windows 11 release matrix, or any untested target is explicitly marked pending;
- signed builds verify to the configured certificate, while unsigned builds are plainly labeled;
- English, Simplified Chinese, and Russian tests pass with no missing keys;
- the full automated, packaged, real-Word, and installer suites pass from a clean release candidate.
