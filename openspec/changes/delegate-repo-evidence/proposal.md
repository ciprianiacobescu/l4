# A repository's own `.l4/` files are evidence for the delegate

## Why

In a consumer delivery plan the delegate answered two questions about the repository's gates by citing the gate
scripts the repository wrote, `.l4/gates/test.sh:44` and `.l4/gates/lint-go.sh:11`. Both replies were discarded as
`cites a harness-written file (questions.md, verification.md, .l4/): not evidence`, the questions went to a person and
the plan stopped [V, ledger `delegate.result`]. `_harness_written` counts any path with a `.l4` part as the harness's
(`".l4" in parts`) [V, code], but a repository's root `.l4/` holds files people write and commit: `.l4/config.yaml`,
`.l4/gates/` (the gate scripts), `.l4/plans/`. What the harness writes there is `.l4/vendor/` (a vendored harness),
`.l4/ci/` (a rendered CI file) and `.l4/bin/` (the shim); its run records live in each unit folder's `.l4/` (ledger,
evidence) and in `.l4-out/`.

## What Changes

- A `checked` entry is harness-written when its file is `questions.md` or `verification.md`, when its path has a `.l4`
  part after the first part (a unit folder's `.l4/`, for example `openspec/changes/<unit>/.l4/ledger/…`), when it is
  under `.l4/vendor/`, `.l4/ci/` or `.l4/bin/`, or when its first part is `.l4-out`. Every other path under the
  repository's `.l4/` (`.l4/config.yaml`, `.l4/gates/…`, `.l4/plans/…`) is the repository's own and may be cited.
- The discard reason becomes `checked <ref> cites a harness-written file (questions.md, verification.md, the
  harness's .l4/ files): not evidence`.
- The prompt (`delegate@5`) says which `.l4/` files are no evidence and that the repository's configuration, gate
  scripts and plans are.

## Impact

- Code: `l4.delegate.reply` (`_harness_written`, the reason text), `l4.delegate.prompt` (the rule, `PROMPT_VERSION`
  5), the template lock.
- Security: what the harness and the asker write stays excluded; the change admits only files a person commits, which
  the quote rule still checks word for word at the unit head.
- Docs: L4-DLG-005, SCN-DLG-120 and SCN-DLG-121, change-table row 79, CHANGELOG.
