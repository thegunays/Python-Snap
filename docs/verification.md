# Verification notes

The test suites and the `input/` and `output/` directories were removed at the
user's request. Earlier results are retained below as historical evidence; their test
counts and fixture paths do not describe the current workspace.

## Current behavior

No secret detection or masking applies to source content, source/output names,
CLI labels, or diagnostics. Eligible decoded source content is preserved unchanged.
Independent validation checks repository selection, source membership and content;
completed-section bounds, lengths, and hashes are verified before atomic publication.
Path containment and control-character safety remain. The historical results below
predate this change and do not constitute verification of it.

## Current change verification

**11 isolated temporary tests passed**, covering unchanged JSON/.NET values and
CRLF, deterministic output, unmodified input, credential-like names and CLI labels,
corruption detection, and output-path safeguards. Ruff, `git diff --check`, and
CLI `--version` also passed. The project's `tests/`, `input/`, and `output/`
directories remain absent.

## Historical removal of the final secret scan

Three isolated temporary behavioral tests passed at that stage: generation no
longer depended on the final secret detector, initial masking remained,
staged-byte tampering preserved the prior output, and nested paths and deterministic
output remained correct. Ruff and the CLI `--version` check passed. The project's
`tests/`, `input/`, and `output/`
directories were not recreated.

## Historical repository-discovery verification

Verified on macOS ARM64 with Python 3.12.14. The application has no third-party
runtime dependencies. pytest 9.1.1 and Ruff 0.16.8 were installed in the local
`.venv` for development. No repository contents were uploaded or committed.

**109 tests passed** in the final full-suite run; Ruff and POSIX launcher syntax
checks passed. The suite uses real temporary Git indexes and copied working trees,
with no commits or remote access. It covers direct and wrapped Git repositories,
arbitrary names, spaces and Unicode, contained `.git` files, parent metadata
rejection, nested repositories/submodules, source-only wrappers, conventional
multi-project layouts, ambiguity diagnostics, and symlink/junction policies.

Integration tests run the Python module, `run.sh`, and `run.command` after copying
an entire Git working-tree directory into `input/`. They also verify selected-root
paths, output naming/isolation, read-only input, tracked current contents, secret-safe
candidate diagnostics, and preservation of previous output when discovery changes.

The then-existing `input/xproject/` .NET fixture was processed successfully by the real
launcher and module. All **1,208 eligible files** appeared under paths such as
`src/Program.cs`, without `xproject/` or `input/` prefixes. The output was
`output/xproject.md`. Independent validation and the final secret scan passed;
all input content hashes stayed unchanged, and repeated output was byte-identical.

Windows-host and Linux-host execution were not performed; POSIX launcher execution
was verified on macOS. No separate type checker is configured.

## Historical original automated verification

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

## Historical additional checks

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
actual `input/` and `output/` were empty at that stage. The user subsequently
requested the synthetic .NET fixture formerly stored under `input/xproject/`;
that fixture and its generated output have since been removed.

## Deliberate limits

Explicit failures replace guesses for unsupported text encodings, unrepresentable
filenames, unsafe Git metadata, Git configuration includes, and encoding macros
without Git metadata. All links
and nested repository/submodule contents inside the selected root are excluded.
Ordinary external worktree metadata is not followed; contained `.git` files are
supported, and source-only copies remain usable. Keep input stable during a
run. The required raw `file:` format cannot provide an unambiguous standalone
parser when original source contains identical header-like lines; internal
validation uses source-derived boundaries and private byte records instead.
