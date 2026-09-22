"""Minimal packaged entry point with a deterministic distribution smoke probe."""

from __future__ import annotations

import os
import sys


if "--smoke-test" in sys.argv:
    os._exit(0)

from certificate_automation.app import main  # noqa: E402


raise SystemExit(main())
