# Feedback on a unit: `l4 feedback`

`l4 feedback` writes one file, `feedback.md`, in the unit's spec folder (`openspec/changes/<name>/` or
`.kiro/specs/<name>/`). It never commits, pushes or calls the forge: you run the git lines it prints. The harness takes
each submitted item at the start of its next verification round, does it in a fix unit, has the judge check it, and
shows the result in the PR's note.

## Commands

```sh
l4 feedback add --kind KIND --text "…" [--at PATH[:L[-L]]]… [--env NAME] [--when "…" --then "…"] \
                [--title "…"] [--lesson] [--draft] [--unit FW:NAME]
l4 feedback list [--json]           l4 feedback show FB-001 [--json]
l4 feedback submit FB-002           # a draft → submitted
l4 feedback withdraw FB-002         # not after it was addressed
```

- **Where to run it.** For an open unit, check out its branch first (`git switch l4/<framework>/<name>`); from any
  other branch the command refuses and prints the `git switch` line.
- **`--at`.** It must point at code in the working tree: not `.l4/`, not `.git/`, not a spec folder (any letter case).
  It quotes the lines (at most 40 lines or 4,000 bytes, secrets redacted). Give it up to 5 times.
- **`--text -`** reads standard input.
- **`--draft`** saves the item without sending it.
- **`--lesson`** keeps the request as a lesson for future units once it is addressed.

## Kinds

| Kind | Fix task | Checked by |
|---|---|---|
| `refactor` | A chore. Test files are put back if touched, and at least one other file must change. | The existing tests pass unchanged, and the judge. |
| `duplication` | The same as `refactor`. | The same. |
| `tests` | A test chore: new tests only, and production code may not change. | The new tests pass, and the judge. |
| `config` | Red, then green, against two built criteria: "WHEN NAME is set THEN … use its value instead of the value at `<place>`" and "WHEN NAME is not set THEN … CONTINUE TO behave as before". | The tests, NAME appearing in the changed non-test code, and the judge. |
| `behaviour` | Red, then green, against your `--when`/`--then`. | The tests and the judge. |

**Choosing.**
- A rename, a changed signature, or anything the current tests would have to follow is `behaviour`. Existing tests are
  never deleted, renamed, skipped or weakened by any fix (the integrity check rejects it); new tests are added. For a
  rename, ask for the old name to stay as an alias that the existing tests keep calling.
- `--when` and `--then` describe the new behaviour as one acceptance criterion: a failing test is written for it
  first.
- `config` needs `--at` pointing at the hard-coded value, and `--env`.

## After the push

- **The PR is in review.** The push sends the unit back to work. The harness's approval for the old head no longer
  counts, and the PR goes back to draft. The next run:
  1. takes the submitted items (the round fails at once);
  2. writes a fix unit with one task per item (at most 5; the rest wait for the next round);
  3. lets the agent work;
  4. re-verifies the whole unit.

  When every item is judged addressed in a passing round, the PR is ready again.
- **The unit is still being built.** Items wait for the end of the running round; nothing is interrupted.
- **What `feedback.md` shows.** The harness sets Status `taken` and then `addressed`, with an *Outcome* line giving
  the round, the commit and the judge's evidence.
- **What the PR's note shows.** A *Your feedback* line per item: `submitted (waiting for the next round)`,
  `taken into <fix unit>`, `waiting for the next round (fix unit full)`, `addressed in round N at <sha>`,
  `not addressed in round N: <evidence>`, `invalid: <problem>`, or `withdrawn`.
- **The judge says yes in a round that fails for another reason.** That is evidence only; the item closes in the next
  passing round.
- **The judge says no, or does not answer.** The item is taken again in the next round. If the work was already done,
  the chore completes as `already-done` and the judge looks again.
- **You edit an item's text after it was taken.** It is taken again.

## Limits and special cases

- **Feedback rounds** have their own limit, `feedback.max_rounds` (default 5), apart from the harness's fix rounds. At
  the limit the unit stops (escalated, exit 13); see `operate.md` → resume.
- **Ids.** `FB-4` and `FB-004` are the same item. A second section with the same id is ignored and reported invalid.
- **An item without a Status line** is reported invalid. It is never taken.
- **Follow-up units and fix units take no feedback.** Give it on the parent unit; the command refuses their folders.
- **A merged unit.**
  1. Check out the base branch.
  2. Run `l4 feedback add --unit FW:NAME …`; it writes into the unit's folder there (OpenSpec: the archive folder).
  3. Land that commit on the base the usual way.

  The next base run creates `<name>-followup-<n>` with its own PR. One follow-up is open at a time; newer items wait.
- **Comments on the PR are not read.** Only `feedback.md` is.
