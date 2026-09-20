from __future__ import annotations

from collections import deque
from types import ModuleType
import sys

import pytest

from certificate_automation.word import (
    Availability,
    ComWordGateway,
    PdfConversionError,
    PermanentWordError,
    TransientWordError,
    WordPdfConverter,
)


SUCCESS = object()


class FakeWordGateway:
    def __init__(self, outcomes):
        self.outcomes = deque(outcomes)
        self.started_instances = 0
        self.quit_calls = 0

    def availability(self):
        return Availability(True, "Microsoft Word is available.")

    def convert_once(self, docx_path, pdf_path):
        self.started_instances += 1
        try:
            outcome = self.outcomes.popleft()
            if callable(outcome):
                outcome(pdf_path)
            elif isinstance(outcome, Exception):
                raise outcome
            else:
                assert outcome is SUCCESS
                pdf_path.write_bytes(b"%PDF-fake")
        finally:
            self.quit_calls += 1


def _source(tmp_path):
    path = tmp_path / "a.docx"
    path.write_bytes(b"docx")
    return path


def test_transient_failure_restarts_owned_word_and_retries(tmp_path):
    gateway = FakeWordGateway([TransientWordError("busy"), SUCCESS])
    converter = WordPdfConverter(
        gateway=gateway,
        max_attempts=2,
        sleeper=lambda _: None,
    )

    converter.convert(_source(tmp_path), tmp_path / "a.pdf")

    assert gateway.started_instances == 2
    assert gateway.quit_calls == 2


def test_permanent_failure_is_not_retried(tmp_path):
    gateway = FakeWordGateway([PermanentWordError("invalid document")])

    with pytest.raises(PdfConversionError) as error:
        WordPdfConverter(gateway=gateway).convert(
            _source(tmp_path),
            tmp_path / "a.pdf",
        )

    assert error.value.code == "word_rejected_document"
    assert error.value.attempts == 1
    assert gateway.started_instances == 1
    assert gateway.quit_calls == 1


def test_failed_attempt_removes_partial_pdf_before_retry(tmp_path):
    destination = tmp_path / "a.pdf"

    def partial_failure(pdf_path):
        pdf_path.write_bytes(b"partial")
        raise TransientWordError("busy")

    def successful_retry(pdf_path):
        assert not pdf_path.exists()
        pdf_path.write_bytes(b"%PDF-complete")

    gateway = FakeWordGateway([partial_failure, successful_retry])

    WordPdfConverter(
        gateway=gateway,
        max_attempts=2,
        sleeper=lambda _: None,
    ).convert(_source(tmp_path), destination)

    assert destination.read_bytes() == b"%PDF-complete"


def test_exhausted_transient_failures_report_attempt_count(tmp_path):
    gateway = FakeWordGateway(
        [TransientWordError("busy"), TransientWordError("still busy")]
    )

    with pytest.raises(PdfConversionError) as error:
        WordPdfConverter(
            gateway=gateway,
            max_attempts=2,
            sleeper=lambda _: None,
        ).convert(_source(tmp_path), tmp_path / "a.pdf")

    assert error.value.code == "word_temporarily_unavailable"
    assert error.value.attempts == 2
    assert "Close any Word dialog" in error.value.user_action


def test_attempt_callback_reports_each_bounded_attempt(tmp_path):
    attempts = []
    gateway = FakeWordGateway([TransientWordError("busy"), SUCCESS])

    WordPdfConverter(
        gateway=gateway,
        max_attempts=2,
        sleeper=lambda _: None,
    ).convert(
        _source(tmp_path),
        tmp_path / "a.pdf",
        on_attempt=lambda current, maximum: attempts.append((current, maximum)),
    )

    assert attempts == [(1, 2), (2, 2)]


def test_missing_source_is_rejected_without_starting_word(tmp_path):
    gateway = FakeWordGateway([SUCCESS])

    with pytest.raises(PdfConversionError) as error:
        WordPdfConverter(gateway=gateway).convert(
            tmp_path / "missing.docx",
            tmp_path / "a.pdf",
        )

    assert error.value.code == "source_document_missing"
    assert gateway.started_instances == 0


def test_gateway_availability_is_exposed():
    gateway = FakeWordGateway([SUCCESS])

    assert WordPdfConverter(gateway=gateway).is_available().available is True


def test_gateway_reports_when_word_com_registration_is_missing(monkeypatch):
    pythoncom = ModuleType("pythoncom")
    win32com = ModuleType("win32com")
    win32com.client = ModuleType("win32com.client")
    winreg = ModuleType("winreg")
    winreg.HKEY_CLASSES_ROOT = object()

    def missing_word(*_args):
        raise FileNotFoundError("class not registered")

    winreg.OpenKey = missing_word
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", win32com.client)
    monkeypatch.setitem(sys.modules, "winreg", winreg)
    monkeypatch.setattr("certificate_automation.word.platform.system", lambda: "Windows")

    availability = ComWordGateway().availability()

    assert availability.available is False
    assert "not installed" in availability.message
