"""Staged generation, independent source validation and atomic publication.

Source may itself contain ``file:`` lines. Section boundaries are verified against
freshly read source lengths, never inferred by searching for header-like content.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .errors import InputError, SnapshotError, ValidationError
from .inventory import inventory, read_text
from .secrets import has_secrets, redact
from .workspace import Workspace, repository_name


@dataclass(frozen=True)
class Section:
    path: str
    offset: int
    size: int
    source_digest: bytes
    snapshot_digest: bytes


@dataclass(frozen=True)
class SnapshotResult:
    path: Path
    file_count: int
    excluded_count: int
    redaction_count: int
    mode: str
    repository_root: Path


def _digest(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _header(path: str) -> bytes:
    if has_secrets(path):
        raise ValidationError(
            "A source filename contains a detectable credential; publication blocked."
        )
    return f"file: {path}\n".encode()


def _open_snapshot(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise ValidationError("Staged snapshot is not a regular file.")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _compare(stream: BinaryIO, expected: bytes) -> None:
    view = memoryview(expected)
    for start in range(0, len(expected), 65536):
        if stream.read(min(65536, len(expected) - start)) != view[start : start + 65536]:
            raise ValidationError("Snapshot content differs from complete, redacted source.")


def validate_snapshot(
    repository_root: Path,
    snapshot_path: Path,
    expected: tuple[Section, ...] | None = None,
) -> tuple[Section, ...]:
    """Independently inventory, decode and compare every completed snapshot byte.

    ``expected`` also checks that source did not change after the writing pass.
    The public validator can validate a snapshot without an in-memory manifest.
    """
    listing = inventory(repository_root)
    expected_sources = {item.path: item.source_digest for item in expected or ()}
    if expected is not None and len(expected_sources) != len(expected):
        raise ValidationError("Duplicate expected snapshot paths.")
    sections: list[Section] = []
    actual_paths: list[str] = []
    eligible_paths: list[str] = []
    with _open_snapshot(snapshot_path) as staged:
        for relative in listing.paths:
            text = read_text(repository_root, relative, listing.encodings.get(relative))
            if text is None:
                continue
            eligible_paths.append(relative)
            source_digest = _digest(text.encode("utf-8"))
            if expected is not None and expected_sources.get(relative) != source_digest:
                raise ValidationError(
                    "Eligible source membership or contents changed during generation."
                )
            clean, _ = redact(text)
            payload = clean.encode("utf-8")
            header = _header(relative)
            start = staged.tell()
            actual_header = staged.readline(len(header) + 1)
            if actual_header != header:
                raise ValidationError(
                    "Snapshot file headers are missing, duplicated, unexpected or out of order."
                )
            actual_paths.append(actual_header[len(b"file: ") : -1].decode("utf-8"))
            _compare(staged, payload)
            _compare(staged, b"\n\n")
            checksum = hashlib.sha256(header)
            checksum.update(payload)
            checksum.update(b"\n\n")
            sections.append(
                Section(relative, start, staged.tell() - start, source_digest, checksum.digest())
            )
        if staged.read(1):
            raise ValidationError("Snapshot contains unexpected trailing data or duplicate files.")
    if not eligible_paths:
        raise ValidationError("No eligible source/text files were found during validation.")
    if len(actual_paths) != len(set(actual_paths)) or actual_paths != eligible_paths:
        raise ValidationError("Snapshot file set or deterministic ordering is incorrect.")
    if expected is not None and tuple(eligible_paths) != tuple(item.path for item in expected):
        raise ValidationError("Expected and actual eligible file sets differ.")
    return tuple(sections)


def final_secret_scan(snapshot_path: Path, sections: tuple[Section, ...]) -> None:
    """Re-read completed UTF-8 output, scanning full source sections and headers.

    Memory is bounded by the largest source section; no heuristic splitting on
    source text, fixed line limits or secret-length cutoffs are used.
    """
    with _open_snapshot(snapshot_path) as staged:
        for section in sections:
            if staged.tell() != section.offset:
                raise ValidationError("Snapshot section boundaries are inconsistent.")
            data = staged.read(section.size)
            if len(data) != section.size or _digest(data) != section.snapshot_digest:
                raise ValidationError("Snapshot changed after completeness validation.")
            try:
                text = data.decode("utf-8", errors="strict")
            except UnicodeError:
                raise ValidationError("Snapshot is not valid UTF-8.") from None
            if has_secrets(text):
                raise ValidationError(
                    "Final secret scan detected a credential; publication blocked."
                )
        if staged.read(1):
            raise ValidationError("Snapshot changed after completeness validation.")


def generate(project_root: Path, output_name: str | None = None) -> SnapshotResult:
    """Publish a complete snapshot, preserving previous output on every failure."""
    temporary: Path | None = None
    try:
        workspace = Workspace.open(project_root)
        listing = inventory(workspace.repository)
        name = (
            output_name
            if output_name is not None
            else repository_name(workspace.repository, listing, input_root=workspace.input) + ".md"
        )
        target = workspace.target(name)
        descriptor, filename = tempfile.mkstemp(
            prefix=".repo-snapshot-", suffix=".tmp", dir=workspace.output
        )
        temporary = Path(filename)
        sections: list[Section] = []
        redaction_count = 0
        excluded_count = listing.excluded_count
        with os.fdopen(descriptor, "wb") as staged:
            for relative in listing.paths:
                text = read_text(workspace.repository, relative, listing.encodings.get(relative))
                if text is None:
                    excluded_count += 1
                    continue
                source_digest = _digest(text.encode("utf-8"))
                clean, count = redact(text)
                payload = clean.encode("utf-8")
                header = _header(relative)
                start = staged.tell()
                staged.write(header)
                staged.write(payload)
                staged.write(b"\n\n")
                checksum = hashlib.sha256(header)
                checksum.update(payload)
                checksum.update(b"\n\n")
                sections.append(
                    Section(
                        relative, start, staged.tell() - start, source_digest, checksum.digest()
                    )
                )
                redaction_count += count
            if not sections:
                if listing.mode == "git":
                    raise InputError(
                        "The selected Git repository has no eligible tracked source/text files. "
                        "Git mode includes tracked files only."
                    )
                raise InputError("The selected repository contains no eligible source/text files.")
            staged.flush()
            os.fsync(staged.fileno())
        workspace.check_repository_selection()
        validated = validate_snapshot(workspace.repository, temporary, tuple(sections))
        final_secret_scan(temporary, validated)
        workspace.check_repository_selection()
        workspace.target(name)  # Recheck boundary/target after all potentially lengthy reads.
        os.replace(temporary, target)
        temporary = None
        return SnapshotResult(
            target,
            len(validated),
            excluded_count,
            redaction_count,
            listing.mode,
            workspace.repository,
        )
    except SnapshotError:
        raise
    except (OSError, UnicodeError, ValueError):
        # OS errors may include credential-bearing filenames; never echo them.
        raise SnapshotError(
            "Snapshot failed: check file permissions, available disk space and workspace paths."
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # A .tmp file is never presented as a valid published snapshot.
                pass
