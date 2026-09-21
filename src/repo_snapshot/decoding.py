"""Deterministic text decoding with an explicit fallback and per-file notices."""

import codecs
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .errors import InputError

DEFAULT_FALLBACK_ENCODING = "cp1254"
_ALIASES = {"utf-16le-bom": "utf-16-le", "utf-16be-bom": "utf-16-be"}
_UNICODE_UNITS = frozenset(
    {"utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"}
)
_SURROGATES = re.compile(r"[\ud800-\udfff]")


@lru_cache(maxsize=128)
def _text_codec(name: str) -> str:
    selected = _ALIASES.get(name.lower(), name)
    encoding = codecs.lookup(selected).name
    if encoding.replace("_", "-") in {"unicode-escape", "raw-unicode-escape", "idna", "punycode"}:
        raise LookupError("A character encoding is required.")
    # Nonempty text rejects byte transforms; replacement support is required for
    # the recovery stage. Empty bytes alone bypass checks in several codecs.
    probe = "snapshot"
    if probe.encode(encoding).decode(encoding, errors="replace") != probe:
        raise LookupError("A round-tripping text encoding is required.")
    return encoding


@dataclass(frozen=True)
class DecodingWarning:
    path: str
    encoding: str
    replaced: bool


@dataclass
class DecodingContext:
    fallback_encoding: str = DEFAULT_FALLBACK_ENCODING
    warnings: dict[str, DecodingWarning] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        try:
            self.fallback_encoding = _text_codec(self.fallback_encoding)
        except (LookupError, UnicodeError, ValueError):
            raise InputError("Fallback encoding must name a supported text encoding.") from None

    def decode(
        self, data: bytes, relative: str, selected: str, *, unicode_hint: bool = False
    ) -> str:
        # A BOM or declared/detected UTF-16/32 layout is stronger evidence than a legacy
        # fallback: retain its code-unit boundaries even if a unit is truncated.
        try:
            preferred = _text_codec(selected)
        except (LookupError, UnicodeError, ValueError):
            preferred = None
        unicode_hint = unicode_hint or preferred in _UNICODE_UNITS
        candidates = (selected,) if unicode_hint else (selected, "utf-8", self.fallback_encoding)
        attempted: set[str] = set()
        replacement_encoding = preferred if unicode_hint and preferred else self.fallback_encoding
        for index, candidate in enumerate(candidates):
            try:
                encoding = _text_codec(candidate)
            except (LookupError, UnicodeError, ValueError):
                continue
            if encoding in attempted:
                continue
            attempted.add(encoding)
            try:
                text = data.decode(encoding, errors="strict")
            except UnicodeError:
                continue
            if _SURROGATES.search(text):
                # UTF-7 can return lone surrogates even in strict mode; such
                # text cannot be written to the UTF-8 snapshot.
                continue
            if index:
                self.warnings[relative] = DecodingWarning(relative, encoding, False)
            return text
        try:
            text = data.decode(replacement_encoding, errors="replace")
        except (UnicodeError, LookupError):
            # A few specialized codecs do not support replacement handling.
            replacement_encoding = "utf-8"
            text = data.decode(replacement_encoding, errors="replace")
        self.warnings[relative] = DecodingWarning(relative, replacement_encoding, True)
        return _SURROGATES.sub("\ufffd", text)
