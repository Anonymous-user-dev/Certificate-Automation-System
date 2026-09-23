# Certificate Automation — Offline User Guide

## Before you begin

You need a 64-bit Windows computer with the desktop version of Microsoft Word installed. The application works offline and does not upload certificates, names, templates, or audit information.

Keep the original Excel workbook and Word template in a controlled location. The application reads them but never modifies them.

The installation includes `examples/sample_students.xlsx`, `examples/sample_recipients.csv`, and `examples/sample_certificate_template.docx`. Copy them to a working folder before editing so the originals remain available for training and troubleshooting.

The same six steps are available in English, Simplified Chinese, and Russian. Change **Language / 语言 / Язык** at the top of the window; changing language never changes recipient data.

## Prepare recipient data

Use column names in the first row and one recipient on each following row. Every field used by the certificate must have a value for every recipient.

Example:

| Full Name | Award | Date | Certificate ID |
|---|---|---|---|
| Ana García | Excellence Award | 2026-09-20 | CERT-2026-001 |

Blank rows are ignored. Duplicate column names, duplicate mapped records, blank required values, unsafe output collisions, and excessively long values block generation.

Choose one source on **Recipient Data / 收件人数据 / Данные получателей**:

- **Excel**: select `.xlsx`, then choose the worksheet. If hidden rows or columns exist, the program asks whether they belong in this batch. Merged data cells and formulas without cached values are rejected rather than guessed.
- **CSV / TSV**: supported encodings are UTF-8, UTF-8 with BOM, UTF-16 with BOM, Windows-1251, and GB18030. The preview shows the encoding and separator. If detection is ambiguous, you must choose explicitly.
- **Paste a table**: in Excel or another table, select the column-heading row and all recipient rows, choose **Copy**, then choose **Paste a table** in this application. Review the preview before replacing the current table.
- **Create a table**: add, remove, search, sort, and edit rows and columns inside the application. Select a cell in a column and choose **Rename column** to give that column the exact meaning you need. Undo and redo include column renames.

Importing never silently changes an existing table: confirm the preview first. A rejected or cancelled import leaves current edits unchanged.

## Prepare the Word template

Place fields inside double braces:

```text
{{FULL_NAME}}
{{AWARD}}
{{DATE}}
{{CERTIFICATE_ID}}
```

Field names may contain letters, numbers, spaces, hyphens, and underscores. The application treats spaces, hyphens, underscores, and letter case as equivalent when suggesting Excel matches. For example, `{{FULL_NAME}}` automatically matches an Excel column named `Full Name`.

You do not need the program to know a field in advance. If a different approved template contains `{{EMPLOYEE_ID}}`, `{{COURSE_HOURS}}`, or another name, the application detects it and creates a matching card in Step 3 automatically. Add or rename a recipient-data column in Step 1, or choose a fixed value or another supported source in Step 3.

Fields are supported in normal paragraphs, tables, headers, footers, and Word text boxes. Do not split one placeholder across separate paragraphs. Keep the braces and field name together as one visible field, even if Word internally divides its formatting runs.

## The six-step workflow

1. **Recipient Data / 收件人数据 / Данные получателей** — import, paste, or type the table; inspect every row.
2. **Word Template / Word 模板 / Шаблон Word** — choose a `.docx`; review its SHA-256 hash and detected placeholders. Macro-enabled, protected, malformed, or ambiguous templates are rejected.
3. **Match Fields / 匹配字段 / Сопоставление полей** — for each detected `{{FIELD_NAME}}`, choose a data column, fixed value, number sequence, original row, formatted date, or joined columns. Only settings needed for the selected choice are shown. Continue is blocked while anything is unresolved.
4. **Review / 审核 / Проверка** — switch between recipients, inspect resolved values and issues, and optionally generate a temporary in-app PDF preview. Warnings must be consciously reviewed.
5. **Output Options / 输出选项 / Параметры вывода** — DOCX and one PDF per recipient are selected by default. Optionally select one combined PDF for bulk printing, then choose the destination and order. The page states the exact number of files planned. PDF controls are disabled with an explanation if Word is unavailable.
6. **Generate / 生成 / Создание** — start the verified batch, monitor progress, or request cancellation. Result links appear only after atomic publication.

## Output batch contents

A successful folder is named similarly to:

```text
Certificate Batch 2026-09-20 143000 a1b2c3d4/
```

Depending on the selected formats, it contains:

- one `*_certificate.docx` per recipient;
- one matching `*_certificate.pdf` per recipient;
- an optional combined PDF in the exact selected recipient order for easier bulk printing;
- `batch_summary.html`, which staff can open offline;
- `manifest.json`, containing source/output hashes, mappings, counts, timestamps, and source row numbers;
- `support.log`, containing operational facts without recipient values or output filenames.

The HTML summary, manifest, and support log are safety and audit records; they are not certificates. If you need print-ready certificates, keep **Individual PDF documents** selected. If you want one file to send to a printer, also select **One combined PDF for printing**. After generation, **Open combined PDF** is enabled only when that exact verified file exists.

### Date fields in simple terms

Choose **Formatted date** only when a recipient-data column contains dates that should be printed differently. **Date as written in your table** describes the source, such as `%Y-%m-%d` for `2026-09-22`. **Date as printed on the certificate** describes the result, such as `%d %B %Y` for `22 September 2026`. The common settings are already filled in; change them only when your table uses another unambiguous order.

The SHA-256 hashes help detect accidental file changes. They do not replace an institutional digital-signature or document-approval process.

## Errors, warnings, and recovery

An **error** blocks generation because correctness cannot be guaranteed. A **warning** identifies something worth reviewing but does not compromise the batch rules.

If the source table or Word template changes after review, the prior mapping, preview, or validation is invalidated. The program sends you back to the affected step instead of generating from stale assumptions. Existing files and output folders are never silently overwritten.

If Word is busy, the application starts a new private Word automation instance and retries a bounded number of times. It never terminates Word processes or documents that you opened yourself. If conversion still fails, close Word dialog boxes, confirm the generated DOCX opens normally, and retry the entire batch.

An interrupted failure may leave a hidden folder named `.certificate-incomplete-<batch-id>` in the selected destination. When that destination is selected again, the application displays recovery controls. You can open `diagnostic.json` for support or explicitly remove that exact incomplete folder. It is never presented as an official batch.

If you close the application during generation, it requests cancellation and waits until the current document reaches a safe boundary. No partial batch is published.

## Privacy and official-document handling

- Processing is local and offline.
- No telemetry, cloud account, web request, or runtime network connection is used.
- Draft project files and temporary previews can contain sensitive values; protect them like the source workbook and certificates.
- The support log excludes recipient values and output filenames.
- The manifest necessarily includes output filenames and source row numbers for traceability. Protect it with the same access controls as the certificates.
- Always inspect the preview and a representative sample of the final PDFs.
- Follow your institution's authorization, retention, signing, and distribution policies.

## When asking for technical support

Provide the application version, `support.log`, and—only if the run failed—`diagnostic.json`. The support log contains operational codes and counts but no recipient values or output filenames. Do not send the workbook, template, certificates, draft project, preview, or `manifest.json` unless your institution has approved sharing personal data.
