"""Fixed workspace boundaries and deterministic, portable output names."""

from __future__ import annotations

import json
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .decoding import DecodingContext
from .discovery import discover_repository
from .errors import InputError, SnapshotError, ValidationError
from .inventory import Inventory, git_remote_name, read_text

_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def validate_output_name(name: str) -> str:
    """Accept one portable Markdown basename, never a path or device name."""
    if (
        not name
        or _INVALID.search(name)
        or name.endswith((" ", "."))
        or name in {".", ".."}
        or not name.lower().endswith(".md")
        or not name[:-3].strip(". ")
        or _RESERVED.match(name)
        or len(name.encode("utf-8", errors="surrogatepass")) > 240
        or any(not c.isprintable() for c in name)
    ):
        raise InputError(
            "Output must be a portable .md filename, without directories or traversal."
        )
    return name


def _safe_identifier(value: str) -> str | None:
    """Normalize project identifiers, not arbitrary filesystem directory names."""
    value = re.sub(r"[^\w.-]+", "-", value.strip(), flags=re.UNICODE).strip(".-")
    if not value:
        return None
    # Bound by bytes for portable filesystems without cutting a UTF-8 sequence.
    value = value.encode("utf-8")[:180].decode("utf-8", errors="ignore")
    if _RESERVED.match(value):
        value = "repository-" + value
    return value


def repository_name(
    root: Path,
    listing: Inventory,
    *,
    input_root: Path | None = None,
    decoding: DecodingContext | None = None,
) -> str:
    """Prefer origin, a discovered folder name, then workspace/project evidence."""
    if listing.mode == "git":
        origin = git_remote_name(root)
        if origin and (name := _safe_identifier(origin)):
            return name
    if input_root is not None and root != input_root and root.is_relative_to(input_root):
        if name := _safe_identifier(root.name):
            return name
    for suffixes in (
        {".sln", ".slnx", ".code-workspace"},
        {".csproj", ".fsproj", ".vbproj", ".vcxproj", ".xcodeproj"},
    ):
        names = {Path(path).stem for path in listing.paths if Path(path).suffix in suffixes}
        if len(names) == 1 and (name := _safe_identifier(names.pop())):
            return name
    identifiers: set[str] = set()
    for filename in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod"):
        if filename not in listing.paths:
            continue
        text = read_text(root, filename, listing.encodings.get(filename), decoding=decoding)
        if text is None:
            continue
        try:
            if filename == "package.json":
                data = json.loads(text)
                value = data.get("name") if isinstance(data, dict) else None
                if isinstance(value, str):
                    value = value.rsplit("/", 1)[-1]
            elif filename == "go.mod":
                match = re.search(r"^module\s+([^\s]+)", text, re.M)
                value = match.group(1).rsplit("/", 1)[-1] if match else None
            else:
                data = tomllib.loads(text)
                section = data.get("project" if filename == "pyproject.toml" else "package", {})
                value = section.get("name") if isinstance(section, dict) else None
            if isinstance(value, str) and (name := _safe_identifier(value)):
                identifiers.add(name)
        except (ValueError, TypeError):
            # Naming evidence is optional; malformed source is still preserved.
            continue
    return identifiers.pop() if len(identifiers) == 1 else "repository"


@dataclass(frozen=True)
class Workspace:
    root: Path
    input: Path
    output: Path
    input_identity: tuple[int, int]
    output_identity: tuple[int, int]
    repository: Path
    repository_identities: tuple[tuple[Path, tuple[int, int]], ...]

    @classmethod
    def open(cls, project_root: Path) -> Workspace:
        root = project_root.resolve(strict=True)
        source = root / "input"
        destination = root / "output"
        if _linked(source) or not source.is_dir():
            raise InputError(
                "input/ must exist as a real directory. Copy repository files into it."
            )
        repository = discover_repository(source)
        if not repository.is_relative_to(source):
            raise InputError("The discovered repository lies outside input/.")
        identities = []
        current = source
        for part in repository.relative_to(source).parts:
            current /= part
            info = current.lstat()
            if _linked(current) or not stat.S_ISDIR(info.st_mode):
                raise InputError("Repository discovery encountered an unsafe directory boundary.")
            identities.append((current, (info.st_dev, info.st_ino)))
        if _linked(destination):
            raise InputError("output/ must be a real directory, not a symbolic link or junction.")
        destination.mkdir(mode=0o700, exist_ok=True)
        if not destination.is_dir():
            raise InputError("output/ must be a directory.")
        source_stat, destination_stat = source.stat(), destination.stat()
        return cls(
            root,
            source,
            destination,
            (source_stat.st_dev, source_stat.st_ino),
            (destination_stat.st_dev, destination_stat.st_ino),
            repository,
            tuple(identities),
        )

    def check_boundaries(self) -> None:
        for path, expected in (
            (self.input, self.input_identity),
            (self.output, self.output_identity),
            *self.repository_identities,
        ):
            current = path.lstat()
            if (
                _linked(path)
                or not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != expected
            ):
                raise InputError(
                    "Workspace directories changed during generation; rerun on stable input."
                )

    def check_repository_selection(self) -> None:
        """Do not publish after a wrapper swap or a newly ambiguous container."""
        self.check_boundaries()
        try:
            selected = discover_repository(self.input)
        except SnapshotError:
            raise ValidationError(
                "Repository discovery changed during generation; rerun on stable input."
            ) from None
        if selected != self.repository:
            raise ValidationError("The selected repository changed during generation.")
        self.check_boundaries()

    def target(self, name: str) -> Path:
        self.check_boundaries()
        target = self.output / validate_output_name(name)
        if _linked(target) or (target.exists() and not target.is_file()):
            raise InputError(
                "Snapshot target must be a regular file, not a directory or symbolic link."
            )
        return target
