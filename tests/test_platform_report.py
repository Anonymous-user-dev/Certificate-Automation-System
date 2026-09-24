from __future__ import annotations

from certificate_automation.platform_report import PlatformReport


def test_authoritative_output_rejects_unc_cloud_removable_and_unknown_volume(tmp_path):
    for facts in (
        {"filesystem": "NTFS", "fixed": True, "cloud": False, "unc": True},
        {"filesystem": "NTFS", "fixed": True, "cloud": True, "unc": False},
        {"filesystem": "NTFS", "fixed": False, "cloud": False, "unc": False},
        {"filesystem": "exFAT", "fixed": True, "cloud": False, "unc": False},
    ):
        assert not PlatformReport.from_facts(tmp_path, **facts).authoritative
    assert PlatformReport.from_facts(tmp_path, filesystem="NTFS", fixed=True, cloud=False, unc=False).authoritative


def test_platform_report_serializes_runtime_without_private_path(tmp_path):
    private = tmp_path / "Ana García" / "official"
    report = PlatformReport.from_facts(
        private, filesystem="NTFS", fixed=True, cloud=False, unc=False,
        application_version="3.0.0", python_version="3.14.0", qt_version="6.11.0",
        windows_release="11", windows_build="26100", word_version="16.0",
        converter_version="Word 16.0",
    )

    payload = report.to_json()

    assert payload["application_version"] == "3.0.0"
    assert payload["python_version"] == "3.14.0"
    assert payload["qt_version"] == "6.11.0"
    assert payload["windows_release"] == "11"
    assert payload["windows_build"] == "26100"
    assert payload["word_version"] == "16.0"
    assert payload["converter_version"] == "Word 16.0"
    assert payload["volume_kind"] == "fixed"
    assert str(private) not in str(payload)
