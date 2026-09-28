from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[2]


def _powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        pytest.skip("PowerShell is required for Windows release-script tests")
    return executable


def _native_path(path: Path) -> str:
    if sys.platform != "win32" and shutil.which("wslpath") and _powershell().lower().endswith(".exe"):
        return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
    return str(path)


def _run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            _native_path(script),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_signing_requested_without_certificate_fails_closed(tmp_path):
    application = tmp_path / "CertificateAutomation.exe"
    installer = tmp_path / "CertificateAutomation-Setup-3.0.0.exe"
    application.write_bytes(b"not-signed")
    installer.write_bytes(b"not-signed")

    result = _run_script(
        ROOT / "packaging" / "sign-release.ps1",
        "-RequireSigning",
        "-Application", _native_path(application),
        "-Installer", _native_path(installer),
    )

    assert result.returncode != 0
    assert "SIGNING_CERTIFICATE_REQUIRED" in result.stderr


def test_verify_release_requires_exact_application_and_installer_names(tmp_path):
    application = tmp_path / "wrong.exe"
    installer = tmp_path / "CertificateAutomation-Setup-3.0.0.exe"
    application.write_bytes(b"not-an-application")
    installer.write_bytes(b"not-an-installer")

    result = _run_script(
        ROOT / "packaging" / "verify-release.ps1",
        "-Application",
        _native_path(application),
        "-Installer",
        _native_path(installer),
    )

    assert result.returncode != 0
    assert "RELEASE_APPLICATION_NAME_INVALID" in result.stderr


def test_verification_requested_as_signed_requires_expected_thumbprint(tmp_path):
    application = tmp_path / "CertificateAutomation.exe"
    installer = tmp_path / "CertificateAutomation-Setup-3.0.0.exe"
    application.write_bytes(b"not-signed")
    installer.write_bytes(b"not-signed")

    result = _run_script(
        ROOT / "packaging" / "verify-release.ps1",
        "-RequireSigning",
        "-Application",
        _native_path(application),
        "-Installer",
        _native_path(installer),
    )

    assert result.returncode != 0
    assert "SIGNING_EXPECTED_THUMBPRINT_REQUIRED" in result.stderr


def test_signing_pipeline_builds_installer_only_after_signed_bundle_verifies(tmp_path):
    # Signing tools and certificate storage are external Windows dependencies.
    # The real pipeline runs; the compiler embeds the bytes it receives.
    script_root = tmp_path / "packaging"
    script_root.mkdir()
    for name in ("sign-release.ps1", "verify-payload.ps1"):
        source = ROOT / "packaging" / name
        if source.exists():
            shutil.copyfile(source, script_root / name)
    (script_root / "installer.iss").write_text("fixture", "utf-8")
    (script_root / "verify-release.ps1").write_text(
        'param($Application, $Installer, $OutputMetadata, $AcceptanceRoot, '
        '$ExpectedThumbprint, [switch]$RequireSigning)\n'
        'if ([IO.File]::ReadAllText($Installer) -ne "signed:application") { throw "unsigned embedded application" }\n'
        '[IO.File]::WriteAllText($OutputMetadata, "verified")\n', "utf-8"
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    application = bundle / "CertificateAutomation.exe"
    application.write_text("application", "utf-8")
    installer = tmp_path / "CertificateAutomation-Setup-3.0.0.exe"
    metadata = tmp_path / "metadata.json"
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        r'''param($Script, $Application, $Installer, $Metadata)
$ErrorActionPreference = 'Stop'
function Get-ChildItem {
    param($LiteralPath, $Filter, [switch]$File, [switch]$Recurse)
    if ($LiteralPath -like 'Cert:*') { return [pscustomobject]@{HasPrivateKey=$true} }
    Microsoft.PowerShell.Management\Get-ChildItem @PSBoundParameters
}
function Get-Command { param($Name, $ErrorAction); if ($Name -eq 'signtool.exe') { return [pscustomobject]@{Source='TestSignTool'} }; Microsoft.PowerShell.Core\Get-Command $Name }
function TestSignTool {
    $path = $args[-1]
    if ($args[0] -eq 'sign' -and $path -eq $Application) { [IO.File]::WriteAllText($path, 'signed:application') }
    $global:LASTEXITCODE = 0
}
function Get-AuthenticodeSignature {
    param($LiteralPath)
    $status = if ([IO.File]::ReadAllText($LiteralPath) -eq 'signed:application') { 'Valid' } else { 'NotSigned' }
    [pscustomobject]@{Status=$status; SignerCertificate=[pscustomobject]@{Thumbprint=('A'*40)}}
}
function TestCompiler {
    if ([IO.File]::ReadAllText($Application) -ne 'signed:application') { throw 'compiler received unsigned bundle' }
    [IO.File]::WriteAllText($Installer, [IO.File]::ReadAllText($Application))
    $global:LASTEXITCODE = 0
}
& $Script -Application $Application -Installer $Installer -InstallerCompiler TestCompiler -CertificateThumbprint ('A'*40) -RequireSigning -OutputMetadata $Metadata
''', "utf-8"
    )

    result = _run_script(
        harness, _native_path(script_root / "sign-release.ps1"),
        _native_path(application), _native_path(installer), _native_path(metadata),
    )

    assert result.returncode == 0 and not result.stderr, result.stderr
    assert installer.read_text("utf-8") == "signed:application"
    assert metadata.read_text("utf-8") == "verified"
