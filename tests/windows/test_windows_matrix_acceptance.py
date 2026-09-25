from __future__ import annotations

import json

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
