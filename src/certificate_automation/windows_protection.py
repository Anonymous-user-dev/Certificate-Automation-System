"""Narrow, injectable boundary for Windows user-bound byte protection."""

from __future__ import annotations

from typing import Protocol


class ProtectionError(RuntimeError):
    def __init__(self, code: str = "history.protection_unavailable") -> None:
        super().__init__(code)
        self.code = code


class ByteProtector(Protocol):
    def protect(self, value: bytes, *, purpose: str) -> bytes: ...

    def unprotect(self, value: bytes, *, purpose: str) -> bytes: ...


class DpapiProtector:
    """Protect a key for the current Windows user; no network or credentials."""

    def protect(self, value: bytes, *, purpose: str) -> bytes:
        try:
            import win32crypt

            return win32crypt.CryptProtectData(
                value, purpose, purpose.encode("utf-8"), None, None, 0
            )[1]
        except Exception:
            raise ProtectionError() from None

    def unprotect(self, value: bytes, *, purpose: str) -> bytes:
        try:
            import win32crypt

            return win32crypt.CryptUnprotectData(
                value, purpose.encode("utf-8"), None, None, 0
            )[1]
        except Exception:
            raise ProtectionError() from None
