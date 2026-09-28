# Optional PDF-Native Template Mode

**Status:** Approved
**Date:** 2026-09-27  
**Product:** Certificate Automation 3.x, fully offline Windows desktop application

## 1. Purpose

Add a Word-free PDF generation mode without removing or weakening the existing DOCX workflow. Operators may choose either:

- **PDF template — recommended:** place named fields on a fixed PDF background and generate PDFs directly inside the application.
- **Word template — compatibility:** keep the existing DOCX placeholder workflow and use Microsoft Word for authoritative PDF conversion when installed.

The selected mode is explicit in the interface, project file, approval summary, manifest, audit report, and diagnostics. The application never silently changes rendering engines.

## 2. Product guarantees

1. Runtime remains fully offline.
2. The original PDF or DOCX template is never modified.
3. PDF mode never starts Microsoft Word and works when Word is absent.
4. DOCX mode retains its current behavior and safety checks.
5. Generated PDF pages retain the source PDF page geometry and background bytes as faithfully as the PDF libraries permit.
6. Every placed field must be mapped and every mapped value must fit its approved box before publication.
7. Text is never silently truncated, wrapped, shrunk, substituted, or moved.
8. All outputs remain staged, verified, audited, revisioned, and published transactionally.

## 3. Operator workflow

### 3.1 Template choice

The template page accepts `.docx` and `.pdf` by file picker or drag and drop. It labels them plainly:

- **Use a PDF background (no Word required)**
- **Use a Word template**

The page explains that PDF mode provides fixed positioning, while Word mode preserves existing Word templates. Opening a saved project restores the chosen mode. Changing template type invalidates layout review, warning acknowledgements, approval, and generation readiness.

### 3.2 PDF template designer

For a PDF template, the template step opens a simple field-placement workspace:

- a page preview with page navigation;
- zoom controls that do not alter saved coordinates;
- an **Add field** button;
- draggable and resizable field boxes;
- a short field-name control such as `FULL_NAME`, `AWARD`, or `DATE`;
- font family, size, color, horizontal alignment, and single-line or multi-line choice;
- duplicate, rename, remove, undo, and redo actions;
- a sample-value preview using actual recipient data.

Coordinates are stored in PDF points relative to the page crop box, never in screen pixels. Each field records page index, rectangle, field name, font identity, font size, color, alignment, and line mode.

Field names use the same rules and mapping system as DOCX placeholders. The operator can create any valid name without changing application code.

### 3.3 Beginner-first disclosure

The normal path shows Add field, field name, position, font size, and alignment. Color, exact numeric coordinates, line spacing, and other expert controls remain under **Advanced field settings**. Nothing is removed; advanced controls do not dominate the first-time workflow.

### 3.4 Mapping and preview

Placed PDF fields become the template's placeholder set and enter the existing Match Fields step. Existing column, fixed value, date, sequence, source-row, join, and reusable-profile mappings continue to work.

Representative records are generated directly onto the PDF background. The operator must review the same longest/risk-selected records used by the current layout workflow before approval.

### 3.5 Output choices

For PDF templates:

- individual PDFs are available;
- one combined PDF and separator pages are available;
- DOCX output is unavailable and the interface explains why.

For Word templates, current DOCX, individual PDF, and combined PDF options remain unchanged.

## 4. Fonts and text safety

PDF mode ships with redistribution-safe fonts covering Latin, Cyrillic, and Simplified Chinese. The exact font files and hashes are recorded in the build and batch manifest. Generated PDFs embed the used font subset when technically supported.

The first release does not silently fall back to another font. If the selected font lacks a required character or cannot be embedded, generation stops with a localized, row-specific error. Future user-imported fonts require an explicit licence/embedding warning and are outside this first implementation.

Text fitting uses the real rendering metrics of the selected font. Before publication the renderer checks every value against its field rectangle:

- single-line text that exceeds width or height blocks generation;
- multi-line text may wrap only when that mode was explicitly selected;
- text exceeding the approved line count or rectangle blocks generation;
- the error identifies recipient and field without exposing private values in diagnostics.

The application may offer suggested font sizes during design, but it never changes an approved size during generation.

## 5. PDF template health

The PDF inspection service records template SHA-256, page count, media boxes, crop boxes, rotation, encryption state, interactive forms, existing signatures, annotations, and embedded-file indicators where detectable.

Blocking conditions:

- encrypted or password-protected template;
- unreadable or damaged page tree;
- zero pages or unsupported page geometry;
- field rectangles outside their page crop box;
- duplicate or invalid field names;
- missing/unembeddable glyphs;
- text overflow;
- a template hash change after layout approval;
- a generated page count or geometry mismatch.

Existing digital signatures are reported as a blocking condition because overlaying content produces a new document that cannot preserve the original signature's validity. Interactive forms, annotations, unusual rotation, transparency, or embedded files are clearly reported and require either conservative support with tests or rejection; they are never ignored silently.

## 6. Rendering architecture

Introduce a template-mode boundary rather than adding PDF conditionals throughout the workflow:

- `TemplateMode`: `docx` or `pdf_overlay`.
- `PdfTemplateInspection`: immutable PDF health and geometry facts.
- `PdfFieldLayout`: immutable, versioned field definitions tied to the template hash.
- `PdfOverlayRenderer`: produces one staged PDF from one record and an approved layout.
- Existing `PdfConverter` remains responsible only for DOCX-to-PDF conversion.
- `BatchGenerator` selects the renderer explicitly from the frozen approval snapshot.

The renderer creates a transparent text overlay for each page, merges it with the corresponding original page, writes to a new staging file, closes all handles, and then passes the result through the existing PDF verifier. The implementation reuses the current publication journal, output integrity, combined-PDF, history, recovery, and export services.

Project schema migration adds an optional template mode and PDF layout. Existing projects default to `docx`; opening or saving them must not change their behavior. Newer unsupported project schemas remain read-only.

## 7. Approval, audit, and recovery

The frozen approval includes:

- template mode and template hash;
- PDF layout schema and digest;
- exact field rectangles and formatting;
- font identities and hashes;
- representative previews reviewed;
- page count and geometry;
- renderer identity and version;
- requested individual/combined PDF counts.

Any change to the template, field placement, mapping, font, or output settings invalidates approval. The manifest and HTML report identify `PdfOverlayRenderer`; they never claim Microsoft Word performed the rendering.

Partial renderings remain inside app-owned staging or recovery folders. No official-looking final folder is published unless every requested PDF, combined PDF, manifest, report, and journal entry verifies.

## 8. Error handling

Errors use stable localized codes and actionable messages. Examples include:

- field outside page;
- text does not fit;
- missing glyph;
- template changed;
- signed or encrypted template unsupported;
- output PDF unreadable;
- output page geometry changed.

The UI opens the exact field and representative recipient needing repair. Retrying never overwrites an existing official revision.

## 9. Testing and acceptance

### 9.1 Automated tests

- coordinate conversion across zoom, crop boxes, and page rotation;
- add, rename, remove, undo, redo, save, and restore field layouts;
- all existing mapping types in PDF mode;
- Latin, Cyrillic, and Simplified Chinese font coverage;
- deterministic fit/overflow and multi-line limits;
- encrypted, signed, malformed, and multi-page template handling;
- template-hash and layout-digest invalidation;
- individual and combined PDF page count/geometry verification;
- transactional rollback and recovery after renderer failures;
- complete EN/RU/zh_CN catalog parity and widget rendering;
- legacy project migration and unchanged DOCX workflow;
- packaged application operation with Microsoft Word absent.

### 9.2 Golden acceptance set

Maintain reviewed PDF fixtures containing portrait, landscape, cropped, rotated, multi-page, Latin, Cyrillic, and Chinese certificates. Compare page geometry, extracted text, font embedding, field bounds, and rendered-page images within documented tolerances.

### 9.3 Windows acceptance

Test the exact installer on supported Windows 10 and Windows 11 machines at 100%, 150%, and 200% display scaling. PDF generation must pass with Word absent. DOCX conversion continues to be tested separately with supported desktop Word installed.

## 10. Packaging and licensing

Only libraries and fonts with redistribution-compatible licences may ship. Their licence files, versions, and hashes are included in the installer and release metadata. No runtime download, telemetry, activation, or cloud conversion is permitted.

The installer remains per-user where possible. Added PDF libraries and fonts must be scanned and included in exact installed-payload verification.

## 11. Delivery sequence

1. Versioned PDF inspection and field-layout domain model.
2. PDF overlay renderer with embedded multilingual fonts and strict fit checks.
3. PDF designer with beginner-first controls and project persistence.
4. Workflow, approval, audit, batch, combined-PDF, recovery, and localization integration.
5. Golden PDF tests, Windows package tests without Word, installer verification, and documentation.

The existing Word mode remains operational throughout development. PDF mode is not exposed as production-ready until its complete safety and packaged acceptance gates pass.
