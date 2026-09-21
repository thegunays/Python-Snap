# Repository snapshot implementation plan

The supplied specification is the design brief. Implement a Python 3.12+ package,
using the standard library at runtime and pytest for behavioral tests. No source
analysis, networking, Git mutation, commits, or writes under input are permitted.

## Design decisions

- Fixed workspace input/output boundaries; default project root comes from the
  source checkout, or the current directory for an installed CLI.
- Git index membership with current working-tree bytes; filesystem fallback only
  when no usable root Git metadata exists. Never inherit a parent's Git index.
- Exclude derived artifacts and all symlinks deliberately. Nested repositories
  and submodule contents do not expand the root inventory.
- Decode one file at a time, strictly, honoring BOMs and working-tree-encoding
  where available. Unsupported legitimate source encodings fail the run.
- Extensible secret rules return value spans. Preserve placeholders; apply
  replacements only in staged output. Report counts, never matched values.
- Write UTF-8 sections with literal relative paths and original decoded content.
  Keep a private in-memory record of section offsets, sizes and hashes. This is
  needed because source itself may contain lines beginning with `file:`.
- A fresh inventory and read/eligibility pass checks the staged sections against
  current source. Re-scan the completed file, then atomically replace its target.
- Fail on filenames containing line separators/control characters that cannot
  fit the required one-line header. Fail safely on source changes during a run.

## Implementation sequence and ownership

1. Inventory/decoding module and real filesystem/Git tests: tracked membership,
   ignored/tracked precedence, binary/artifact filtering, encodings, symlink and
   submodule boundaries, deterministic normalized paths.
2. Secret module and table-driven tests: contextual assignments, connection
   strings, private keys, provider tokens, placeholders and ordinary identifiers.
3. CLI/launchers and subprocess tests: root discovery, supported Python probing,
   useful safe errors, direct module use, exact exit-code propagation.
4. Snapshot/workspace modules and integration tests: filename containment,
   naming, staging, content fidelity, offsets/hashes, two independent inventories,
   final secret scanning and atomic replacement.
5. Independent review, complete pytest and configured lint, direct/module and
   launcher smoke runs against isolated representative input directories; verify
   deterministic output and unchanged input hashes.

## Review focus

- Parent Git metadata and external gitfiles must never admit outside files.
- Raw header-like source lines cannot be parsed by a naive header regex.
- Failed decoding, source races and output tampering must preserve previous output.
- Detect credential values without logging source or destroying placeholders.
- Output symlinks, reserved filenames and path traversal must fail before writing.

Tests are written and run red before the corresponding implementation. Independent
subsystems can be implemented in parallel; integration and publication stay
sequential. The user explicitly authorized engineering choices and full execution.
