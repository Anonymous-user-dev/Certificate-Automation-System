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
    artifact = tmp_path / "fixture.exe"
    artifact.write_bytes(b"not-signed")

    result = _run_script(
        ROOT / "packaging" / "sign-release.ps1",
        "-RequireSigning",
        "-Input",
        _native_path(artifact),
    )

    assert result.returncode != 0
    assert "SIGNING_CERTIFICATE_REQUIRED" in result.stderr


def test_verify_release_records_unsigned_artifact_and_pending_machine_matrix(tmp_path):
    artifact = tmp_path / "fixture.exe"
    artifact.write_bytes(b"offline-release-fixture")
    metadata = tmp_path / "release-metadata.json"

    result = _run_script(
        ROOT / "packaging" / "verify-release.ps1",
        "-Input",
        _native_path(artifact),
        "-OutputMetadata",
        _native_path(metadata),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(metadata.read_text("utf-8-sig"))
    assert payload["signature_status"] == "unsigned"
    assert payload["publisher"] is None
    assert payload["artifacts"][0]["sha256"] == "677dfcc2fd869e58fc683bdabf3b0fb3585813cfd52ed0ea6460c7c05a6363d2"
    assert {row["state"] for row in payload["windows_matrix"]} == {"machine_verification_pending"}


def test_verification_requested_as_signed_rejects_unsigned_artifact(tmp_path):
    artifact = tmp_path / "fixture.exe"
    artifact.write_bytes(b"not-signed")

    result = _run_script(
        ROOT / "packaging" / "verify-release.ps1",
        "-RequireSigning",
        "-Input",
        _native_path(artifact),
    )

    assert result.returncode != 0
    assert "SIGNATURE_REQUIRED" in result.stderr
