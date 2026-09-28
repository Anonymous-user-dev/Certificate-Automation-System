from pathlib import Path

from test_signing_pipeline import ROOT, _native_path, _run_script


def _verify_payload(*arguments):
    script = ROOT / "packaging" / "verify-payload.ps1"
    assert script.is_file(), "Release flow has no installed payload verification"
    return _run_script(script, *arguments)


def test_payload_verification_rejects_changed_installed_application(tmp_path):
    bundle = tmp_path / "bundle"
    installed = tmp_path / "installed"
    bundle.mkdir()
    installed.mkdir()
    (bundle / "CertificateAutomation.exe").write_bytes(b"signed application")
    (installed / "CertificateAutomation.exe").write_bytes(b"unsigned application")

    result = _verify_payload(
        "-BundleRoot", _native_path(bundle),
        "-InstalledRoot", _native_path(installed),
    )

    assert result.returncode != 0
    assert "INSTALLED_PAYLOAD_HASH_MISMATCH" in result.stderr


def test_payload_verification_checks_all_bundle_files(tmp_path):
    bundle = tmp_path / "bundle"
    installed = tmp_path / "installed"
    bundle.mkdir()
    installed.mkdir()
    for root in (bundle, installed):
        (root / "CertificateAutomation.exe").write_bytes(b"application")
        (root / "_internal").mkdir()
    (bundle / "_internal" / "runtime.dll").write_bytes(b"runtime")

    result = _verify_payload(
        "-BundleRoot", _native_path(bundle),
        "-InstalledRoot", _native_path(installed),
    )

    assert result.returncode != 0
    assert "INSTALLED_PAYLOAD_MISSING" in result.stderr


def test_payload_verification_accepts_exact_unsigned_payload(tmp_path):
    bundle = tmp_path / "bundle"
    installed = tmp_path / "installed"
    for root in (bundle, installed):
        root.mkdir()
        (root / "CertificateAutomation.exe").write_bytes(b"application")
        (root / "data.txt").write_bytes(b"offline data")

    result = _verify_payload(
        "-BundleRoot", _native_path(bundle),
        "-InstalledRoot", _native_path(installed),
    )

    assert result.returncode == 0, result.stderr


def test_required_payload_signing_rejects_unsigned_bundle_before_install(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "CertificateAutomation.exe").write_bytes(b"unsigned")

    result = _verify_payload(
        "-BundleRoot", _native_path(bundle), "-RequireSigning",
        "-ExpectedThumbprint", "A" * 40,
    )

    assert result.returncode != 0
    assert "PAYLOAD_SIGNATURE_REQUIRED" in result.stderr


def test_release_verifier_rejects_installer_with_different_embedded_application(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    application = bundle / "CertificateAutomation.exe"
    pe = bytearray(128)
    pe[:2] = b"MZ"
    pe[60:64] = (64).to_bytes(4, "little")
    pe[64:70] = b"PE\0\0\x64\x86"
    application.write_bytes(pe + b'8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a longPathAware level="asInvoker"')
    for relative in (
        "certificate_automation/locales/en.json", "certificate_automation/locales/ru.json",
        "certificate_automation/locales/zh_CN.json", "examples/sample_recipients.csv",
        "examples/sample_students.xlsx", "examples/sample_certificate_template.docx",
    ):
        path = bundle / "_internal" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"offline")
    installer = tmp_path / "CertificateAutomation-Setup-3.0.0.exe"
    installer.write_bytes(b"Inno Setup Setup Data")
    harness = tmp_path / "verify-harness.ps1"
    harness.write_text(r'''param($Script, $Application, $Installer, $Metadata)
$ErrorActionPreference = 'Stop'
function Get-Item {
    param($LiteralPath)
    $item = Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath
    return [pscustomobject]@{FullName=$item.FullName; Length=$item.Length; VersionInfo=[pscustomobject]@{ProductVersion='3.0.0'}}
}
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $WindowStyle)
    $dirArgument = @($ArgumentList | Where-Object { $_ -like '/DIR=*' })
    if ($dirArgument.Count) {
        $destination = $dirArgument[0].Substring(5).Trim('"')
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $destination 'CertificateAutomation.exe'), 'unsigned embedded app')
        [IO.File]::WriteAllText((Join-Path $destination 'unins000.exe'), 'cleanup')
    }
    return [pscustomobject]@{ExitCode=0}
}
& $Script -Application $Application -Installer $Installer -OutputMetadata $Metadata
''', "utf-8")
    metadata = tmp_path / "metadata.json"

    result = _run_script(
        harness, _native_path(ROOT / "packaging" / "verify-release.ps1"),
        _native_path(application), _native_path(installer), _native_path(metadata),
    )

    assert "INSTALLED_PAYLOAD_HASH_MISMATCH" in result.stderr
    assert result.returncode != 0
    assert not metadata.exists()
