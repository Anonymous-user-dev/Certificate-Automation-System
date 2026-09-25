from __future__ import annotations

import json
from pathlib import Path

from test_signing_pipeline import ROOT, _native_path, _run_script


def test_record_only_acceptance_captures_host_and_full_gate_inventory(tmp_path):
    installer = tmp_path / "CertificateAutomation-Setup-3.0.0.exe"
    installer.write_bytes(b"exact-installer")
    evidence_root = tmp_path / "acceptance"

    result = _run_script(
        ROOT / "scripts" / "windows-release-acceptance.ps1",
        "-Installer",
        _native_path(installer),
        "-OutputDirectory",
        _native_path(evidence_root),
        "-RecordOnly",
    )

    assert result.returncode == 0, result.stderr
    evidence_files = tuple(evidence_root.rglob("acceptance.json"))
    assert len(evidence_files) == 1
    payload = json.loads(evidence_files[0].read_text("utf-8-sig"))
    assert payload["installer"]["sha256"] == "11f2857f148cac364048f37e5334f3c17369848986e94f0cad273fe37546cc0a"
    assert payload["host"]["architecture"] == "x64"
    assert payload["target"]["os"] == payload["host"]["os"]
    assert payload["target"]["release"] == payload["host"]["display_version"]
    assert payload["host"]["display_version"]
    assert payload["host"]["build"].isdigit()
    assert payload["host"]["display_scale_measurement"] == "GetDpiForSystem"
    assert payload["mode"] == "record_only"
    expected = {
        "silent_clean_install",
        "responsive_launch",
        "all_input_families",
        "save_and_recover",
        "mixed_script_50_recipient_batch",
        "unicode_and_long_paths",
        "locked_file_recovery",
        "upgrade_from_2_1_1",
        "display_scale_100",
        "display_scale_150",
        "display_scale_200",
        "silent_uninstall",
    }
    assert {gate["id"] for gate in payload["tests"]} == expected
    assert {gate["status"] for gate in payload["tests"]} == {"not_run"}


def _write_scale_evidence(
    root: Path, scale: int, *, target_os: str = "Windows 11", host_build: str = "26100"
) -> None:
    functional = {
        "silent_clean_install", "responsive_launch", "all_input_families", "save_and_recover",
        "mixed_script_50_recipient_batch", "unicode_and_long_paths", "locked_file_recovery",
        "upgrade_from_2_1_1", "silent_uninstall",
    }
    tests = [{"id": gate, "status": "passed", "detail": None} for gate in sorted(functional)]
    tests.extend(
        {"id": f"display_scale_{candidate}", "status": "passed" if candidate == scale else "not_run", "detail": None}
        for candidate in (100, 150, 200)
    )
    payload = {
        "schema_version": 1,
        "evidence_id": f"Windows-11-24H2-build-26100-scale-{scale}",
        "mode": "execute",
        "target": {"os": target_os, "release": "24H2"},
        "host": {
            "os": "Windows 11", "display_version": "24H2", "build": host_build,
            "architecture": "x64", "display_scale_percent": scale,
            "display_scale_measurement": "GetDpiForSystem",
        },
        "installer": {"sha256": "a" * 64},
        "tests": tests,
        "overall_status": "passed",
    }
    destination = root / str(scale)
    destination.mkdir(parents=True)
    (destination / "acceptance.json").write_text(json.dumps(payload), "utf-8")


def test_matrix_validator_aggregates_three_measured_scale_runs(tmp_path):
    for scale in (100, 150, 200):
        _write_scale_evidence(tmp_path, scale)

    result = _run_script(
        ROOT / "packaging" / "validate-acceptance.ps1",
        "-AcceptanceRoot", _native_path(tmp_path),
        "-InstallerHash", "a" * 64,
    )

    assert result.returncode == 0, result.stderr
    matrix = json.loads(result.stdout)
    row = next(item for item in matrix if item["os"] == "Windows 11" and item["release"] == "24H2")
    assert row["state"] == "verified"
    assert row["verified_scales"] == [100, 150, 200]


def test_matrix_validator_rejects_caller_label_that_disagrees_with_measured_host(tmp_path):
    for scale in (100, 150, 200):
        _write_scale_evidence(tmp_path, scale, target_os="Windows 10")

    result = _run_script(
        ROOT / "packaging" / "validate-acceptance.ps1",
        "-AcceptanceRoot", _native_path(tmp_path),
        "-InstallerHash", "a" * 64,
    )

    assert result.returncode == 0, result.stderr
    matrix = json.loads(result.stdout)
    assert {item["state"] for item in matrix} == {"machine_verification_pending"}


def test_matrix_validator_rejects_non_measured_build_label(tmp_path):
    for scale in (100, 150, 200):
        _write_scale_evidence(tmp_path, scale, host_build="caller-supplied")

    result = _run_script(
        ROOT / "packaging" / "validate-acceptance.ps1",
        "-AcceptanceRoot", _native_path(tmp_path),
        "-InstallerHash", "a" * 64,
    )

    assert result.returncode == 0, result.stderr
    assert {item["state"] for item in json.loads(result.stdout)} == {"machine_verification_pending"}


def test_release_verifier_contract_checks_exact_bundle_internals():
    script = (ROOT / "packaging" / "verify-release.ps1").read_text("utf-8")

    for required in (
        "0x8664", "ProductVersion", "RELEASE_VERSION_INVALID",
        "Inno Setup Setup Data", "RELEASE_INSTALLER_FORMAT_INVALID",
        "8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a", "longPathAware",
        "certificate_automation\\locales\\zh_CN.json",
        "examples\\sample_certificate_template.docx", "OFFLINE_BUNDLE_INCOMPLETE",
    ):
        assert required in script


def test_acceptance_refuses_non_executable_installer(tmp_path):
    installer = tmp_path / "installer.txt"
    installer.write_text("wrong artifact", "utf-8")

    result = _run_script(
        ROOT / "scripts" / "windows-release-acceptance.ps1",
        "-Installer",
        _native_path(installer),
        "-OutputDirectory",
        _native_path(tmp_path / "acceptance"),
        "-RecordOnly",
    )

    assert result.returncode != 0
    assert "INSTALLER_MUST_BE_EXE" in result.stderr
