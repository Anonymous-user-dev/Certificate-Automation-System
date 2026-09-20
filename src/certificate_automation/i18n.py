"""Offline, parameter-safe translation catalogs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from string import Formatter


SUPPORTED_LOCALES = ("en", "zh_CN", "ru")
DEFAULT_LOCALE = "en"


class CatalogError(ValueError):
    """A translation catalog is incomplete or cannot format a message safely."""

    def __init__(self, code: str, *, key: str | None = None) -> None:
        super().__init__(code if key is None else f"{code}: {key}")
        self.code = code
        self.key = key


def _catalog_path(package_root: Path, locale: str) -> Path:
    return Path(package_root) / "locales" / f"{locale}.json"


def _load_messages(package_root: Path, locale: str) -> dict[str, str]:
    path = _catalog_path(package_root, locale)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError("i18n.catalog_unreadable", key=locale) from error
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise CatalogError("i18n.catalog_invalid", key=locale)
    return payload


def _parameter_names(template: str) -> frozenset[str]:
    return frozenset(
        name
        for _, name, _, _ in Formatter().parse(template)
        if name is not None and name != ""
    )


@dataclass(frozen=True, slots=True)
class TranslationCatalog:
    """One selected catalog paired with the canonical English fallback."""

    locale: str
    _messages: Mapping[str, str]
    _fallback: Mapping[str, str]

    @classmethod
    def load(
        cls,
        package_root: Path,
        locale: str,
        *,
        fallback: Mapping[str, str] | None = None,
    ) -> "TranslationCatalog":
        selected = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
        english = dict(fallback or _load_messages(package_root, DEFAULT_LOCALE))
        messages = english if selected == DEFAULT_LOCALE else _load_messages(
            package_root, selected
        )
        return cls(selected, messages, english)

    def text(self, key: str, **parameters: object) -> str:
        template = self._messages.get(key, self._fallback.get(key))
        if template is None:
            raise CatalogError("i18n.unknown_key", key=key)
        expected = _parameter_names(template)
        supplied = frozenset(parameters)
        if supplied != expected:
            code = (
                "i18n.missing_parameter"
                if expected - supplied
                else "i18n.unexpected_parameter"
            )
            raise CatalogError(code, key=key)
        try:
            return template.format_map(parameters)
        except (KeyError, ValueError, TypeError) as error:
            raise CatalogError("i18n.format_failed", key=key) from error


class CatalogSet:
    """Own the active offline locale and notify UI subscribers of changes."""

    def __init__(self, package_root: Path, locale: str = DEFAULT_LOCALE) -> None:
        self._package_root = Path(package_root)
        self._fallback = _load_messages(self._package_root, DEFAULT_LOCALE)
        self._catalog = TranslationCatalog.load(
            self._package_root,
            locale,
            fallback=self._fallback,
        )
        self._subscribers: list[Callable[[str], None]] = []

    @classmethod
    def load(cls, package_root: Path, locale: str = DEFAULT_LOCALE) -> "CatalogSet":
        return cls(package_root, locale)

    @property
    def locale(self) -> str:
        return self._catalog.locale

    @property
    def changed(self) -> tuple[Callable[[str], None], ...]:
        return tuple(self._subscribers)

    def subscribe(self, callback: Callable[[str], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def set_locale(self, locale: str) -> None:
        selected = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
        if selected == self.locale:
            return
        self._catalog = TranslationCatalog.load(
            self._package_root,
            selected,
            fallback=self._fallback,
        )
        for callback in tuple(self._subscribers):
            callback(selected)

    def text(self, key: str, **parameters: object) -> str:
        return self._catalog.text(key, **parameters)


def validate_catalogs(package_root: Path) -> tuple[str, ...]:
    """Return deterministic structural defects across all shipped catalogs."""

    errors: list[str] = []
    catalogs: dict[str, dict[str, str]] = {}
    for locale in SUPPORTED_LOCALES:
        try:
            catalogs[locale] = _load_messages(package_root, locale)
        except CatalogError as error:
            errors.append(str(error))
    if DEFAULT_LOCALE not in catalogs:
        return tuple(errors)

    english = catalogs[DEFAULT_LOCALE]
    english_keys = set(english)
    for locale in SUPPORTED_LOCALES:
        messages = catalogs.get(locale)
        if messages is None:
            continue
        missing = sorted(english_keys - set(messages))
        extra = sorted(set(messages) - english_keys)
        errors.extend(f"{locale}: missing key {key}" for key in missing)
        errors.extend(f"{locale}: extra key {key}" for key in extra)
        for key in sorted(english_keys & set(messages)):
            expected = _parameter_names(english[key])
            actual = _parameter_names(messages[key])
            if actual != expected:
                errors.append(
                    f"{locale}: parameter mismatch for {key}: "
                    f"expected {sorted(expected)}, found {sorted(actual)}"
                )
    return tuple(errors)


def package_root() -> Path:
    """Return the installed package directory containing locale data."""

    return Path(__file__).resolve().parent
