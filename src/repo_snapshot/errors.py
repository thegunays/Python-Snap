"""Public error categories and CLI exit codes."""


class SnapshotError(Exception):
    """A controlled failure with a safe, actionable message."""

    exit_code = 1


class InputError(SnapshotError):
    """Invalid input or output configuration."""

    exit_code = 2


class InventoryError(SnapshotError):
    """Repository membership or source could not be read safely."""

    exit_code = 3


class ValidationError(SnapshotError):
    """Completeness, fidelity, or integrity validation failed."""

    exit_code = 4
