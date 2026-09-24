"""Conservative report for authoritative local publication destinations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PlatformReport:
    path: Path
    filesystem: str | None
    fixed: bool
    cloud: bool
    unc: bool
    evidence: str

    @property
    def authoritative(self) -> bool:
        return self.filesystem == "NTFS" and self.fixed and not self.cloud and not self.unc

    def to_json(self) -> dict[str, object]:
        return {
            "filesystem": self.filesystem, "fixed": self.fixed,
            "cloud": self.cloud, "unc": self.unc, "evidence": self.evidence,
        }

    @classmethod
    def from_facts(cls, path: Path, *, filesystem: str | None, fixed: bool, cloud: bool, unc: bool) -> "PlatformReport":
        return cls(Path(path), filesystem, fixed, cloud, unc, "injected")

    @classmethod
    def inspect_volume(cls, path: Path) -> "PlatformReport":
        path = Path(path)
        if os.name != "nt":
            return cls(path, None, False, False, False, "unsupported_platform")
        import ctypes
        from ctypes import wintypes

        resolved = path.resolve()
        name = str(resolved)
        unc = name.startswith("\\\\")
        if unc:
            return cls(path, None, False, False, True, "windows_volume")
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
        return cls(path, filesystem.value if okay else None, drive_type == 3, cloud, False, "windows_volume")
