"""Conservative report for authoritative local publication destinations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import platform
import sys


def _application_version() -> str:
    try:
        return version("certificate-automation-system")
    except PackageNotFoundError:
        try:
            return version("certificate-automation")
        except PackageNotFoundError:
            return "unknown"


def _qt_version() -> str:
    try:
        from PySide6.QtCore import qVersion
        return qVersion()
    except ImportError:
        return "unavailable"


@dataclass(frozen=True, slots=True)
class PlatformReport:
    path: Path
    filesystem: str | None
    fixed: bool
    cloud: bool
    unc: bool
    evidence: str
    application_version: str = "unknown"
    python_version: str = "unknown"
    qt_version: str = "unknown"
    windows_release: str = "unsupported"
    windows_build: str = "unsupported"
    word_version: str | None = None
    converter_version: str | None = None

    @property
    def volume_kind(self) -> str:
        if self.unc:
            return "network"
        if self.fixed:
            return "fixed"
        return "unknown"

    @property
    def authoritative(self) -> bool:
        return self.filesystem == "NTFS" and self.fixed and not self.cloud and not self.unc

    def to_json(self) -> dict[str, object]:
        return {
            "filesystem": self.filesystem, "fixed": self.fixed,
            "cloud": self.cloud, "unc": self.unc, "evidence": self.evidence,
            "volume_kind": self.volume_kind,
            "application_version": self.application_version,
            "python_version": self.python_version,
            "qt_version": self.qt_version,
            "windows_release": self.windows_release,
            "windows_build": self.windows_build,
            "word_version": self.word_version,
            "converter_version": self.converter_version,
        }

    @classmethod
    def from_facts(
        cls, path: Path, *, filesystem: str | None, fixed: bool, cloud: bool, unc: bool,
        application_version: str | None = None, python_version: str | None = None,
        qt_version: str | None = None, windows_release: str | None = None,
        windows_build: str | None = None, word_version: str | None = None,
        converter_version: str | None = None,
    ) -> "PlatformReport":
        return cls(
            Path(path), filesystem, fixed, cloud, unc, "injected",
            application_version or _application_version(), python_version or sys.version.split()[0],
            qt_version or _qt_version(),
            windows_release or (platform.release() if os.name == "nt" else "unsupported"),
            windows_build or (platform.version() if os.name == "nt" else "unsupported"),
            word_version, converter_version,
        )

    @classmethod
    def inspect_volume(cls, path: Path) -> "PlatformReport":
        path = Path(path)
        if os.name != "nt":
            return replace(cls.from_facts(path, filesystem=None, fixed=False, cloud=False, unc=False),
                           evidence="unsupported_platform")
        import ctypes
        from ctypes import wintypes

        resolved = path.resolve()
        name = str(resolved)
        unc = name.startswith("\\\\")
        if unc:
            return replace(cls.from_facts(path, filesystem=None, fixed=False, cloud=False, unc=True),
                           evidence="windows_volume")
        root = resolved.anchor
        kernel = ctypes.windll.kernel32
        drive_type = kernel.GetDriveTypeW(wintypes.LPCWSTR(root))
        filesystem = ctypes.create_unicode_buffer(256)
        okay = kernel.GetVolumeInformationW(
            wintypes.LPCWSTR(root), None, 0, None, None, None, filesystem, len(filesystem)
        )
        cloud = False
        current = resolved
        while True:
            attributes = kernel.GetFileAttributesW(wintypes.LPCWSTR(str(current)))
            if attributes != 0xFFFFFFFF and attributes & (0x400 | 0x40000 | 0x400000):
                cloud = True
            if current == current.parent:
                break
            current = current.parent
        return replace(cls.from_facts(
            path, filesystem=filesystem.value if okay else None,
            fixed=drive_type == 3, cloud=cloud, unc=False,
        ), evidence="windows_volume")
