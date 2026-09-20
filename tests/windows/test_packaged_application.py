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
