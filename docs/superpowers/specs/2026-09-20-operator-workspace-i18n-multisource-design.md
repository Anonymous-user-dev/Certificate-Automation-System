# Certificate Automation 2.0 Operator Workspace Design

## Purpose

Certificate Automation 2.0 will be an offline Windows desktop product that a first-time, nontechnical office worker can use safely to prepare, review, generate, and print official certificate batches. It must make every consequential choice visible, refuse ambiguous data, recover from interruption, and preserve traceability without exposing recipient data in support logs.

The release replaces the current form-like wizard with a guided operator workspace; adds complete English, Simplified Chinese, and Russian localization; accepts tabular data from multiple offline sources or direct entry; and optionally creates one verified combined PDF for bulk printing.

## Product principles

- Remain fully offline at runtime. Do not add accounts, telemetry, remote translation, cloud storage, or network-dependent validation.
- Prefer an explicit stop with a plain-language correction over a silent guess.
- Never modify imported files or the selected Word template.
- Never publish a partial or unverified official batch.
- Keep advanced choices available without placing them in the first-time user's main path.
- Present source values, mappings, preview results, filenames, and output choices before generation.
- Keep every operation available in English, Simplified Chinese, and Russian.
- Treat tests as necessary evidence, then verify the packaged application and representative documents visually.

## Operator workflow

### Home

The home screen provides four primary actions:

1. New certificate batch.
2. Continue a saved draft.
3. Recover an interrupted batch.
4. Open previous results.

A language selector is always visible in the top-right. The selected language applies immediately and is stored only in local application settings.

### Workspace shell

A persistent left sidebar shows six steps with complete, current, warning, or blocked states:

1. Recipient Data
2. Certificate Template
3. Match Fields
4. Review
5. Output Options
6. Generate and Results

The main panel uses a consistent header, one-sentence explanation, contextual help, and Back/Continue buttons. The current step and the next safe action must always be visually obvious. Destructive actions require explicit confirmation; ordinary navigation does not.

### Recipient Data

The user chooses one of four sources:

- Excel workbook (`.xlsx`);
- delimited text (`.csv` or `.tsv`);
- table pasted from the clipboard;
- a table created and edited inside the application.

All sources open in the same spreadsheet-like editor. The operator can add, remove, rename, reorder, and edit columns and rows; undo and redo edits; and search or sort the visible data. Direct cell highlighting identifies missing values, duplicates, unsafe filename inputs, and column-name conflicts.

Imports are read-only. The editor works on an internal snapshot and never writes back to the source. Legacy `.xls`, `.ods`, databases, and cloud spreadsheets are not direct 2.0 inputs; staff can export them to `.xlsx`, `.csv`, or `.tsv`, or paste their rows. This keeps the supported surface auditable while covering common office workflows.

### Certificate Template

The operator chooses one `.docx` template. The application displays the template filename, hash, page count when previewable, and detected placeholders. Placeholder cards show the human-readable field name, occurrence count, and location category. Damaged, protected, macro-enabled, or ambiguous templates are rejected with correction instructions.

### Match Fields

Each placeholder has one explicit source:

- a data column;
- fixed text;
- sequential certificate number;
- source row number;
- a formatted date;
- a concatenation of selected columns with a literal separator.

Arbitrary formulas, scripts, regular-expression transformations, and executable extensions are excluded. They make official output difficult to review and reproduce.

Every mapping displays representative values from at least three rows when available. Its state is Exact, Suggested, Manual, Fixed, or Unresolved. Suggested mappings are visually distinct and require review. Generation remains blocked while any placeholder is unresolved.

### Review

Review contains a recipient selector and can render any selected recipient, not only the first. It shows:

- the exact source values;
- resolved placeholder values;
- planned output filename;
- a generated PDF preview;
- batch-level errors and warnings;
- Word availability, destination access, estimated storage, and output counts.

The operator may move directly from a validation issue to the affected cell or mapping. Errors block generation. Warnings require acknowledgement before official generation.

### Output Options

The operator selects:

- editable DOCX files;
- individual PDF files;
- an optional combined PDF for printing;
- recipient ordering for the combined PDF;
- destination folder;
- batch display name.

At least one published output must be selected: editable DOCX files, individual PDFs, or a combined PDF. Individual and combined PDF output require desktop Microsoft Word. The default remains DOCX plus individual PDFs; combined PDF is off by default. When the operator requests only a combined PDF, verified individual PDFs exist solely inside the unpublished staging transaction and are not copied to the final batch.

### Generate and Results

Generation shows named phases and `current / total` progress. Cancellation occurs only between safe document boundaries. The result screen provides large actions for opening the output folder, combined PDF, summary, and audit manifest.

A failure screen states what completed, what was withheld, what the user should correct, and where the redacted diagnostic record is stored. Incomplete staging data is never labeled or displayed as an official batch.

## Canonical tabular data model

Every source adapter produces an immutable imported snapshot and an editable `TabularDataset` containing:

- stable row identifiers independent of visible sorting;
- ordered column identifiers and displayed labels;
- exact normalized string values plus source display values;
- cell-level origin and validation state;
- source type, source location when applicable, import timestamp, and source hash;
- a monotonic edit revision used by validation and preview caches.

The processing engine consumes only `TabularDataset`; it does not branch on Excel, CSV, paste, or manual-entry behavior.

### Excel adapter

The existing `.xlsx` safety rules remain. Formulas are detected separately from cached display values. Missing or stale cached formula results block generation and tell the operator to recalculate and save the workbook in Excel. Merged cells intersecting the data area block import. Hidden rows and columns are reported before the operator chooses whether to include them.

### Delimited-text adapter

UTF-8, UTF-8 with BOM, UTF-16 with BOM, Windows-1251, and GB18030 are supported. Delimiter and encoding detection may propose a choice, but the import preview must display both and permit correction. Low-confidence or lossy decoding blocks import. Quoted delimiters and multiline fields follow Python CSV semantics. Inconsistent row widths are surfaced rather than silently padded or truncated.

### Paste and manual adapters

Clipboard input accepts tab/newline tables and quoted CSV text. A preview appears before rows replace or append to the active table. Manual entry supports keyboard navigation, multi-cell paste, row and column insertion/removal, undo/redo, and explicit column names.

## Local draft projects and recovery

Drafts use a local SQLite project file with schema versioning and transactional writes. The project stores the editable dataset, mappings, selected template path and hash, output configuration, language, acknowledgements, and last completed workflow step. It does not embed the source workbook or template.

Autosave occurs after a short debounce and before leaving a step. A successful transaction replaces the previous recoverable state; rotating local backups preserve the last three valid project revisions. A project whose referenced template changed must be re-inspected and revalidated before preview or generation.

Project files contain personal data and must be described as sensitive in the interface and guide. Staff choose their location. The application never copies a project to a shared support directory.

## Localization architecture

All user-facing text is referenced by stable translation keys and parameters. Version-controlled UTF-8 catalogs provide:

- `en` English fallback;
- `zh_CN` Simplified Chinese;
- `ru` Russian.

Catalogs cover navigation, controls, accessibility names, dialogs, validation, progress, recovery, import explanations, output summaries, and user actions. Core services return stable issue codes and structured parameters rather than preformatted English messages. The UI and reports format those issues through the selected catalog.

Switching language emits one application-level change event. Screens rebuild their visible labels without discarding the current project or edits. Placeholder names and recipient values are never translated.

Automated checks require every English key to exist in both translated catalogs, reject unused placeholder parameters, and reject untranslated keys rendered to the UI. Audit JSON and support logs retain stable language-neutral codes; the human-readable HTML summary uses the selected language and records its locale.

## Mapping and transformation safety

Mappings are immutable plans created from reviewed UI choices. Supported transformations are typed records, not expression strings:

- `ColumnValue(column_id)`
- `FixedValue(text)`
- `SequenceValue(start, step, width, prefix, suffix)`
- `SourceRowValue()`
- `FormattedDateValue(source, input_format, output_format)`
- `JoinValue(column_ids, separator)`

Validation evaluates every mapping against every row before preview or generation. Sequence values are deterministic from the stable dataset order selected for generation. Date parsing must be unambiguous and locale-independent internally. Mapping plans and parameters are included in the audit manifest without unnecessarily duplicating recipient values.

## Output transaction and combined PDF

The staged batch transaction remains all-or-nothing:

1. Revalidate the current project revision and source/template hashes.
2. Render and verify selected DOCX outputs.
3. Convert and verify selected individual PDFs through isolated Word instances.
4. If enabled, merge the verified PDFs in the selected order.
5. Reopen the merged PDF and verify its page count equals the sum of source PDF pages.
6. Write the localized summary, language-neutral manifest, and redacted support log.
7. Atomically publish the complete directory.

The merged PDF has a Windows-safe batch-derived name, SHA-256 hash, page count, and ordered source-row references in the manifest. Merge failure blocks publication. Individual PDFs may be staged temporarily when only a combined PDF was selected, but unpublished temporary inputs are removed after successful merge.

## Error handling and chaos cases

The product must handle without data loss or misleading success:

- damaged, renamed, moved, locked, or changed source/template files;
- duplicate or empty headers and inconsistent delimited rows;
- ambiguous delimiter or encoding detection;
- Excel formulas without reliable cached values;
- multiline, Unicode, right-to-left, Cyrillic, and CJK values;
- reserved Windows filenames, normalization collisions, and long paths;
- a destination becoming unavailable during generation;
- Word being absent, busy, displaying a dialog, rejecting a document, or crashing;
- disk exhaustion and permission changes;
- application close, power interruption, or process termination;
- a draft opened by a newer or unsupported schema version;
- combined-PDF corruption or page-count mismatch;
- translation-key or formatting-parameter defects.

Expected failures return stable codes, localized explanations, and specific recovery actions. Diagnostics exclude cell values, generated filenames, and document contents. Unexpected failures retain private staged files only in a clearly named incomplete directory when they are useful for local recovery.

## Visual system and accessibility

The interface uses a restrained professional palette, strong contrast, a single accent color, semantic success/warning/error colors, consistent spacing, and large primary actions. Status must never rely on color alone. Dense data remains in the grid; explanatory copy stays concise.

Every control has a translated accessible name, a visible keyboard focus state, and logical tab order. The complete workflow is operable without a mouse. Layouts must accommodate Russian expansion and Chinese typography at Windows text scaling up to 200% without clipping.

## Testing and release evidence

Implementation follows test-driven development. Required automated coverage includes:

- adapter contract tests shared by Excel, CSV, TSV, paste, and manual data;
- encoding, delimiter, multiline, inconsistent-width, formula, hidden-data, and merged-cell cases;
- grid editing, undo/redo, stable row identity, autosave, backup, and project migration tests;
- translation-catalog completeness, parameter agreement, live switching, and layout text coverage;
- mapping transformation and full-dataset validation tests;
- UI workflow tests in all three locales;
- merged-PDF order, page count, corruption, cancellation, and manifest tests;
- transactional failures at every generation phase;
- real Microsoft Word conversion tests on Windows;
- packaged EXE and installer smoke tests.

Release acceptance additionally requires visual inspection of every principal screen in all three languages at 100% and 200% scaling, keyboard-only completion of a representative workflow, and live batches from each data-source type. A 50-recipient mixed Unicode batch must produce verified individual files and a verified combined PDF.

## Version and compatibility

This architectural release is version 2.0.0. It targets 64-bit Windows with desktop Microsoft Word for PDF output. Version 1 project state does not exist, so no draft migration is required. Existing `.xlsx` and `.docx` inputs remain compatible. The current supported batch directory and manifest semantics are extended rather than replaced.

## Explicit exclusions

- Cloud storage, email delivery, online collaboration, accounts, and telemetry.
- Direct `.xls`, `.ods`, database, Google Sheets, or web API connections.
- Arbitrary formulas, macros, scripts, plugins, or user-executable transformations.
- Digital signing, legal approval, certificate distribution, or identity verification.
- Editing Word document layout inside the application.

These exclusions keep official-document generation deterministic, supportable, and fully offline.
