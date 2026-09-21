"""Read-only membership, conservative artifact policy, and flexible source decoding.

Git only supplies tracked paths and encoding attributes. No checkout, filter,
hook, submodule, or remote operation is performed. All content comes from guarded
reads of current working-tree files.
"""

import codecs
import fnmatch
import hashlib
import os
import re
import shlex
import stat
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .decoding import DecodingContext
from .errors import InventoryError


@dataclass(frozen=True)
class Inventory:
    paths: tuple[str, ...]
    excluded_count: int
    mode: str
    encodings: dict[str, str]


@dataclass(frozen=True)
class SourceText:
    text: str
    source_digest: bytes


_ARTIFACT_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".vs",
        ".idea",
        "bin",
        "obj",
        "debug",
        "release",
        "testresults",
        "coverage",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        ".next",
        ".nuxt",
        ".cache",
        ".gradle",
        "htmlcov",
        "output",
        ".terraform",
    }
)
_BINARY_SUFFIXES = frozenset(
    {
        ".dll",
        ".exe",
        ".pdb",
        ".so",
        ".dylib",
        ".class",
        ".jar",
        ".war",
        ".ear",
        ".zip",
        ".7z",
        ".rar",
        ".gz",
        ".bz2",
        ".xz",
        ".tar",
        ".tgz",
        ".zst",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".tiff",
        ".avif",
        ".pdf",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".webm",
        ".avi",
        ".mov",
        ".flac",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".pyc",
        ".pyo",
        ".o",
        ".a",
        ".lib",
        ".wasm",
        ".nupkg",
        ".snupkg",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".psd",
        ".icns",
    }
)
_SOURCE_SUFFIXES = frozenset(
    {
        ".cs",
        ".csproj",
        ".sln",
        ".slnx",
        ".fs",
        ".fsproj",
        ".vb",
        ".vbproj",
        ".java",
        ".kt",
        ".kts",
        ".go",
        ".rs",
        ".py",
        ".rb",
        ".php",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".m",
        ".swift",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".sql",
        ".graphql",
        ".gql",
        ".proto",
        ".json",
        ".jsonc",
        ".xml",
        ".config",
        ".ini",
        ".properties",
        ".toml",
        ".yml",
        ".yaml",
        ".tf",
        ".tfvars",
        ".hcl",
        ".bicep",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".md",
        ".txt",
        ".rst",
        ".adoc",
        ".props",
        ".targets",
        ".lock",
        ".sum",
        ".mod",
        ".gradle",
        ".cmake",
        ".mk",
        ".service",
        ".timer",
        ".conf",
        ".rules",
        ".rego",
        ".ipynb",
        ".r",
        ".rmd",
        ".ex",
        ".exs",
        ".erl",
        ".clj",
        ".lua",
    }
)
_SOURCE_NAMES = frozenset(
    {
        "dockerfile",
        "containerfile",
        "makefile",
        "gnumakefile",
        "jenkinsfile",
        "procfile",
        "gemfile",
        "rakefile",
        "license",
        "licence",
        "readme",
        "changelog",
        "authors",
        "codeowners",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".dockerignore",
        ".env",
        ".npmrc",
        ".yarnrc",
        ".gitmodules",
    }
)
_OS_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_BINARY_MAGICS = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"%PDF-",
    b"PK\x03\x04",
    b"\x7fELF",
    b"SQLite format 3\0",
    b"\x1f\x8b",
    b"\0asm",
    b"\xca\xfe\xba\xbe",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
)


def _ordered(paths: set[str] | list[str]) -> tuple[str, ...]:
    return tuple(sorted(paths, key=lambda path: ("/" in path, path)))


def _validate_relative(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != relative
        or (os.name == "nt" and "\\" in relative)
        or any(unicodedata.category(char) in {"Cc", "Cs", "Zl", "Zp"} for char in relative)
    ):
        raise InventoryError("A repository filename cannot be represented safely in a snapshot.")
    if os.name == "nt" and re.match(r"^[A-Za-z]:", relative):
        raise InventoryError("A repository filename cannot be represented safely in a snapshot.")
    return path.parts


def _maintained(relative: str) -> bool:
    path = PurePosixPath(relative)
    name = path.name.lower()
    return (
        path.suffix.lower() in _SOURCE_SUFFIXES
        or name in _SOURCE_NAMES
        or name.startswith(("dockerfile.", "containerfile.", ".env."))
    )


def _artifact(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        any(part.lower() in _ARTIFACT_DIRS for part in parts[:-1])
        or parts[-1].lower() in _OS_FILES
        or parts[-1].endswith(("~", ".swp", ".swo"))
    )


def _is_link(path: Path, info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or (hasattr(path, "is_junction") and path.is_junction())


def _checked_path(root: Path, relative: str) -> tuple[Path, os.stat_result] | None:
    """Check every component without ever intentionally following links."""
    parts = _validate_relative(relative)
    current = root
    try:
        root_info = root.lstat()
        if _is_link(root, root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise InventoryError("The repository root must be a real directory.")
        for index, part in enumerate(parts):
            current = current / part
            info = current.lstat()
            if _is_link(current, info):
                return None
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise InventoryError("A repository source path changed or is not a directory.")
        if not stat.S_ISREG(info.st_mode):
            raise InventoryError("A source file has been replaced by a non-regular file.")
        return current, info
    except OSError:
        raise InventoryError(
            "A repository source file is missing or cannot be read safely."
        ) from None


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_bytes(root: Path, relative: str, *, classify_binary: bool = False) -> bytes | None:
    checked = _checked_path(root, relative)
    if checked is None:
        return None
    path, initial = checked
    handles: list[int] = []
    try:
        if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
            parent_fd = os.open(root, flags)
            handles.append(parent_fd)
            parts = _validate_relative(relative)
            for part in parts[:-1]:
                parent_fd = os.open(part, flags, dir_fd=parent_fd)
                handles.append(parent_fd)
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        else:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or _fingerprint(before) != _fingerprint(initial):
                raise InventoryError("A repository source file changed while being read.")
            data: bytes | None
            if classify_binary:
                prefix = stream.read(8192)
                lfs_header = b"version https://git-lfs.github.com/spec/v1"
                possible_lfs = prefix.startswith((lfs_header + b"\n", lfs_header + b"\r\n"))
                known_binary_suffix = PurePosixPath(relative).suffix.lower() in _BINARY_SUFFIXES
                if prefix.startswith(_BINARY_MAGICS) or (known_binary_suffix and not possible_lfs):
                    data = None
                else:
                    # Candidate pointers must be validated against the complete file;
                    # legitimate source is never truncated to the classification prefix.
                    data = prefix + stream.read()
            else:
                data = stream.read()
            after = os.fstat(stream.fileno())
        final = _checked_path(root, relative)
        if (
            final is None
            or _fingerprint(before) != _fingerprint(after)
            or _fingerprint(after) != _fingerprint(final[1])
        ):
            raise InventoryError("A repository source file changed while being read.")
        return data
    except OSError:
        raise InventoryError("A repository source file cannot be read safely.") from None
    finally:
        for descriptor in reversed(handles):
            os.close(descriptor)


def _git_directory(root: Path) -> Path | None:
    """Accept only root metadata whose own/common directory stays in the boundary."""
    marker = root / ".git"
    try:
        marker_info = marker.lstat()
        if _is_link(marker, marker_info):
            return None
        if stat.S_ISDIR(marker_info.st_mode):
            directory = marker
        elif stat.S_ISREG(marker_info.st_mode):
            value = marker.read_text(encoding="utf-8").strip()
            if not value.startswith("gitdir: "):
                return None
            directory = root / value[8:]
        else:
            return None
        directory = directory.resolve(strict=True)
        directory.relative_to(root.resolve(strict=True))
        _check_git_metadata(root, directory)
        common = directory / "commondir"
        if common.exists():
            shared = (directory / common.read_text(encoding="utf-8").strip()).resolve(strict=True)
            try:
                shared.relative_to(root.resolve(strict=True))
            except ValueError:
                raise InventoryError(
                    "Shared Git metadata lies outside the repository boundary."
                ) from None
            _check_git_metadata(root, shared)
        return directory if directory.is_dir() else None
    except (OSError, ValueError, UnicodeError):
        return None


def _check_git_metadata(root: Path, directory: Path) -> None:
    """Reject linked metadata and config includes before asking Git to read them."""
    boundary = root.resolve(strict=True)
    for name in (
        "HEAD",
        "index",
        "config",
        "config.worktree",
        "commondir",
        "packed-refs",
        "shallow",
        "objects",
        "refs",
        "info",
    ):
        target = directory / name
        if not os.path.lexists(target):
            continue
        try:
            if _is_link(target, target.lstat()):
                raise InventoryError("Linked Git metadata cannot be used within a safe boundary.")
        except OSError:
            raise InventoryError("Git metadata cannot be read safely.") from None
        if name not in {"config", "config.worktree"}:
            continue
        relative = target.relative_to(boundary).as_posix()
        config = _read_bytes(boundary, relative)
        if config is None:
            raise InventoryError("Git configuration cannot be read safely.")
        if re.search(rb"(?im)^\s*\[\s*include(?:if)?(?:[\s\].])", config):
            raise InventoryError(
                "Git configuration includes are unsupported for boundary-safe snapshotting."
            )


def _git(
    root: Path, directory: Path, *args: str, data: bytes | None = None, probe_root: bool = False
):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_CEILING_DIRECTORIES": str(root),
        }
    )
    command = [
        "git",
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "core.attributesFile=" + os.devnull,
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.quotePath=false",
    ]
    if not probe_root:
        command.extend(("--git-dir=" + str(directory), "--work-tree=" + str(root)))
    command.extend(args)
    try:
        return subprocess.run(
            command, cwd=root, env=env, input=data, capture_output=True, check=False, timeout=60
        )
    except FileNotFoundError:
        return None
    except OSError:
        raise InventoryError("Git repository membership could not be read safely.") from None
    except subprocess.TimeoutExpired:
        raise InventoryError(
            "Git inventory exceeded its time limit; no snapshot was published."
        ) from None


def _nested(root: Path, relative: str) -> bool:
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        if os.path.lexists(current / ".git"):
            return True
    return False


def is_git_root(root: Path) -> bool:
    """Check whether the candidate is the actual root of its own Git working tree."""
    root = root.absolute()
    try:
        info = root.lstat()
        if _is_link(root, info) or not stat.S_ISDIR(info.st_mode):
            return False
    except FileNotFoundError:
        return False
    except OSError:
        raise InventoryError("A candidate repository root cannot be inspected safely.") from None
    directory = _git_directory(root)
    return directory is not None and _exact_git_root(root, directory)


def _exact_git_root(root: Path, directory: Path) -> bool:
    # Local metadata was validated before this probe. Let Git identify its own
    # work tree: forcing --work-tree here would hide a different core.worktree.
    valid = _git(root, directory, "rev-parse", "--show-toplevel", probe_root=True)
    if valid is None:
        if (directory / "HEAD").exists():
            raise InventoryError(
                "Git is required to inventory this repository, but its executable is unavailable."
            )
        return False
    if valid.returncode:
        if (directory / "HEAD").exists():
            raise InventoryError("Root Git metadata is malformed or unreadable.")
        return False
    try:
        actual = Path(os.fsdecode(valid.stdout.rstrip(b"\r\n")))
        return actual.is_absolute() and actual.resolve(strict=True) == root.resolve(strict=True)
    except (OSError, ValueError):
        raise InventoryError(
            "The actual Git working-tree root cannot be established safely."
        ) from None


def _git_inventory(root: Path, directory: Path) -> Inventory | None:
    if not _exact_git_root(root, directory):
        return None
    result = _git(root, directory, "ls-files", "--stage", "-z")
    if result is None or result.returncode:
        raise InventoryError("The Git index could not be read; completeness cannot be established.")
    paths: set[str] = set()
    excluded: set[str] = set()
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, _oid, _stage = metadata.split(b" ")
            relative = os.fsdecode(raw_path)
        except ValueError:
            raise InventoryError("The Git index returned an invalid source entry.") from None
        _validate_relative(relative)
        if (
            mode not in {b"100644", b"100755"}
            or _artifact(relative)
            or _nested(root, relative)
            or _checked_path(root, relative) is None
        ):
            excluded.add(relative)
        else:
            paths.add(relative)
    ordered = _ordered(paths)
    encodings: dict[str, str] = {}
    if ordered:
        attributes = _git(
            root,
            directory,
            "check-attr",
            "-z",
            "--stdin",
            "working-tree-encoding",
            data=b"\0".join(os.fsencode(p) for p in ordered),
        )
        if attributes is None or attributes.returncode:
            raise InventoryError("Repository encoding metadata could not be read safely.")
        fields = attributes.stdout.split(b"\0")
        for index in range(0, len(fields) - 2, 3):
            value = fields[index + 2]
            if value not in {b"unspecified", b"unset", b"set"}:
                # Invalid codec labels follow the same per-file recovery path
                # as unknown labels in a source-only repository.
                encodings[os.fsdecode(fields[index])] = value.decode("ascii", errors="replace")
    return Inventory(ordered, len(excluded), "git", encodings)


def _ignore_rules(
    root: Path,
    directory: str,
    decoding: DecodingContext,
    attributes: list[tuple[str, str, str | None]],
) -> list[tuple[str, str, bool]]:
    path = (directory + "/" if directory else "") + ".gitignore"
    target = root / path
    if not os.path.lexists(target):
        return []
    data = _read_bytes(root, path)
    if data is None:
        return []
    content = _decode(data, path, _path_encoding(path, attributes), decoding=decoding)
    if content is None:
        raise InventoryError("Repository ignore guidance cannot be decoded safely.")
    rules = []
    for line in content.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        negative = line.startswith("!")
        pattern = line[1:] if negative else line
        rules.append((directory, pattern, negative))
    return rules


def _ignored(relative: str, rules: list[tuple[str, str, bool]]) -> bool:
    ignored = False
    for base, pattern, negative in rules:
        prefix = base + "/" if base else ""
        if not relative.startswith(prefix):
            continue
        local = relative[len(prefix) :]
        directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/") or "/" in pattern
        pattern = pattern.lstrip("/")
        candidates = local.split("/")[:-1] if directory_only else local.split("/")
        if anchored:
            candidates = [
                "/".join(local.split("/")[:i])
                for i in range(1, len(local.split("/")) + (not directory_only))
            ]
        if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
            ignored = not negative
    return ignored


def _attribute_rules(
    root: Path,
    directory: str,
    decoding: DecodingContext,
    inherited: list[tuple[str, str, str | None]],
) -> list[tuple[str, str, str | None]]:
    """Read simple working-tree-encoding patterns when Git metadata is unavailable.

    Attribute macros containing encodings are rejected because guessing their
    expansion could silently corrupt legitimate source.
    """
    relative = (directory + "/" if directory else "") + ".gitattributes"
    if not os.path.lexists(root / relative):
        return []
    content = read_text(root, relative, _path_encoding(relative, inherited), decoding=decoding)
    if content is None:
        return []
    rules: list[tuple[str, str, str | None]] = []
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "working-tree-encoding" not in line:
            continue
        try:
            fields = shlex.split(line, comments=False)
        except ValueError:
            raise InventoryError(
                "Repository encoding attributes cannot be interpreted safely."
            ) from None
        if not fields:
            continue
        if fields[0].startswith("[attr]"):
            raise InventoryError("Encoding attribute macros require usable root Git metadata.")
        for attribute in fields[1:]:
            if attribute.startswith("working-tree-encoding="):
                rules.append((directory, fields[0], attribute.partition("=")[2]))
            elif attribute in {"-working-tree-encoding", "!working-tree-encoding"}:
                rules.append((directory, fields[0], None))
    return rules


def _path_encoding(relative: str, rules: list[tuple[str, str, str | None]]) -> str | None:
    encoding = None
    for base, pattern, value in rules:
        prefix = base + "/" if base else ""
        if not relative.startswith(prefix):
            continue
        local = relative[len(prefix) :]
        candidate = (
            local
            if "/" in pattern.lstrip("/") or pattern.startswith("/")
            else local.rsplit("/", 1)[-1]
        )
        if fnmatch.fnmatchcase(candidate, pattern.lstrip("/")):
            encoding = value
    return encoding


def _filesystem_inventory(root: Path, decoding: DecodingContext) -> Inventory:
    paths: list[str] = []
    encodings: dict[str, str] = {}
    excluded = 0
    pending = [(root, "", [], [])]
    while pending:
        directory, relative_dir, inherited_rules, inherited_attributes = pending.pop()
        attributes = inherited_attributes + _attribute_rules(
            root, relative_dir, decoding, inherited_attributes
        )
        rules = inherited_rules + _ignore_rules(root, relative_dir, decoding, attributes)
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
            for entry in entries:
                relative = (relative_dir + "/" if relative_dir else "") + entry.name
                _validate_relative(relative)
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if _is_link(path, info):
                    excluded += 1
                elif stat.S_ISDIR(info.st_mode):
                    if entry.name.lower() in _ARTIFACT_DIRS or os.path.lexists(path / ".git"):
                        excluded += 1
                    else:
                        pending.append((path, relative, rules, attributes))
                elif stat.S_ISREG(info.st_mode):
                    if (
                        _artifact(relative)
                        or entry.name == ".git"
                        or (_ignored(relative, rules) and not _maintained(relative))
                    ):
                        excluded += 1
                    else:
                        paths.append(relative)
                        encoding = _path_encoding(relative, attributes)
                        if encoding is not None:
                            encodings[relative] = encoding
                else:
                    excluded += 1
        except OSError:
            raise InventoryError("A repository directory cannot be inventoried safely.") from None
    return Inventory(_ordered(paths), excluded, "filesystem", encodings)


def inventory(root: Path, *, decoding: DecodingContext | None = None) -> Inventory:
    """Inventory current files without following links or using parent Git metadata."""
    root = root.absolute()
    try:
        info = root.lstat()
        if _is_link(root, info) or not stat.S_ISDIR(info.st_mode):
            raise InventoryError("The repository root must be a real directory.")
    except OSError:
        raise InventoryError("The repository root is missing or unreadable.") from None
    directory = _git_directory(root)
    if directory is not None:
        result = _git_inventory(root, directory)
        if result is not None:
            return result
    return _filesystem_inventory(root, decoding or DecodingContext())


def _decode(
    data: bytes, relative: str, encoding: str | None, *, decoding: DecodingContext | None = None
) -> str | None:
    if not data:
        return ""
    if data.startswith(_BINARY_MAGICS):
        return None
    selected = encoding
    unicode_hint = False
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        selected = "utf-32"
        unicode_hint = True
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        selected = "utf-16"
        unicode_hint = True
    elif data.startswith(codecs.BOM_UTF8):
        selected = "utf-8-sig"
        unicode_hint = True
    if selected is None and len(data) >= 4:
        sample = data[:8192]
        sample = sample[: len(sample) - len(sample) % 2]
        even = sample[0::2].count(0) / len(sample[0::2])
        odd = sample[1::2].count(0) / len(sample[1::2])
        if odd > 0.6 and even < 0.1:
            selected = "utf-16-le"
            unicode_hint = True
        elif even > 0.6 and odd < 0.1:
            selected = "utf-16-be"
            unicode_hint = True
    if selected is None:
        controls = sum(byte < 32 and byte not in {9, 10, 12, 13} for byte in data)
        if b"\0" in data or controls / len(data) > 0.01:
            if _maintained(relative):
                raise InventoryError("A likely source file contains undecodable binary controls.")
            return None
        selected = "utf-8"
    text = (decoding or DecodingContext()).decode(
        data, relative, selected, unicode_hint=unicode_hint
    )
    controls = sum(unicodedata.category(char) == "Cc" and char not in "\t\r\n\f" for char in text)
    if "\0" in text or (text and controls / len(text) > 0.01):
        if encoding or _maintained(relative):
            raise InventoryError("A likely source file contains invalid text controls.")
        return None
    return text


def read_source(
    root: Path,
    relative: str,
    encoding: str | None = None,
    *,
    decoding: DecodingContext | None = None,
) -> SourceText | None:
    """Read decoded text and hash original bytes, including any replaced byte values."""
    _validate_relative(relative)
    if _artifact(relative):
        return None
    data = _read_bytes(root.absolute(), relative, classify_binary=True)
    if data is None:
        return None
    lfs_pointer = re.fullmatch(
        rb"version https://git-lfs.github.com/spec/v1\r?\n"
        rb"(?:ext-[^\r\n]+\r?\n)*oid sha256:[0-9a-f]{64}\r?\nsize [0-9]+\r?\n?",
        data,
    )
    if PurePosixPath(relative).suffix.lower() in _BINARY_SUFFIXES and not lfs_pointer:
        return None
    text = _decode(data, relative, encoding, decoding=decoding)
    if text is None:
        return None
    path = PurePosixPath(relative)
    if (
        path.name.lower().endswith((".min.js", ".min.css"))
        and any(
            part.lower() in {"vendor", "vendors", "third_party", "third-party"}
            for part in path.parts[:-1]
        )
        and re.search(
            r"jquery|bootstrap|lodash|react|copyright|@license|generated",
            text[:4096],
            re.IGNORECASE,
        )
    ):
        return None
    return SourceText(text, hashlib.sha256(data).digest())


def read_text(
    root: Path,
    relative: str,
    encoding: str | None = None,
    *,
    decoding: DecodingContext | None = None,
) -> str | None:
    """Return full decoded content, or None for deliberate binary/artifact exclusions."""
    source = read_source(root, relative, encoding, decoding=decoding)
    return source.text if source is not None else None


def git_remote_name(root: Path) -> str | None:
    """Read only the local origin URL; never resolve included config or contact remotes."""
    root = root.absolute()
    directory = _git_directory(root)
    if directory is None or not _exact_git_root(root, directory):
        return None
    result = _git(
        root, directory, "config", "--local", "--no-includes", "--get", "remote.origin.url"
    )
    if result is None or result.returncode:
        return None
    try:
        remote = result.stdout.decode("utf-8").strip()
        if any(unicodedata.category(char).startswith("C") for char in remote):
            return None
        path = (
            urlsplit(remote).path
            if "://" in remote
            else re.split(r"[?#]", remote.split(":", 1)[-1], maxsplit=1)[0]
        )
        name = unquote(path.rstrip("/").rsplit("/", 1)[-1])
        name = name.removesuffix(".git")
        return name or None
    except (UnicodeError, ValueError):
        return None
