"""Small, safe command-line interface for the fixed input/output workspace."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
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
        description="Create a validated Markdown source snapshot from input/ into output/.",
        allow_abbrev=False,
    )
    parser.add_argument("--output", metavar="NAME.md", help="output basename (under output/)")
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

        result = generate(project_root or _project_root(), output_name=arguments.output)
        print(f"Generated: {result.path}")
        print(
            f"Validated: {result.file_count} file(s), {result.excluded_count} excluded, "
            f"{result.redaction_count} redaction(s); {result.mode} inventory."
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
