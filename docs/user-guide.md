# Certificate Automation — Offline User Guide

## Before you begin

You need a 64-bit Windows computer with the desktop version of Microsoft Word installed. The application works offline and does not upload certificates, names, templates, or audit information.

Keep the original Excel workbook and Word template in a controlled location. The application reads them but never modifies them.

The installation includes `examples/sample_students.xlsx` and `examples/sample_certificate_template.docx`. Copy them to a working folder before editing so the originals remain available for training and troubleshooting.

## Prepare the Excel workbook

Use one worksheet with column names in the first row and one recipient on each following row. Avoid merged cells in the data area. Every field used by the certificate must have a value for every recipient.

Example:

| Full Name | Award | Date | Certificate ID |
|---|---|---|---|
| Ana García | Excellence Award | 2026-09-20 | CERT-2026-001 |

Blank rows are ignored. Duplicate column names, duplicate mapped records, blank required values, unsafe output collisions, and excessively long values block generation.

## Prepare the Word template

Place fields inside double braces:

```text
{{FULL_NAME}}
{{AWARD}}
{{DATE}}
{{CERTIFICATE_ID}}
```

Field names may contain letters, numbers, spaces, hyphens, and underscores. The application treats spaces, hyphens, underscores, and letter case as equivalent when suggesting Excel matches. For example, `{{FULL_NAME}}` automatically matches an Excel column named `Full Name`.

Fields are supported in normal paragraphs, tables, headers, footers, and Word text boxes. Do not split one placeholder across separate paragraphs. Keep the braces and field name together as one visible field, even if Word internally divides its formatting runs.

## The six-step workflow

1. **Files** — Choose the `.xlsx` workbook, worksheet, `.docx` template, and output folder.
2. **Mapping** — Review every suggested match. Select another Excel column or enter a fixed value when required.
3. **Validation** — Correct every item marked `ERROR`. Warnings are displayed separately and do not silently become errors.
4. **Preview** — Generate and inspect one temporary PDF. A preview is not an official published batch.
5. **Generate** — Confirm generation. The application creates and verifies every DOCX and PDF in a private staging folder.
6. **Results** — A successful run displays the new timestamped batch folder. A failed or cancelled run never appears as a successful official batch.

## Output batch contents

A successful folder is named similarly to:

```text
Certificate Batch 2026-09-20 143000 a1b2c3d4/
```

It contains:

- one `*_certificate.docx` per recipient;
- one matching `*_certificate.pdf` per recipient;
- `batch_summary.html`, which staff can open offline;
- `manifest.json`, containing source/output hashes, mappings, counts, timestamps, and source row numbers;
- `support.log`, containing operational facts without recipient values or output filenames.

The SHA-256 hashes help detect accidental file changes. They do not replace an institutional digital-signature or document-approval process.

## Errors, warnings, and recovery

An **error** blocks generation because correctness cannot be guaranteed. A **warning** identifies something worth reviewing but does not compromise the batch rules.

If Word is busy, the application starts a new private Word automation instance and retries a bounded number of times. It never terminates Word processes or documents that you opened yourself. If conversion still fails, close Word dialog boxes, confirm the generated DOCX opens normally, and retry the entire batch.

An interrupted failure may leave a hidden folder named `.certificate-incomplete-<batch-id>` in the selected destination. When that destination is selected again, the application displays recovery controls. You can open `diagnostic.json` for support or explicitly remove that exact incomplete folder. It is never presented as an official batch.

If you close the application during generation, it requests cancellation and waits until the current document reaches a safe boundary. No partial batch is published.

## Privacy and official-document handling

- Processing is local and offline.
- No telemetry or cloud account is used.
- The support log excludes recipient values and output filenames.
- The manifest necessarily includes output filenames and source row numbers for traceability. Protect it with the same access controls as the certificates.
- Always inspect the preview and a representative sample of the final PDFs.
- Follow your institution's authorization, retention, signing, and distribution policies.

## When asking for technical support

Provide the application version, `support.log`, and—only if the run failed—`diagnostic.json`. Do not send the workbook, template, certificates, or `manifest.json` unless your institution has approved sharing personal data.
