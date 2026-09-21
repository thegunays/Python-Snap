"""Small, safe command-line interface for the fixed input/output workspace."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .decoding import DEFAULT_FALLBACK_ENCODING
from .errors import SnapshotError


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's default diagnostic repeats arbitrary user-provided values.
        self.exit(2, "Error: invalid arguments. Use --help for usage.\n")


def _project_root() -> Path:
    package = Path(__file__).resolve().parent
    checkout = package.parent.parent
    if package.parent.name == "src" and (checkout / "pyproject.toml").is_file():
        return checkout
    return Path.cwd()


def main(argv: Sequence[str] | None = None, *, project_root: Path | None = None) -> int:
    """Run a snapshot, reporting safe diagnostics and a meaningful exit status."""
    parser = _ArgumentParser(
        prog="repo-snapshot",
        description="Discover one repository under input/ and create its snapshot under output/.",
        allow_abbrev=False,
    )
    parser.add_argument("--output", metavar="NAME.md", help="output basename (under output/)")
    parser.add_argument(
        "--fallback-encoding", default=DEFAULT_FALLBACK_ENCODING, metavar="ENCODING",
        help="text encoding tried after UTF-8 fails (default: cp1254; e.g. cp1252)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code or 0)

    if sys.version_info < (3, 12):  # noqa: UP036 -- report unsupported direct invocation
        print("Error: Python 3.12 or newer is required.", file=sys.stderr)
        return 1
    try:
        # Keep help/version independent of repository processing and input state.
        from .snapshot import generate

        root = (project_root or _project_root()).resolve()
        result = generate(
            root, output_name=arguments.output, fallback_encoding=arguments.fallback_encoding
        )
        for warning in result.decoding_warnings:
            path = "".join(character for character in warning.path if character.isprintable())
            detail = (
                "undecodable characters were replaced with U+FFFD"
                if warning.replaced else "the preferred encoding could not decode this file"
            )
            print(f"Warning: {path}: used {warning.encoding}; {detail}.", file=sys.stderr)
        relative = result.repository_root.relative_to(root / "input").as_posix()
        label = "input/" if relative == "." else "input/" + relative + "/"
        label = "".join(character for character in label if character.isprintable())
        print(f"Source: {label}")
        print(f"Generated: {result.path}")
        print(
            f"Validated: {result.file_count} file(s), {result.excluded_count} excluded; "
            f"{result.mode} inventory."
        )
        return 0
    except SnapshotError as error:
        print(f"Error: {error}", file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        print("Error: interrupted; generation did not complete.", file=sys.stderr)
        return 130
    except Exception:
        # Source values and raw OS exception messages must never reach the console.
        print(
            "Error: snapshot generation could not complete safely. "
            "Check workspace access, available storage, and source readability.",
            file=sys.stderr,
        )
        return 1
