# Verification notes

This is a historical record of checks performed before the test directory was
removed at the user's request. The automated test suite is no longer included.

Verified on macOS ARM64 with Python 3.12.14. The application has no third-party
runtime dependencies. pytest 9.1.1 and Ruff 0.16.8 were installed in the local
`.venv` for development. No repository contents were uploaded or committed.

## Automated verification

Commands used during the original verification:

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

Final result: **213 passed, 2 skipped** in 5.55 seconds. Ruff reported **all checks
passed**. The skips are the two Windows-only junction integration tests.

The tests inspect actual Markdown, use real temporary Git indexes, and invoke the
module and launchers through subprocesses. Coverage includes membership and
working-tree changes; ignore precedence; filesystem boundaries; source encodings;
LFS pointers; empty and large files; redaction and false positives; deterministic
output; deliberately damaged snapshots; source changes; safe errors; failed
publication; and preservation of source and previous snapshots.
Real sparse-file regressions also verify bounded reads of excluded 64 MiB binary
files; encoding regressions preserve a genuine leading U+FEFF after an encoding BOM.

Two tests requiring actual Windows directory junctions cannot run on this macOS
host. Junction rejection policy is exercised separately here. Windows batch
execution and Linux-host execution require their respective operating systems;
no claim of those platform runs is made. No separate type checker is configured.

## Additional checks performed

- Editable package built and installed successfully; the installed `repo-snapshot`
  entrypoint reported version 1.0.0; `pip check` reported no broken requirements.
- All package modules compiled; POSIX shell syntax checks passed for both scripts.
- Direct module execution and `run.command` correctly rejected the empty actual
  `input/` with exit code 2 and did not publish any snapshot.
- An interactive terminal run of `run.command` displayed the error, waited for
  Enter, and preserved exit code 2 after the pause.
- Separate filesystem and Git fixtures each contained representative .NET, Python,
  JavaScript, CI, Helm, Terraform, Docker, documentation, UTF-16 and empty source.
  Both direct-module and macOS-launcher runs produced the same 13 validated
  sections, including working-tree modifications in the Git fixture.
- Repeated snapshots were byte-identical. Source and Git metadata content hashes
  were unchanged. Independent validation and the final secret scan passed.
- Injecting an undecodable source file made the real launcher return exit code 3,
  retained the previous valid snapshot byte-for-byte, and left no staging file.

Representative repositories were created only inside isolated temporary test
workspaces, each using the required `input/` and `output/` layout. The project's
actual `input/` and `output/` remain empty, ready for the user's repository.

## Deliberate limits

Secret detection is heuristic; unknown, obfuscated, or split credentials can be
missed, and false positives remain possible. Explicit failures replace guesses
for unsupported text encodings, unrepresentable filenames, unsafe Git metadata,
Git configuration includes, and encoding macros without Git metadata. All links
and nested repository/submodule contents are excluded. Keep input stable during a
run. The required raw `file:` format cannot provide an unambiguous standalone
parser when original source contains identical header-like lines; internal
validation uses source-derived boundaries and private byte records instead.
