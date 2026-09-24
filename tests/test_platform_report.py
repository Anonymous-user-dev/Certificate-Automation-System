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
