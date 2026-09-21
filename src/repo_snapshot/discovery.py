"""Conservative, read-only discovery within the fixed input container.

A valid Git root wins and stops traversal beneath itself. Otherwise all Git roots
under the container are considered, with links, junctions and known artifact
directories excluded. An artifact-like directory name may itself be a valid Git
root; discovery checks that directory but does not search ordinary artifact
directories for nested dependencies. More than one independent root is an error.

Without Git, any direct meaningful file anchors its directory. A single child
can be a wrapper. Familiar source-layout directories such as ``src`` remain part
of their parent unless repository-root evidence identifies a wrapped repository.
Multiple familiar source directories form one direct repository layout, including
their individual project manifests. Unclear unrelated children are reported
rather than selected by name. Source presence has no extension allowlist;
classification and completeness remain the inventory layer's responsibility.
"""

import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .errors import InputError
from .inventory import _ARTIFACT_DIRS, _OS_FILES, is_git_root
from .secrets import redact

_SOURCE_DIRECTORIES = frozenset(
    {
        "src",
        "source",
        "lib",
        "libs",
        "app",
        "apps",
        "include",
        "scripts",
        "deploy",
        "deployment",
        "infra",
        "infrastructure",
        "docs",
        "doc",
        "test",
        "tests",
        ".github",
        ".gitlab",
        "packages",
        "cmd",
        "internal",
        "controllers",
        "services",
        "models",
        "legacy",
        "code_backups",
        "backup",
        "old",
        "archive",
        "resources",
        "migration",
        "migrations",
        "examples",
        "config",
        "configuration",
        "tools",
        "public",
        "assets",
        "components",
    }
)
_ROOT_FILENAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "cmakelists.txt",
        "composer.json",
        "gemfile",
        "mix.exs",
        "makefile",
    }
)
_PROJECT_SUFFIXES = frozenset(
    {".sln", ".slnx", ".csproj", ".fsproj", ".vbproj", ".vcxproj", ".code-workspace"}
)


@dataclass(frozen=True)
class _Directory:
    files: tuple[Path, ...]
    children: tuple[Path, ...]


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _checked_directory(path: Path, boundary: Path) -> Path:
    """Recheck components before traversing; a discovered link is never followed."""
    relative = path.relative_to(boundary)
    current = boundary
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        if _is_link(current) or not stat.S_ISDIR(current.lstat().st_mode):
            raise InputError("Input directories changed or are unsafe; use real directories.")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(boundary):
        raise InputError("Repository discovery cannot leave input/.")
    return resolved


def _contents(directory: Path) -> _Directory:
    files: list[Path] = []
    children: list[Path] = []
    for entry in sorted(directory.iterdir(), key=lambda path: path.name):
        name = entry.name.lower()
        if name in _OS_FILES or name == ".git" or entry.name.endswith(("~", ".swp", ".swo")):
            continue
        if _is_link(entry):
            continue
        mode = entry.lstat().st_mode
        if stat.S_ISDIR(mode):
            if name not in _ARTIFACT_DIRS or is_git_root(entry):
                children.append(entry)
        elif stat.S_ISREG(mode):
            files.append(entry)
    return _Directory(tuple(files), tuple(children))


def _candidate_label(candidate: Path, boundary: Path) -> str:
    relative = candidate.relative_to(boundary).as_posix()
    cleaned, _ = redact(relative)
    cleaned = "".join(
        character
        for character in cleaned
        if not unicodedata.category(character).startswith("C")
        and unicodedata.category(character) not in {"Zl", "Zp"}
    )
    # Removing controls could join pieces into a recognizable credential.
    cleaned, _ = redact(cleaned)
    return (cleaned or "[unnamed directory]") + "/"


def _ambiguous(candidates: tuple[Path, ...] | list[Path], boundary: Path) -> InputError:
    labels = [_candidate_label(candidate, boundary) for candidate in sorted(candidates)]
    return InputError(
        "Multiple repository candidates found under input/:\n\n"
        + "\n".join("- " + label for label in labels)
        + "\n\nKeep one repository under input/ and run again."
    )


def _root_evidence(path: Path, tree: dict[Path, _Directory], meaningful: set[Path]) -> bool:
    directory = tree[path]
    while not directory.files:
        children = tuple(child for child in directory.children if child in meaningful)
        if len(children) != 1:
            return False
        directory = tree[children[0]]
    return any(
        file.name.lower() in _ROOT_FILENAMES
        or file.name.lower() == "readme"
        or file.name.lower().startswith("readme.")
        or file.suffix.lower() in _PROJECT_SUFFIXES
        for file in directory.files
    )


def _non_git_root(boundary: Path, tree: dict[Path, _Directory]) -> Path:
    # Children occur after their parents in traversal order; compute meaningful
    # subtrees bottom-up to ignore empty wrappers without repeatedly walking them.
    meaningful: set[Path] = set()
    for path, directory in reversed(tuple(tree.items())):
        if directory.files or any(child in meaningful for child in directory.children):
            meaningful.add(path)
    if boundary not in meaningful:
        raise InputError("input/ contains no repository source files or meaningful directories.")

    current = boundary
    while True:
        directory = tree[current]
        if directory.files:
            return current
        children = tuple(child for child in directory.children if child in meaningful)
        if len(children) == 1:
            child = children[0]
            if child.name.lower() in _SOURCE_DIRECTORIES and not _root_evidence(
                child, tree, meaningful
            ):
                return current
            current = child
            continue
        if all(child.name.lower() in _SOURCE_DIRECTORIES for child in children):
            return current
        raise _ambiguous(children, boundary)


def discover_repository(input_root: Path) -> Path:
    """Return the unambiguous source root, always within the real input directory."""
    try:
        if _is_link(input_root) or not input_root.is_dir():
            raise InputError("input/ must exist as a real directory containing one repository.")
        boundary = input_root.resolve(strict=True)
        pending = [boundary]
        tree: dict[Path, _Directory] = {}
        candidates: list[Path] = []
        while pending:
            current = _checked_directory(pending.pop(), boundary)
            if is_git_root(current):
                candidates.append(current)
                continue
            directory = _contents(current)
            tree[current] = directory
            pending.extend(reversed(directory.children))
        if len(candidates) > 1:
            raise _ambiguous(candidates, boundary)
        selected = candidates[0] if candidates else _non_git_root(boundary, tree)
        return _checked_directory(selected, boundary)
    except OSError:
        raise InputError("Repository discovery could not safely read input/ directories.") from None
