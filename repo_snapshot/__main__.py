"""Fallback checkout entrypoint; normal lookup resolves the source entrypoint."""

import sys

if sys.version_info < (3, 12):  # noqa: UP036 -- guard before importing application code
    print("Error: Python 3.12 or newer is required.", file=sys.stderr)
    raise SystemExit(1)

from .cli import main  # noqa: E402

raise SystemExit(main())
