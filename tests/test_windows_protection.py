from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from certificate_automation.windows_protection import DpapiProtector, ProtectionError


def test_dpapi_round_trip_uses_purpose_as_entropy(monkeypatch):
    calls = []

    def protect(value, description, entropy, *_rest):
        calls.append(("protect", value, description, entropy))
        return description, b"sealed:" + value

    def unprotect(value, entropy, *_rest):
        calls.append(("unprotect", value, entropy))
        return "ignored", value.removeprefix(b"sealed:")

    monkeypatch.setitem(sys.modules, "win32crypt", SimpleNamespace(
        CryptProtectData=protect, CryptUnprotectData=unprotect,
    ))
    protector = DpapiProtector()
    assert protector.unprotect(protector.protect(b"secret", purpose="history-key"), purpose="history-key") == b"secret"
    assert calls == [
        ("protect", b"secret", "history-key", b"history-key"),
        ("unprotect", b"sealed:secret", b"history-key"),
    ]


def test_dpapi_failure_has_stable_code_and_no_secret(monkeypatch):
    def broken(*_args):
        raise RuntimeError("secret key leaked in original failure")

    monkeypatch.setitem(sys.modules, "win32crypt", SimpleNamespace(
        CryptProtectData=broken, CryptUnprotectData=broken,
    ))
    with pytest.raises(ProtectionError) as caught:
        DpapiProtector().unprotect(b"secret", purpose="history-key")
    assert caught.value.code == "history.protection_unavailable"
    assert "secret" not in str(caught.value)
