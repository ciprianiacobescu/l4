# Design: which `.l4/` paths are the harness's

## D1. The rule

`_harness_written(path)` with `parts = PurePosixPath(path).parts`:

- `parts[-1] in HARNESS_WRITTEN` (`questions.md`, `verification.md`), as today;
- `".l4" in parts[1:]`: a `.l4` folder below the root, which is a unit folder's (`openspec/changes/<unit>/.l4/…`,
  `.kiro/specs/<name>/.l4/…`; any depth);
- `parts[0] == ".l4"` and `len(parts) > 1` and `parts[1] in HARNESS_ROOT_DIRS`, with `HARNESS_ROOT_DIRS = ("vendor",
  "ci", "bin")`;
- `parts[0] == ".l4-out"`.

Everything else, including `.l4/config.yaml`, `.l4/gates/…` and `.l4/plans/…`, is not harness-written. `_harness_ref`
uses the same function, so a `spec:` or `path:line` reference to the repository's gate script is checked like any
repository file (tracked, regular, quote at the line).

## D2. The reason and the prompt

The discard reason text is `checked <ref> cites a harness-written file (questions.md, verification.md, the harness's
.l4/ files): not evidence` (one constant, used by `check_reply`). The system text's sentence "never `questions.md`,
`verification.md` or anything under `.l4/`, which are written by the harness or by the agent that asked, and prove
nothing" becomes: never `questions.md`, `verification.md`, a unit folder's `.l4/`, the repository's `.l4/vendor/`,
`.l4/ci/` or `.l4/bin/`, or `.l4-out/`, which the harness or the agent that asked wrote and which prove nothing; the
repository's own `.l4/config.yaml`, `.l4/gates/` and `.l4/plans/` are evidence like any of its files. `PROMPT_VERSION`
goes to 5 and the template lock is regenerated (`uv run python -m l4.templatelock --write`).

## D3. What stays

The quote and length rules, `test:` entries, the retry of a reference that does not resolve (delegate-citations), and
everything a judge or the verifier reads.
