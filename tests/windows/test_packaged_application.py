from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


def test_packaged_application_starts_offline_and_exits_cleanly(request):
    executable_value = request.config.getoption("--exe")
    if not executable_value:
        pytest.skip("pass --exe to test a packaged application")
    executable = Path(executable_value)
    assert executable.is_file(), f"Packaged executable was not found: {executable}"

    result = subprocess.run(
        [str(executable), "--smoke-test"],
        timeout=30,
        check=False,
    )

    assert result.returncode == 0


def test_packaged_application_imports_qt_and_constructs_workspace(request):
    executable_value = request.config.getoption("--exe")
    if not executable_value:
        pytest.skip("pass --exe to test a packaged application")
    executable = Path(executable_value)
    assert executable.is_file(), f"Packaged executable was not found: {executable}"

    result = subprocess.run(
        [str(executable), "--ui-smoke-test"],
        timeout=30,
        check=False,
    )

    assert result.returncode == 0


def test_packaged_application_exposes_custom_fields_and_safe_pdf_defaults(request):
    executable_value = request.config.getoption("--exe")
    if not executable_value:
        pytest.skip("pass --exe to test a packaged application")
    executable = Path(executable_value)
    assert executable.is_file(), f"Packaged executable was not found: {executable}"

    result = subprocess.run(
        [str(executable), "--workflow-smoke-test"],
        timeout=30,
        check=False,
    )

    assert result.returncode == 0


def test_packaged_application_contains_all_locale_catalogs(request):
    executable_value = request.config.getoption("--exe")
    if not executable_value:
        pytest.skip("pass --exe to test a packaged application")
    packaged_root = Path(executable_value).parent
    candidates = (
        packaged_root / "_internal" / "certificate_automation" / "locales",
        packaged_root / "certificate_automation" / "locales",
    )
    locale_root = next((path for path in candidates if path.is_dir()), candidates[0])

    for locale in ("en", "zh_CN", "ru"):
        assert (locale_root / f"{locale}.json").is_file()


def test_packaged_application_contains_offline_examples(request):
    executable_value = request.config.getoption("--exe")
    if not executable_value:
        pytest.skip("pass --exe to test a packaged application")
    examples = Path(executable_value).parent / "_internal" / "examples"

    assert (examples / "sample_recipients.csv").is_file()
    assert (examples / "sample_certificate_template.docx").is_file()


def test_packaged_application_does_not_bundle_foreign_icu_runtime(request):
    executable_value = request.config.getoption("--exe")
    if not executable_value:
        pytest.skip("pass --exe to test a packaged application")
    internal = Path(executable_value).parent / "_internal"

    bundled_icu = tuple(
        path.name for path in internal.glob("*.dll") if path.name.lower().startswith("icu")
    )

    assert bundled_icu == ()
