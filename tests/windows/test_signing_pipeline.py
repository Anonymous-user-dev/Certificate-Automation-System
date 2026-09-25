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
