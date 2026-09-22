from __future__ import annotations

from pathlib import Path
import tomllib

from certificate_automation import __version__


ROOT = Path(__file__).parents[1]


def test_release_version_is_consistent_and_is_2_0_1():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    installer = (ROOT / "packaging" / "installer.iss").read_text("utf-8")

    assert __version__ == "2.0.1"
    assert project["project"]["version"] == __version__
    assert '#define AppVersion "2.0.1"' in installer


def test_locales_and_csv_example_are_declared_for_source_and_windows_packages():
    project_text = (ROOT / "pyproject.toml").read_text("utf-8")
    spec = (ROOT / "packaging" / "certificate-automation.spec").read_text("utf-8")
    installer = (ROOT / "packaging" / "installer.iss").read_text("utf-8")

    assert '"locales/*.json"' in project_text
    assert '"certificate_automation/locales"' in spec
    assert "sample_recipients.csv" in spec
    assert "sample_recipients.csv" in installer
    assert (ROOT / "examples" / "sample_recipients.csv").is_file()
