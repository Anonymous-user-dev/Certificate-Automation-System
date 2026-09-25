# Certificate Automation

Certificate Automation 3.0 is a fully offline Windows desktop application for generating official certificate batches from Excel, CSV, TSV, pasted, or manually entered tables and a Word template. It selects editable DOCX plus individual PDFs by default and can optionally create one combined print PDF. Nothing is published unless the complete selected batch verifies successfully.

## Product guarantees

- Guided PySide6 interface for nontechnical staff.
- Any field written as `{{PLACEHOLDER}}` in the Word template is detected automatically and can be matched without changing program code.
- Flexible fields matched to renamed or imported columns, fixed values, sequences, source rows, formatted dates, or joined columns.
- English, Simplified Chinese, and Russian interface translations.
- Complete preflight validation before official generation.
- Formatting-safe replacement across Word paragraphs, split runs, tables, headers, footers, and text boxes.
- Microsoft Word PDF conversion for template fidelity.
- Bounded Word recovery without terminating Word processes owned by the user.
- Staged, all-or-nothing batch publication with no silent overwrites.
- SHA-256 audit manifest, offline HTML summary, and privacy-conscious support log.
- Clear incomplete-run diagnostics and recovery controls.
- No cloud service, account, telemetry, or runtime network requirement.

Microsoft Word is required for PDF output. The manifest records hashes and processing facts; it is not a digital signature or legal certification.

## Supported recipient sources

| Source | Supported behavior |
|---|---|
| Excel `.xlsx` | Explicit worksheet selection; hidden rows/columns require an operator choice; merged data cells and missing formula caches are rejected |
| CSV / TSV / text | UTF-8, UTF-8 BOM, UTF-16 BOM, Windows-1251, and GB18030; ambiguous encoding or separator requires confirmation |
| Clipboard | Tab-separated tables or CSV with an import preview |
| Manual | Spreadsheet-style rows and columns with add, remove, rename, edit, and undo/redo controls |

Source files are copied into an internal snapshot and are never edited. Draft projects and previews may contain personal data: store drafts in an approved location and delete them according to institutional retention policy. Temporary previews use an isolated application-session folder and are removed on normal shutdown when Windows has released them.

## Development setup

Python 3.12 or 3.13 is required. CPython 3.12/3.13 x64 with PySide6 6.8.3 is the verified Windows release-build line.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not word_integration'
```

On Windows PowerShell:

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\python -m pip install -e ".[test,build]"
.\.venv-win\Scripts\python -m pytest tests\windows -m word_integration -v
.\.venv-win\Scripts\certificate-automation
```

## Build the offline Windows application

From the repository root in Windows PowerShell:

```powershell
.\.venv-win\Scripts\python -m pip install --require-hashes -r packaging\requirements-build.lock
.\.venv-win\Scripts\python -m PyInstaller --noconfirm --clean packaging\certificate-automation.spec
.\.venv-win\Scripts\python -m pytest tests\windows\test_packaged_application.py -v --exe dist\CertificateAutomation\CertificateAutomation.exe
```

If Inno Setup 6 is installed:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

The application files appear under `dist/CertificateAutomation/`; the installer appears under `dist/installer/`. Build artifacts are intentionally ignored by Git.

The application manifest declares Windows 10/11 compatibility, x64, per-monitor DPI awareness, UTF-8, long-path support, and ordinary-user (`asInvoker`) execution. The installer is per-user and requires no administrator elevation.

## Verify or sign a release

Every delivered executable and installer must be passed to the verifier. An unsigned build is allowed only when its metadata plainly says `unsigned`; asking for signing fails closed if a certificate, private key, SignTool, signature, or configured thumbprint is missing.

```powershell
packaging\verify-release.ps1 -Application dist\CertificateAutomation\CertificateAutomation.exe -Installer dist\installer\CertificateAutomation-Setup-3.0.0.exe

# Organization-controlled certificate; no certificate or secret is stored in this repository.
packaging\sign-release.ps1 -RequireSigning -CertificateThumbprint $env:CERTIFICATE_SIGNING_THUMBPRINT -TimestampUrl $env:CERTIFICATE_TIMESTAMP_URL -Application dist\CertificateAutomation\CertificateAutomation.exe -Installer dist\installer\CertificateAutomation-Setup-3.0.0.exe
```

Run `scripts\windows-release-acceptance.ps1` separately on clean Windows 10 22H2, Windows 11 24H2, and Windows 11 25H2 x64 machines at 100%, 150%, and 200% display scale. Until evidence for the exact installer SHA-256 exists, `release-metadata.json` records each unavailable row as `machine_verification_pending`; it never treats an untested machine as verified.

## Project layout

- `src/certificate_automation/` — tested application and processing engine.
- `tests/` — unit, integration, UI, failure, and Windows Word tests.
- `packaging/` — PyInstaller and Inno Setup definitions.
- `docs/user-guide.md` — offline operator guide.
- `examples/` — a ready-to-use sample workbook and Word certificate template.
- `docs/superpowers/` — approved design and implementation plan.

The earlier experimental script and sample files remain under `system/` only as development history; the supported product entry point is `certificate-automation`.
