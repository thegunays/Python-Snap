# Repository snapshot implementation plan

The supplied specification is the design brief. The Python 3.12+ package uses the
standard library at runtime; its original behavioral tests used pytest and were
later removed at the user's request. No source analysis, networking, Git mutation,
commits, or writes under input are permitted.

## Design decisions

- Fixed workspace input/output boundaries; default project root comes from the
  source checkout (including editable installs), or the current directory for a
  regular installed CLI.
- Treat input as a repository container. Select its own exact Git root or one
  independent descendant Git root, without traversing links or parents. Without
  Git, unwrap one meaningful repository directory while retaining conventional
  source layouts. Reject ambiguous independent candidates with relative paths
  stripped of control characters.
- Git index membership with current working-tree bytes; filesystem fallback only
  when no usable root Git metadata exists. Never inherit a parent's Git index.
- Exclude derived artifacts and all symlinks deliberately. Nested repositories
  and submodule contents inside the selected repository do not expand its inventory.
- Decode one file at a time: prefer BOMs and working-tree-encoding, then UTF-8,
  then the project-wide fallback (default cp1254, selectable by CLI). Recover
  remaining undecodable characters with U+FFFD. Damaged BOM-marked Unicode and
  declared or detected UTF-16/UTF-32 retain their encoding. Recover unusable per-file
  metadata, but reject invalid CLI fallback codecs. Deduplicate recovery warnings
  per file across all passes.
- Preserve eligible decoded source values unchanged. Apply no secret detection or
  masking to source content, source/output names, CLI labels, or diagnostics.
- Write UTF-8 sections with literal relative paths and original decoded content.
  Keep a private in-memory record of section offsets, sizes and hashes, plus raw
  source-byte hashes so lossy decoding cannot conceal source changes. Boundaries
  are needed because source itself may contain lines beginning with `file:`.
- A fresh inventory and read/eligibility pass checks the staged sections against
  current source. Recheck repository selection and wrapper identities before
  validation and publication. Verify completed section byte bounds and hashes,
  then atomically replace its target. All source paths are relative to the selected
  repository.
- Fail on filenames containing line separators/control characters that cannot
  fit the required one-line header. Fail safely on source changes during a run.

## Original implementation sequence and ownership

1. Inventory/decoding module and real filesystem/Git tests: tracked membership,
   ignored/tracked precedence, binary/artifact filtering, encodings, symlink and
   submodule boundaries, deterministic normalized paths.
2. Original secret module and table-driven tests (subsequently removed): contextual
   assignments, connection strings, private keys, provider tokens, placeholders
   and ordinary identifiers.
3. CLI/launchers and subprocess tests: root discovery, supported Python probing,
   useful safe errors, direct module use, exact exit-code propagation.
4. Snapshot/workspace modules and integration tests: filename containment,
   naming, staging, content fidelity, offsets/hashes, two independent inventories,
   final byte-integrity verification and atomic replacement.
5. Independent review, complete pytest and configured lint, direct/module and
   launcher smoke runs against isolated representative input directories; verify
   deterministic output and unchanged input hashes.

## Review focus

- Parent Git metadata and external gitfiles must never admit outside files.
- Raw header-like source lines cannot be parsed by a naive header regex.
- Unreadable source, source races and output tampering must preserve previous output.
- After decoding, preserve eligible text without further rewriting. Fallback
  selection applies project-wide and does not guess each file's encoding.
- Output symlinks, reserved filenames and path traversal must fail before writing.

Original tests were written and run red before the corresponding implementation.
Independent subsystems were implemented in parallel; integration and publication
remained sequential. The user explicitly authorized engineering choices and full execution.
