"""Microsoft Word PDF conversion behind a testable, ownership-safe adapter."""

from __future__ import annotations

from dataclasses import dataclass
import gc
from pathlib import Path
import platform
import time
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class WordAvailability:
    available: bool
    message: str
    code: str = "word.available"


Availability = WordAvailability


class PdfConverter(Protocol):
    def is_available(self) -> Availability: ...

    def convert(
        self,
        docx_path: Path,
        pdf_path: Path,
        on_attempt: Callable[[int, int], None] | None = None,
    ) -> None: ...


class TransientWordError(RuntimeError):
    """A Word/RPC failure that may succeed with a fresh private instance."""


class PermanentWordError(RuntimeError):
    """A document or environment failure that retrying cannot correct."""


class PdfConversionError(RuntimeError):
    """User-actionable failure returned by the conversion boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        user_action: str,
        attempts: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.user_action = user_action
        self.attempts = attempts


class WordGateway(Protocol):
    def availability(self) -> Availability: ...

    def convert_once(self, docx_path: Path, pdf_path: Path) -> None: ...


class WordPdfConverter:
    """Convert through isolated Word instances with bounded retries."""

    def __init__(
        self,
        gateway: WordGateway | None = None,
        *,
        max_attempts: int = 2,
        backoff_seconds: float = 0.5,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self._gateway = gateway or ComWordGateway()
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleeper = sleeper

    def is_available(self) -> Availability:
        return self._gateway.availability()

    def convert(
        self,
        docx_path: Path,
        pdf_path: Path,
        on_attempt: Callable[[int, int], None] | None = None,
    ) -> None:
        docx_path = Path(docx_path)
        pdf_path = Path(pdf_path)
        if not docx_path.is_file():
            raise PdfConversionError(
                f"Source Word document '{docx_path.name}' does not exist.",
                code="source_document_missing",
                user_action="Regenerate the Word document and try again.",
                attempts=0,
            )

        availability = self.is_available()
        if not availability.available:
            raise PdfConversionError(
                availability.message,
                code="word_not_available",
                user_action="Install or repair desktop Microsoft Word, then try again.",
                attempts=0,
            )

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self._max_attempts + 1):
            pdf_path.unlink(missing_ok=True)
            if on_attempt is not None:
                on_attempt(attempt, self._max_attempts)
            try:
                self._gateway.convert_once(docx_path.resolve(), pdf_path.resolve())
                if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
                    raise TransientWordError("Word did not create a PDF file.")
                return
            except PermanentWordError as error:
                pdf_path.unlink(missing_ok=True)
                raise PdfConversionError(
                    f"Microsoft Word rejected '{docx_path.name}': {error}",
                    code="word_rejected_document",
                    user_action=(
                        "Open the generated Word document manually, correct any Word "
                        "repair warning, and run validation again."
                    ),
                    attempts=attempt,
                ) from error
            except TransientWordError as error:
                pdf_path.unlink(missing_ok=True)
                if attempt == self._max_attempts:
                    raise PdfConversionError(
                        f"Microsoft Word could not convert '{docx_path.name}' after "
                        f"{attempt} attempts: {error}",
                        code="word_temporarily_unavailable",
                        user_action=(
                            "Close any Word dialog boxes, wait for Word to finish other "
                            "work, and try the batch again."
                        ),
                        attempts=attempt,
                    ) from error
                self._sleeper(self._backoff_seconds * attempt)
            except Exception as error:
                pdf_path.unlink(missing_ok=True)
                raise PdfConversionError(
                    f"Microsoft Word could not convert '{docx_path.name}'.",
                    code="word_conversion_failed",
                    user_action=(
                        "Confirm the document opens in Microsoft Word, then try again."
                    ),
                    attempts=attempt,
                ) from error


class ComWordGateway:
    """Own exactly one private Word process for the duration of one attempt."""

    _TRANSIENT_HRESULTS = {
        -2147418111,  # RPC_E_CALL_REJECTED
        -2147417846,  # RPC_E_SERVERCALL_RETRYLATER
        -2147023174,  # RPC server unavailable
        -2146959355,  # COM server execution failure
    }

    def availability(self) -> Availability:
        if platform.system() != "Windows":
            return WordAvailability(
                False,
                "PDF conversion requires the Windows desktop version of Microsoft Word.",
                "word.windows_required",
            )
        try:
            import pythoncom  # noqa: F401
            import winreg
            import win32com.client  # noqa: F401
        except ImportError:
            return WordAvailability(
                False,
                "The Microsoft Word automation component is not installed.",
                "word.component_missing",
            )
        try:
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                r"Word.Application\CLSID",
            ) as key:
                clsid, _ = winreg.QueryValueEx(key, None)
            if not str(clsid).strip():
                raise OSError("Word.Application has an empty CLSID registration.")
        except OSError:
            return WordAvailability(
                False,
                "Desktop Microsoft Word is not installed or its automation "
                "registration is damaged.",
                "word.not_available",
            )
        return WordAvailability(True, "Microsoft Word automation is available.")

    def convert_once(  # pragma: no cover - exercised by Windows Word integration
        self,
        docx_path: Path,
        pdf_path: Path,
    ) -> None:
        try:
            import pythoncom
            import pywintypes
            import win32com.client
        except ImportError as error:
            raise PermanentWordError(
                "The Microsoft Word automation component is unavailable."
            ) from error

        word = None
        document = None
        failure: Exception | None = None
        cleanup_failure: Exception | None = None
        initialized = False
        try:
            pythoncom.CoInitialize()
            initialized = True
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = 3
            word.Options.SaveNormalPrompt = False
            document = word.Documents.Open(
                str(docx_path),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                Visible=False,
                OpenAndRepair=False,
                NoEncodingDialog=True,
            )
            document.ExportAsFixedFormat(
                OutputFileName=str(pdf_path),
                ExportFormat=17,
                OpenAfterExport=False,
                OptimizeFor=0,
                Range=0,
                Item=0,
                IncludeDocProps=True,
                KeepIRM=True,
                CreateBookmarks=1,
                DocStructureTags=True,
                BitmapMissingFonts=True,
                UseISO19005_1=False,
            )
        except pywintypes.com_error as error:
            failure = self._classify_com_error(error)
        except Exception as error:
            failure = PermanentWordError(str(error) or type(error).__name__)
        finally:
            if document is not None:
                try:
                    document.Close(SaveChanges=0)
                except Exception as error:
                    cleanup_failure = error
                finally:
                    document = None
                    gc.collect()
            if word is not None:
                try:
                    word.Quit(SaveChanges=0)
                except Exception as error:
                    cleanup_failure = cleanup_failure or error
                finally:
                    word = None
                    gc.collect()
            if initialized:
                pythoncom.CoUninitialize()

        if failure is not None:
            raise failure
        if cleanup_failure is not None:
            raise TransientWordError(
                "The private Microsoft Word instance did not close cleanly."
            ) from cleanup_failure

    def _classify_com_error(self, error: Exception) -> Exception:
        hresult = getattr(error, "hresult", None)
        description = str(error)
        folded = description.casefold()
        if hresult in self._TRANSIENT_HRESULTS or any(
            phrase in folded
            for phrase in (
                "call was rejected",
                "retry later",
                "server is busy",
                "rpc server is unavailable",
            )
        ):
            return TransientWordError(description)
        return PermanentWordError(description)
