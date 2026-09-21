"""Checkout bootstrap: expose the source package without installing it."""

from pathlib import Path

# Restrict package lookup to our source package; do not mutate global sys.path
# or execute arbitrary source as a bootstrap mechanism.
__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "repo_snapshot")]
__version__ = "1.0.0"
