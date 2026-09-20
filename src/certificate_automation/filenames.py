"""Deterministic Windows-safe output filenames."""

from __future__ import annotations

from hashlib import sha256
import re
import unicodedata


MAX_STEM_LENGTH = 120
RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "clock$",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_CONTROL_OR_INVALID = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')


def safe_stem(value: str) -> str:
    """Return a stable filename stem accepted by Windows."""

    original = unicodedata.normalize("NFKC", str(value)).strip()
    stem = _CONTROL_OR_INVALID.sub("_", original)
    stem = re.sub(r"\s+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip(" ._")
    if not stem:
        stem = "certificate"

    base_name = stem.split(".", maxsplit=1)[0].casefold()
    if base_name in RESERVED_NAMES:
        stem = f"_{stem}"

    if len(stem) > MAX_STEM_LENGTH:
        digest = sha256(original.encode("utf-8")).hexdigest()[:8]
        prefix_length = MAX_STEM_LENGTH - len(digest) - 1
        stem = f"{stem[:prefix_length].rstrip(' ._')}-{digest}"
    return stem

