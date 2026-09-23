"""Open a verified local artifact in its registered desktop application."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_local_path(path: Path) -> bool:
    """Use Qt first, then the Windows file association if Qt cannot open it."""

    target = Path(path)
    try:
        if not (target.is_file() or target.is_dir()):
            return False
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False

    try:
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
            return True
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            os.startfile(str(resolved))
            return True
        except (AttributeError, OSError):
            pass
    return False
