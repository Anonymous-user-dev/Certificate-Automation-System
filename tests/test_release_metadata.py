from __future__ import annotations

from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET

from certificate_automation import __version__


ROOT = Path(__file__).parents[1]


def test_release_version_is_consistent_and_is_3_0_0():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    installer = (ROOT / "packaging" / "installer.iss").read_text("utf-8")

    assert __version__ == "3.0.0"
    assert project["project"]["version"] == __version__
    assert '#define AppVersion "3.0.0"' in installer


def test_windows_runtime_is_pinned_to_approved_python_and_qt_line():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))

    assert project["project"]["requires-python"] == ">=3.12,<3.14"
    assert "PySide6==6.8.3" in project["project"]["dependencies"]


def test_windows_manifest_declares_supported_runtime():
    root = ET.parse(ROOT / "packaging" / "windows-app.manifest").getroot()
    text = ET.tostring(root, encoding="unicode")

    assert "8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a" in text
    assert "longPathAware" in text and "true" in text
    assert 'level="asInvoker"' in text
    assert "PerMonitorV2" in text
    assert "UTF-8" in text


def test_windows_package_targets_x64_without_admin_install():
    spec = (ROOT / "packaging" / "certificate-automation.spec").read_text("utf-8")
    installer = (ROOT / "packaging" / "installer.iss").read_text("utf-8")

    assert 'target_arch="x86_64"' in spec
    assert "windows-app.manifest" in spec
    assert "windows-version.txt" in spec
    version_resource = (ROOT / "packaging" / "windows-version.txt").read_text("utf-8")
    assert "3, 0, 0, 0" in version_resource
    assert "ProductVersion', '3.0.0'" in version_resource
    assert "PrivilegesRequired=lowest" in installer
    assert "ArchitecturesAllowed=x64compatible" in installer


def test_windows_build_lock_is_hash_complete_for_runtime_and_builder():
    lock = (ROOT / "packaging" / "requirements-build.lock").read_text("utf-8")

    expected = ("lxml", "openpyxl", "pypdf", "python-docx", "pyside6", "pywin32", "pyinstaller")
    assert all(f"{package}==" in lock.lower() for package in expected)
    requirement_lines = [line for line in lock.splitlines() if "==" in line]
    assert requirement_lines
    assert lock.count("--hash=sha256:") >= len(requirement_lines)


def test_locales_and_csv_example_are_declared_for_source_and_windows_packages():
    project_text = (ROOT / "pyproject.toml").read_text("utf-8")
    spec = (ROOT / "packaging" / "certificate-automation.spec").read_text("utf-8")
    installer = (ROOT / "packaging" / "installer.iss").read_text("utf-8")

    assert '"locales/*.json"' in project_text
    assert '"certificate_automation/locales"' in spec
    assert "sample_recipients.csv" in spec
    assert "sample_recipients.csv" in installer
    assert (ROOT / "examples" / "sample_recipients.csv").is_file()
