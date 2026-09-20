# Certificate Automation

Certificate Automation is an offline Windows desktop application for generating official certificate batches from an Excel workbook and a Word template. It produces an editable DOCX and a print-ready PDF for every recipient, verifies the complete batch, and publishes nothing unless the entire run succeeds.

## Product guarantees

- Guided PySide6 interface for nontechnical staff.
- Flexible `{{PLACEHOLDER}}` fields matched to Excel columns or fixed values.
- Complete preflight validation before official generation.
- Formatting-safe replacement across Word paragraphs, split runs, tables, headers, footers, and text boxes.
- Microsoft Word PDF conversion for template fidelity.
- Bounded Word recovery without terminating Word processes owned by the user.
- Staged, all-or-nothing batch publication with no silent overwrites.
- SHA-256 audit manifest, offline HTML summary, and privacy-conscious support log.
- Clear incomplete-run diagnostics and recovery controls.
- No cloud service, account, telemetry, or runtime network requirement.

Microsoft Word is required for PDF output. The manifest records hashes and processing facts; it is not a digital signature or legal certification.

## Development setup

Python 3.12 or newer is required.

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
.\.venv-win\Scripts\pyinstaller --noconfirm --clean packaging\certificate-automation.spec
.\.venv-win\Scripts\python -m pytest tests\windows\test_packaged_application.py -v --exe dist\CertificateAutomation\CertificateAutomation.exe
```

If Inno Setup 6 is installed:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

The application files appear under `dist/CertificateAutomation/`; the installer appears under `dist/installer/`. Build artifacts are intentionally ignored by Git.

## Project layout

- `src/certificate_automation/` — tested application and processing engine.
- `tests/` — unit, integration, UI, failure, and Windows Word tests.
- `packaging/` — PyInstaller and Inno Setup definitions.
- `docs/user-guide.md` — offline operator guide.
- `examples/` — a ready-to-use sample workbook and Word certificate template.
- `docs/superpowers/` — approved design and implementation plan.

The earlier experimental script and sample files remain under `system/` only as development history; the supported product entry point is `certificate-automation`.
