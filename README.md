# Repository Snapshot

Create one portable Markdown file containing a repository's eligible source,
configuration, infrastructure, scripts, and documentation. The utility inventories,
writes, and validates the snapshot. It does not analyze code or contact an
AI service. Normal operation uses the Python standard library and requires no
network access.

## Run

Install **Python 3.12 or newer** once, then copy either a **whole repository folder**
or its **contents** into this project's `input/` directory. `input/` is a container:
the application discovers the repository automatically. Include its `.git` metadata
to use tracked Git membership, or copy source without Git metadata.

```text
Python-Snap/
├── input/
│   └── MyRepository/     or place these contents directly inside input/
│       ├── README.md
│       ├── src/
│       └── .git/         optional
├── output/               created automatically
├── src/repo_snapshot/    application
├── repo_snapshot/        checkout module bootstrap
├── run.bat
├── run.command
└── run.sh
```

1. Windows: double-click **run.bat**.
2. macOS: double-click **run.command**.
3. Linux: run **run.sh**; graphical double-click support depends on your file
   manager's executable-file settings.

The launcher prints the generated path and validation counts. macOS and Windows
keep an interactive terminal open until you press a key. Redirected/noninteractive
runs do not pause. No launcher installs Python, packages, or other software.

If an archive loses executable permissions on macOS/Linux, run
`chmod +x run.sh run.command` once. Launchers use their own project directory even
when invoked from somewhere else. They try a local `.venv` and supported Python
commands; Windows also tries the `py` launcher. To select a particular interpreter,
set `REPO_SNAPSHOT_PYTHON` to its executable path, without command-line arguments.
An invalid explicit override produces an error instead of silently selecting
another interpreter.

From the project root, direct execution needs no package installation:

```sh
python3 -m repo_snapshot
python3 -m repo_snapshot --output MySnapshot.md
python3 -m repo_snapshot --help
```

On Windows, use `py -3.12 -m repo_snapshot` if `python` is unavailable. The optional
installed command is `repo-snapshot`; install the local package with
`python -m pip install .`. A source checkout, including an editable installation,
always uses its own `input/` and `output/`. A regular installed package uses
`input/` and `output/` under the current working directory. `--output` accepts a
simple `.md` basename, never a path.

The default name prefers reliable Git metadata, then the discovered repository's
folder name, then unambiguous project/workspace identifiers, falling back to
`repository.md`. The container name `input` does not supply the default name.
Generated files stay under `output/`; existing snapshots are replaced only after
the new snapshot passes validation.

## Repository discovery

A valid Git repository directly at `input/` takes priority. Otherwise the program
searches beneath `input/`, including harmless wrapper directories, and selects one
independent Git root. Once a Git root is found, its nested repositories and
submodules do not become competing roots. Multiple independent repositories cause
an error listing their relative candidate paths with control characters removed;
keep one repository in the container and run again.

Without usable Git metadata, direct repository content stays rooted at `input/`.
A single meaningful repository folder is selected automatically. Ordinary source
layouts such as `src/` and `deploy/` remain part of their containing repository;
ambiguous collections of unrelated folders are rejected rather than guessed.
Discovery ignores symlinks, junctions, generated directories and operating-system
noise, and never searches above `input/`.

For example, both `input/MyRepository/src/App.cs` and
`input/wrapper/MyRepository/src/App.cs` produce `file: src/App.cs` after
`MyRepository` is selected. Output always stays in this application's `output/`.

## Snapshot contract

Each eligible file appears exactly once, in deterministic order: root-level files
first, then nested paths in lexical order. Paths are relative to the **discovered
repository root**, use forward slashes, and omit container/wrapper directory names.
Sections have this form, with no added fences or commentary:

```text
file: README.md
original content

file: src/app.py
original content
```

Current working-tree content is preserved, including empty files, comments,
indentation, original newlines, and source values. Output is UTF-8. UTF-8,
BOM-marked UTF-8/UTF-16, and supported repository encoding metadata
are decoded strictly; undecodable eligible source causes failure rather than
replacement characters or silent omission. Encoding BOMs are consumed when
decoding, so this is a textual snapshot, not a byte-for-byte archive.

Git index membership is authoritative when usable Git metadata belongs to the
discovered repository root; tracked modifications and tracked files matching ignore rules
are included. Untracked files are not part of that Git snapshot. Without usable
root Git metadata, the utility recursively inventories the selected filesystem tree. Parent Git
metadata never supplies membership. Known binaries, build output, caches, and
derived dependencies are excluded; filtering also inspects bytes rather than
trusting extensions alone. Maintained legacy and backup source directories are
not excluded just because of their names.

All symlinks are skipped. Submodules and nested repositories **inside the selected
repository** are not recursively expanded. Git LFS pointers remain pointer text;
objects are never downloaded. `.git` files are supported when their metadata stays
inside the selected source boundary; external worktree metadata is not followed.
Nothing under `input/` is written, executed, or formatted in place.
No Git initialization, fetching, configuration updates, telemetry, or upload occurs.

Git must be installed when `input/` contains recognized Git metadata; a missing
Git executable causes an error rather than silently changing repository membership.
Source-only copies work without Git. Corrupt or linked Git metadata and local Git
configuration includes are rejected. Git transports and lazy fetches are disabled.
Without Git metadata, `.gitignore` is conservative guidance: recognized maintained
source stays included. Ordinary nested `.gitattributes` encoding rules are supported;
encoding macros require usable Git metadata. An excluded directory counts as one
pruned entry in the reported exclusion count.

## Validation

Eligible decoded source content is written unchanged. No secret detection or
masking is applied to source content, source/output names, CLI labels, or diagnostics.

Generation stages a temporary file under `output/`. Independent validation rechecks
repository selection, inventory, and source content. The completed snapshot's
section boundaries, lengths, and hashes are verified before atomic replacement of
the destination.
Failures preserve an earlier valid output and do not publish a partial snapshot.
Keep `input/` unchanged while a run is in progress; detected changes cause failure.
This is not a filesystem transaction and cannot protect against a malicious
process continuously replacing files during the run.

The required plain-text format is inherently ambiguous when source itself has a
line beginning with `file:`. Internal validation uses private section offsets,
lengths, and hashes rather than treating every such source line as a new header.
Those validation records are not added to the portable Markdown. Filenames with
line separators/control characters cannot be represented safely and cause failure.
Windows device names are rejected for output, and workspace symlinks and directory
junctions cannot redirect output. Processing uses memory proportional to the
largest eligible file, plus the inventory, rather than retaining the whole repository.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Generated and validated |
| 1 | Runtime, storage, or unexpected failure |
| 2 | Invalid input, output name, empty eligible inventory, or CLI arguments |
| 3 | Inventory, source-read, or decoding failure |
| 4 | Completeness, fidelity, or integrity-validation failure |
| 130 | Interrupted |

## Development

Runtime dependencies are standard-library only. Development checks use Ruff:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check .
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
Dependency installation is an explicit development step and may need network
access. The test suite was removed at the user's request; prior test results are
recorded in the verification notes. The Windows batch launcher is supplied but
requires a Windows host for runtime verification.

The package separates discovery, inventory/decoding, workspace/output
handling, snapshot validation, and CLI reporting. The checkout bootstrap exposes
the source package without executing source strings or changing global `sys.path`.

See [verification notes](docs/verification.md) for the checks run on this implementation.
