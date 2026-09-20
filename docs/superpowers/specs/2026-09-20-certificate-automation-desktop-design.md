# Certificate Automation Desktop Application Design

## Purpose

Build a fully offline Windows desktop application for nontechnical staff who need to issue batches of official certificates from an Excel workbook and a Word template. The application must reduce manual work while treating correctness, traceability, template fidelity, and failure recovery as first-class requirements.

## Product Scope

The application will:

- provide a PySide6 desktop interface with file and folder pickers;
- import recipient data from `.xlsx` workbooks;
- discover placeholders in `.docx` templates;
- automatically map normalized Excel columns to placeholders and allow staff to correct mappings;
- validate the complete batch before publishing any official document;
- generate an editable DOCX and print-ready PDF for every recipient;
- use installed Microsoft Word for highest-fidelity PDF conversion;
- verify generated files and reject incomplete batches;
- publish successful runs into new timestamped batch folders without overwriting earlier work;
- produce a human-readable summary and a machine-readable audit manifest;
- run without internet access.

The first release is a single-user Windows application. It will not include accounts, cloud storage, online collaboration, or a server.

## User Workflow

1. The user selects an Excel workbook, Word template, and destination folder.
2. The application reads workbook headers and discovers template placeholders.
3. It automatically maps exact normalized matches, then displays dropdowns for unmatched or ambiguous fields.
4. The user runs preflight validation. The application reports errors in plain language with source row or template location where possible.
5. The application generates a non-published preview from a selected record.
6. The user confirms the reviewed batch.
7. The application generates DOCX and PDF files in a private staging directory.
8. It reopens and verifies every generated artifact, writes the audit records, then publishes the complete batch atomically.
9. The results page shows the batch location, counts, warnings, and any recovery instructions.

## Architecture

The application will separate the interface from independently testable services:

- `workbook`: workbook loading, header normalization, row extraction, and input diagnostics;
- `template`: placeholder discovery and safe DOCX replacement across paragraphs, tables, headers, footers, and supported drawing/text content;
- `mapping`: automatic and user-selected column-to-placeholder mappings;
- `validation`: workbook, mapping, value, template, environment, filename, and output preflight checks;
- `generation`: per-recipient DOCX creation in a staging workspace;
- `conversion`: Microsoft Word automation behind an interface that supports deterministic test doubles;
- `verification`: output count, readability, placeholder, filename, and PDF checks;
- `batch`: transaction orchestration, retry policy, rollback, atomic publication, and progress events;
- `audit`: structured manifest, checksums, summary, and support log;
- `ui`: the PySide6 guided workflow and background workers.

The core domain must not import PySide6 or Word automation directly. This keeps business rules fast to test and prevents the interface from containing document-processing logic.

## Flexible Placeholders and Mapping

Template placeholders use the form `{{FIELD_NAME}}`. Excel headers and placeholders are normalized by trimming whitespace, case-folding, and treating spaces, hyphens, and underscores as equivalent for automatic matching.

Automatic matching is a convenience, never an assumption. The mapping screen shows every discovered placeholder and the selected workbook column. Every placeholder must be mapped or explicitly marked with an allowed fixed value before generation. Multiple placeholders may map to one column. Unknown placeholders, duplicate normalized headers, ambiguous matches, and templates without placeholders block generation with an explanation.

The application will support fields such as `{{FULL_NAME}}`, `{{AWARD}}`, `{{DATE}}`, `{{COURSE}}`, `{{CERTIFICATE_ID}}`, and future user-defined fields without code changes.

## Validation and Safety

Preflight validation must complete before any official outputs are created. It includes:

- file existence, extension, readability, and corruption checks;
- workbook sheet selection and header integrity;
- empty required values and fully blank rows;
- duplicate normalized records and duplicate output filenames;
- values that are unsafe for filenames or unreasonably long for documents;
- Excel dates, text dates, Unicode names, and supported scalar value types;
- placeholder discovery, complete mappings, and unsupported template constructs;
- destination write access, available disk space, and source/output path conflicts;
- installed and automatable Microsoft Word;
- predicted output counts and collision-free batch naming.

Warnings may be acknowledged only when they do not threaten correctness. Errors always block generation.

## Transactional Generation

Each run receives a unique batch identifier. All work occurs under a private staging directory:

1. copy the source template into the staging context;
2. create each DOCX without modifying the original;
3. verify replacement completeness and DOCX readability;
4. convert DOCX files to PDF through Microsoft Word;
5. verify PDF existence, signature, nonzero page count, and expected artifact count;
6. write the audit manifest and human-readable batch summary;
7. rename or move the completed staging batch to its final timestamped destination.

If any required step fails, no final batch is published. Temporary artifacts are retained only when useful for diagnosis and are clearly marked as incomplete; otherwise they are removed. Existing output batches are never silently overwritten.

## Word Conversion and Recovery

Microsoft Word COM automation is the primary and required fidelity path. Conversion runs outside the UI thread and uses bounded retries for transient failures. Recovery may close the application-owned Word instance, start a clean instance, and retry the affected conversion. It must never close Word documents or processes that the user owns.

If retrying cannot safely finish the batch, generation stops. The user receives a concise explanation and correction steps; the detailed log records the failing file, operation, exception category, retry history, and environment details. The application never represents a DOCX-only partial batch as a successful result.

## Auditability

Every published batch contains:

- the generated DOCX and PDF files;
- a human-readable `batch_summary.html` or equivalent offline report;
- a structured `manifest.json` with application version, batch identifier, timestamps, source filenames and SHA-256 hashes, selected worksheet, normalized mappings, recipient source rows, output filenames and hashes, counts, warnings, and final status;
- a support log that excludes unnecessary personal data where possible.

The manifest provides traceability but is not presented as a cryptographic signature or legal certification.

## User Interface

The PySide6 application uses a guided sequence:

1. **Files** — select workbook, template, worksheet, and destination.
2. **Mapping** — review detected placeholders and column mappings.
3. **Validation** — show grouped errors and warnings with actionable language.
4. **Preview** — generate and open a temporary sample for review.
5. **Generate** — show recipient-level progress with safe cancellation boundaries.
6. **Results** — show success status, batch location, audit summary, or recovery instructions.

Long operations run in background workers. Navigation and generation controls are disabled when their use would create inconsistent state. Closing the application during generation prompts the user and leaves either a verified published batch or a clearly incomplete staging record.

## Testing Strategy

Fast automated tests cover normalization, mappings, validation, filename planning, placeholder replacement, manifests, transaction state, retries, rollback, and error presentation. Fixtures cover split Word runs, tables, nested tables, headers, footers, Unicode, duplicate names, corrupt inputs, invalid dates, locked paths, and simulated conversion failures.

Integration tests create and reopen real XLSX and DOCX fixtures. Windows-only tests exercise Word COM conversion and verify resulting PDFs. PySide6 tests cover the primary workflow, disabled states, cancellation, progress, and plain-language error rendering.

Release verification includes a clean Windows environment with Microsoft Word installed, packaged application startup, offline operation, a representative 50-recipient batch, intentional failure cases, and hash/count validation of published output.

## Packaging and Delivery

The application will target supported 64-bit Windows systems with Microsoft Word installed. PyInstaller will produce a distributable application, with installer packaging added after the executable is verified. Runtime dependencies, sample workbook, sample template, and an offline user guide will be included. The build and application must not require network access at runtime.

## Version-Control Workflow

Existing user work will be preserved. Implementation will proceed in small vertical increments. After every one or two completed features, the relevant tests will be run; only verified changes will be committed and pushed to the configured GitHub remote. Generated certificates, temporary staging data, logs, build artifacts, and local environments will not be committed.

## Success Criteria

The product is complete when a nontechnical user can install or launch it on Windows, select a valid workbook and template, review flexible mappings, preview the result, and produce a verified 50-recipient DOCX/PDF batch without using a terminal. Invalid or interrupted runs must not publish a misleading partial batch, and failures must provide clear next actions and sufficient diagnostic detail for support.
