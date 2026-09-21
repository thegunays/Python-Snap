"""Best-effort, offline credential detection without rewriting source syntax.

Rules return character spans, never credential values or diagnostic excerpts.
Both redaction and final validation use the same detector registry. Add provider
formats to ``PROVIDER_RULES`` and syntax-aware rules to ``DETECTORS``. This is a
conservative heuristic scanner, not a parser for every programming language or
a guarantee that unknown/obfuscated credentials can be identified.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

REDACTED = "[REDACTED]"
Span = tuple[int, int]
Detector = Callable[[str], Iterator[Span]]


@dataclass(frozen=True)
class ProviderRule:
    """A recognizable credential format; optionally select only a value group."""

    name: str
    pattern: re.Pattern[str]
    group: int | str = 0


PROVIDER_RULES: tuple[ProviderRule, ...] = (
    ProviderRule("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ProviderRule("github-fine-grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b")),
    ProviderRule("gitlab", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,255}\b")),
    ProviderRule("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ProviderRule("google-api", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ProviderRule("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,255}\b")),
    ProviderRule("stripe-secret", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,255}\b")),
    ProviderRule("npm", re.compile(r"\bnpm_[A-Za-z0-9]{36,255}\b")),
    ProviderRule("pypi", re.compile(r"\bpypi-[A-Za-z0-9_-]{50,512}\b")),
    ProviderRule("openai", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,512}\b")),
    ProviderRule("sendgrid", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{32,}\b")),
    ProviderRule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
                                  r"\.[A-Za-z0-9_-]{16,}\b")),
)

_PLACEHOLDER = re.compile(
    r"(?:\[REDACTED\]|\#\{[^{}]*\}\#|\$\{\{[\s\S]*?\}\}|\{\{[\s\S]*?\}\}|"
    r"\$\{[^{}]*\}|\$\([^()]*\)|%[A-Za-z_][A-Za-z0-9_]*%|"
    r"<[A-Za-z_][A-Za-z0-9_ .-]*>|CHANGEME|CHANGE_ME|REPLACE_ME|REPLACE[-_ ]?THIS|"
    r"(?:YOUR|INSERT|REPLACE_WITH|ENTER)[-_ ][A-Za-z0-9_ -]+|TODO|TBD|\*{3,}|[xX]{3,}|\.\.\.)",
    re.IGNORECASE,
)
_NON_VALUES = frozenset({"", "null", "none", "nil", "true", "false", "undefined"})
_STRONG_SUFFIXES = (
    "password", "passwd", "passphrase", "apikey", "accesskey", "secretaccesskey",
    "accesstoken", "refreshtoken", "authtoken", "bearertoken", "clientsecret",
    "oauthsecret", "signingsecret", "signingkey", "jwtsecret", "jwtkey", "secretkey",
    "encryptionkey", "accountkey", "sharedaccesskey", "privatekey", "personalaccesstoken",
)
_STRONG_KEYS = frozenset({"pwd", "pat", "sas", "sastoken", "sig"})
_WEAK_KEYS = frozenset({"key", "secret", "token", "credential", "credentials"})
_ASSIGNMENT = re.compile(
    r"(?<![\w.-])(?P<quote>(?:\\?[\"'])?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]*"
    r"(?:[ \t]+(?:[Pp]assword|[Tt]oken|[Kk]ey|[Ss]ecret))?)(?P=quote)\s*"
    r"(?P<separator>[:=])\s*"
)
_TYPE_ANNOTATION = re.compile(
    r"(?:str|string|int|float|bool|boolean|bytes|object|Any|String|SecretStr)"
    r"(?:[ \t]*\|[ \t]*(?:None|undefined|null))?[ \t]*(?P<end>[=,);{\r\n]|$)"
)
_ATTRIBUTE = re.compile(r"(?P<key>[A-Za-z_:][\w:.-]*)\s*=\s*(?P<quote>[\"'])"
                        r"(?P<value>.*?)(?P=quote)", re.DOTALL)
_XML_TAG = re.compile(r"<[A-Za-z_][\w:.-]*\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.DOTALL)
_XML_ELEMENT = re.compile(r"<(?P<key>[A-Za-z_][\w:.-]*)\s*>"
                          r"(?P<value>[^<]*)</(?P=key)\s*>", re.DOTALL)
_XML_CDATA = re.compile(r"<(?P<key>[A-Za-z_][\w:.-]*)\s*>\s*<!\[CDATA\["
                       r"(?P<value>.*?)\]\]>\s*</(?P=key)\s*>", re.DOTALL)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?P<kind>(?:(?:RSA|DSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY)-----"
    r"[\s\S]*?(?:-----END (?P=kind)-----|\Z)"
)
_AUTH = re.compile(r"\b(?:Bearer|Basic)[ \t]+", re.IGNORECASE)
_URL_PASSWORD = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/@\"']+:(?P<value>[^\s/@\"']+)@"
)


def _placeholder(value: str) -> bool:
    stripped = value.strip()
    if stripped.lower() in _NON_VALUES or _PLACEHOLDER.fullmatch(stripped):
        return True
    # Multiline YAML/template values are placeholders only if every nonblank
    # line is itself a complete placeholder. One embedded expression does not
    # exempt an entire connection string or URL.
    lines = stripped.splitlines()
    return len(lines) > 1 and all(not line.strip() or _PLACEHOLDER.fullmatch(line.strip())
                                  for line in lines)


def _key_strength(key: str) -> int:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized in _STRONG_KEYS or normalized.endswith(_STRONG_SUFFIXES):
        return 2
    if normalized.endswith("pat") and ("devops" in normalized or "github" in normalized):
        return 2
    return 1 if normalized in _WEAK_KEYS else 0


def _sensitive(value: str, strength: int, *, quoted: bool = True) -> bool:
    if not strength or _placeholder(value):
        return False
    # Bare references and calls are code, not embedded credential values.
    if not quoted and (
        re.search(r"\b(?:os\.environ|process\.env|Environment\.|env\.|var\.|secrets\.)", value)
        or re.fullmatch(r"(?:self|this|user|config|settings|options|credentials)"
                        r"(?:\.[A-Za-z_]\w*)+", value)
        or re.search(r"[A-Za-z_]\w*\s*\(", value)
        or re.search(r"\s(?:\+|\|\||\?\?)\s", value)
        or value.startswith(("$", "!ref ", "!Ref ", "!Sub ", "!secret "))
    ):
        return False
    if strength == 2:
        return True
    # Generic names need value evidence, not just a substring such as 'token'.
    categories = sum((bool(re.search(r"[a-z]", value)), bool(re.search(r"[A-Z]", value)),
                      bool(re.search(r"[0-9]", value)), bool(re.search(r"[^\w\s]", value))))
    return len(value) >= 16 and categories >= 3 and not any(c.isspace() for c in value)


def _read_value(text: str, start: int) -> tuple[int, int, bool]:
    """Return the literal's interior span, leaving delimiters untouched."""
    if start >= len(text):
        return start, start, False
    if text.startswith(('\\"', "\\'"), start):
        delimiter = text[start:start + 2]
        closing_at = text.find(delimiter, start + 2)
        return start + 2, closing_at if closing_at != -1 else len(text), True
    quote = text[start]
    if quote in "\"'`":
        delimiter = quote * 3 if text.startswith(quote * 3, start) else quote
        content_start = start + len(delimiter)
        cursor = content_start
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
            elif text.startswith(delimiter, cursor):
                return content_start, cursor, True
            else:
                cursor += 1
        return content_start, len(text), True
    # A complete unquoted template can contain spaces or syntax delimiters.
    for opening, closing in (("${{", "}}"), ("{{", "}}"), ("#{", "}#"),
                             ("${", "}"), ("$(", ")"), ("<", ">")):
        if text.startswith(opening, start):
            closing_at = text.find(closing, start + len(opening))
            if closing_at != -1:
                return start, closing_at + len(closing), False
    if text.startswith(REDACTED, start):
        return start, start + len(REDACTED), False
    cursor = start
    while cursor < len(text):
        char = text[cursor]
        if char in "\r\n;,\"'`<>}]":
            break
        if char == "#" and (cursor == start or text[cursor - 1].isspace()):
            break
        if text.startswith(" //", cursor):
            break
        cursor += 1
    while cursor > start and text[cursor - 1].isspace():
        cursor -= 1
    return start, cursor, False


def _yaml_block(text: str, key_at: int, marker_at: int) -> Span | None:
    line_start = text.rfind("\n", 0, key_at) + 1
    indentation = len(text[line_start:key_at]) - len(text[line_start:key_at].lstrip())
    newline = text.find("\n", marker_at)
    if newline == -1:
        return None
    cursor = newline + 1
    first = end = None
    while cursor < len(text):
        newline = text.find("\n", cursor)
        line_end = newline if newline != -1 else len(text)
        line = text[cursor:line_end].rstrip("\r")
        stripped = line.lstrip(" \t")
        indent = len(line) - len(stripped)
        if stripped and indent <= indentation:
            break
        if stripped:
            if first is None:
                first = cursor + indent
            end = cursor + len(line.rstrip())
        cursor = line_end + 1
    return (first, end) if first is not None and end is not None else None


def _assignments(text: str) -> Iterator[Span]:
    for match in _ASSIGNMENT.finditer(text):
        strength = _key_strength(match["key"])
        if not strength:
            continue
        start = match.end()
        if match["separator"] == ":" and not match["quote"]:
            annotation = _TYPE_ANNOTATION.match(text, start)
            if annotation:
                if annotation["end"] != "=":
                    continue
                start = annotation.end()
                while start < len(text) and text[start] in " \t":
                    start += 1
        if start < len(text) and text[start] in "|>":
            span = _yaml_block(text, match.start(), start)
            if span and _sensitive(text[span[0]:span[1]], strength):
                yield span
            continue
        start, end, quoted = _read_value(text, start)
        if _sensitive(text[start:end], strength, quoted=quoted):
            yield start, end


def _xml(text: str) -> Iterator[Span]:
    for tag in _XML_TAG.finditer(text):
        attributes = list(_ATTRIBUTE.finditer(tag[0]))
        contextual_strength = max(
            (_key_strength(attr["value"]) for attr in attributes
             if attr["key"].lower() in {"key", "name"}), default=0
        )
        for attr in attributes:
            strength = _key_strength(attr["key"])
            if attr["key"].lower() == "value":
                strength = max(strength, contextual_strength)
            if _sensitive(attr["value"], strength):
                start, end = attr.span("value")
                yield tag.start() + start, tag.start() + end
    for pattern in (_XML_ELEMENT, _XML_CDATA):
        for element in pattern.finditer(text):
            value = element["value"]
            if _sensitive(value, _key_strength(element["key"])):
                start, end = element.span("value")
                yield (start + len(value) - len(value.lstrip()),
                       end - len(value) + len(value.rstrip()))


def _private_keys(text: str) -> Iterator[Span]:
    for match in _PRIVATE_KEY.finditer(text):
        yield match.span()


def _authorization(text: str) -> Iterator[Span]:
    for match in _AUTH.finditer(text):
        start, end, _ = _read_value(text, match.end())
        if _placeholder(text[start:end]):
            continue
        # Headers and explicitly quoted authorization literals carry clear
        # credential context. Ordinary prose about Bearer authentication does
        # not. Other token formats still have provider-specific detection.
        prefix = text[max(text.rfind("\n", 0, match.start()), 0):match.start()]
        contextual = bool(re.search(r"authorization\b", prefix, re.IGNORECASE))
        quoted = match.start() > 0 and text[match.start() - 1] in "\"'`"
        if not contextual and not quoted:
            continue
        # Whitespace terminates an ordinary bearer/basic token (templates were
        # considered above, before splitting their internal whitespace).
        token = text[start:end].split(maxsplit=1)
        if token and not _placeholder(token[0]):
            yield start, start + len(token[0])


def _url_credentials(text: str) -> Iterator[Span]:
    for match in _URL_PASSWORD.finditer(text):
        if not _placeholder(match["value"]):
            yield match.span("value")


def _providers(text: str) -> Iterator[Span]:
    for rule in PROVIDER_RULES:
        for match in rule.pattern.finditer(text):
            yield match.span(rule.group)


DETECTORS: tuple[Detector, ...] = (
    _private_keys, _providers, _assignments, _xml, _authorization, _url_credentials,
)


def _spans(text: str) -> list[Span]:
    spans = sorted(span for detector in DETECTORS for span in detector(text))
    merged: list[Span] = []
    for start, end in spans:
        if start >= end:
            continue
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def redact(text: str) -> tuple[str, int]:
    """Redact detected values, returning a new string and disjoint-span count."""
    spans = _spans(text)
    if not spans:
        return text, 0
    parts: list[str] = []
    end = 0
    for start, next_end in spans:
        parts.extend((text[end:start], REDACTED))
        end = next_end
    parts.append(text[end:])
    return "".join(parts), len(spans)


def has_secrets(text: str) -> bool:
    """Run the same rules independently; never return or report matched values."""
    return any(next(detector(text), None) is not None for detector in DETECTORS)
