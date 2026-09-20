from pathlib import Path


ROOT = Path(SPECPATH).parent
SOURCE = ROOT / "src"

analysis = Analysis(
    [str(SOURCE / "certificate_automation" / "app.py")],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=[
        (str(ROOT / "docs" / "user-guide.md"), "docs"),
        (str(ROOT / "examples" / "sample_students.xlsx"), "examples"),
        (str(ROOT / "examples" / "sample_certificate_template.docx"), "examples"),
    ],
    hiddenimports=[
        "pythoncom",
        "pywintypes",
        "win32com",
        "win32com.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytest_cov", "pytestqt", "tests"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="CertificateAutomation",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CertificateAutomation",
)
