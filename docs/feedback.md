# Asking for changes: `l4 feedback`

When a unit's pull request or merge request is open, you can ask for changes to its code, for example:
- a function that should be refactored;
- code that is duplicated;
- a hard-coded value that should come from an environment variable;
- tests that are missing;
- behaviour that should be different.

You write the request with one command, then commit and push. The harness does the rest:
1. It takes your request at the start of its next verification round.
2. It turns it into a task of the right kind.
3. An agent does the task.
4. The judge checks that your request was addressed.
5. The pull request goes back to ready, and the note on it shows what happened to each request.

The command only edits one file, `feedback.md` in the unit's folder. It never commits, pushes or talks to the forge.
`l4 feedback --help` lists the kinds with an example each, and every subcommand has its own `--help`.

## The short version

```sh
git switch l4/kiro/add-reorder-quantity          # the unit's branch
.l4/bin/l4 feedback add --kind refactor \
    --at src/inventory/reorder.py:4-9 \
    --text "Extract the pack rounding into its own helper; the loop is hard to read."
git add .kiro/specs/add-reorder-quantity/feedback.md
git commit -m "feedback(add-reorder-quantity): FB-001 Extract the pack rounding into its own helper; the loop is hard to read."
git push
```

`l4 feedback add` prints the item's id and status (`FB-001 submitted`), the file, and the exact `git add`, `git commit` and
`git push` lines for your item, so you can copy them. It refuses a bad item with exit code 2 and writes nothing, for
example a `behaviour` item without `--when` and `--then`, or an `--at` that names a line the file does not have.

## The five kinds

Pick the kind by what you want to happen. The kind decides what the agent may change, and how the result is checked.

| Kind | Use it when | What the agent does | How it is checked |
|---|---|---|---|
| `refactor` | the code should be restructured and behave the same | changes production code only; every test file it touches is put back | every gate passes on the original tests, and the judge confirms the request |
| `duplication` | the same logic is written twice or more | the same as `refactor` | the same as `refactor` |
| `tests` | tests are missing or weak | adds tests only; a change to production code fails the attempt | the new tests pass, and the judge confirms the request |
| `config` | a value is hard-coded and should come from an environment variable | writes a failing test first, then the code (red, then green) | the test, the variable's name in the changed code, and the judge |
| `behaviour` | the code should behave differently | red, then green, against the condition you state | the test, and the judge |

### `refactor`

```sh
l4 feedback add --kind refactor --at src/billing/invoice.py:40-72 \
    --text "Split build_invoice into one function per section; it is 30 lines of nested ifs."
```

`--at` is required: it shows where the code is. The lines it names are quoted into the item (at most 40 lines or 4,000
bytes, with secrets redacted). If the agent changes only test files, the attempt fails with `nothing changed`.

A rename, or any change the existing tests would have to follow, is `behaviour` (with `--when` and `--then`), not
`refactor`: `refactor` puts test files back, so the attempt fails.

### `duplication`

```sh
l4 feedback add --kind duplication \
    --at src/pricing/cart.py:18-25 --at src/pricing/order.py:31-38 \
    --text "Both compute the line total the same way; keep one function and call it from both."
```

Give every copy with its own `--at` (up to five). Alternatively, give one place and name the others in the text. Like
`refactor`, it needs at least one `--at`.

### `tests`

```sh
l4 feedback add --kind tests --at src/inventory/reorder.py \
    --text "No test covers pack_size 1 or a target of 0."
```

`--at` is optional here. `tests` takes no `--env`, `--when` or `--then`.

### `config`

```sh
l4 feedback add --kind config --at src/notify/client.py:12 --env NOTIFY_BASE_URL \
    --text "The base URL is hard-coded; read it from NOTIFY_BASE_URL and keep today's URL as the default."
```

`--at` points at the hard-coded value, and `--env` names the variable (capital letters, digits and `_`). From these the
harness writes two conditions, which the agent must make true with a failing test first:
1. WHEN the environment variable `NOTIFY_BASE_URL` is set THEN the system SHALL use its value instead of the value
   written at `src/notify/client.py:12`.
2. WHEN `NOTIFY_BASE_URL` is not set THEN the system SHALL CONTINUE TO behave as before this change.

To state the first condition yourself, add `--when` and `--then` (both, or neither). The judge's "addressed" is not enough
for a `config` item: the variable's name must also appear in a non-test file the fix changed.

### `behaviour`

```sh
l4 feedback add --kind behaviour --at src/inventory/reorder.py:7 \
    --when "PACK_ROUNDING is down" \
    --then "reorder_quantity rounds the shortfall down to whole packs" \
    --text "Some suppliers only accept full packs we already have room for."
```

`--when` and `--then` are required, because they become the acceptance criterion the agent's test must prove.

## Other options

- **`--title "…"`** sets the item's title. By default it is the first line of the text, cut at 72 characters.
- **`--text -`** reads the text from standard input, for longer requests.
- **`--draft`** saves the item with Status `draft`, which the harness never reads. Send it later with
  `l4 feedback submit FB-002` (only a valid draft can be submitted), then commit and push.
- **`--lesson`** makes the request a lesson for future units once it is addressed in a round that passes, for example
  "never hard-code endpoints". The lesson is titled `Human feedback: <your text>`, and the same request on two units
  reinforces one lesson.
- **`--unit kiro:add-reorder-quantity`** names the unit when the checked-out branch is not a unit branch. A unit that
  is still open takes its feedback on its own branch: from another branch the command exits 2 and prints the
  `git switch l4/<framework>/<name>` line. A unit that was already merged is the exception (see below).
- **A follow-up unit or a fix unit takes no feedback of its own.** `add`, `submit` and `withdraw` on its folder exit 2
  and name the parent unit: give the feedback on the parent.
- **`l4 feedback list`** and **`l4 feedback show FB-001`** show the items as the file holds them (id, status, kind,
  first place, title, and what makes an item invalid). Add `--json` for scripts.
- **`l4 feedback withdraw FB-002`** takes back an item, then commit and push. An item not yet taken is never taken. An
  item already taken is no longer checked, but its task still runs. An `addressed` item cannot be withdrawn.

You can also edit `feedback.md` by hand. The file explains its own format at the top. An item is read only when its
**Status** is `submitted`.

Ids are written `FB-NNN`; a short id is read as the same item, so `FB-4` is `FB-004` (in a heading, an index row or a
command). If two sections end up with the same id (a bad merge, a copied section), the first one is the item. The
others are never taken, and the note and the run log report each once as `invalid: duplicate id FB-004`. An item whose
**Status** line you deleted is reported as `invalid: no Status line`; put the line back (`submitted`) to send it.

## What happens after the push

- **The pull request is ready (in review).** Your push sends the unit back to work: the harness only counts an
  approval given for the hand-off head, so your push voids it (the approval label is removed) and the pull request goes
  back to draft.
  1. The next round takes every submitted item and writes a fix unit, with one task per item. Your request comes first in
     the fix unit's proposal (OpenSpec) or `bugfix.md` (Kiro), as `Requested by <you> in FB-001 (…)`. The item's Status in
     `feedback.md` becomes `taken`, and its *Outcome* block names the fix unit.
  2. The agent works through the tasks, at most five at a time. An item past the fifth waits for the next round.
  3. The unit is verified again, and the judge checks each of your items.
  4. When all of them are addressed and the rest of the verification passes, the pull request is ready again.
- **The unit is still being built.** Your items wait until the round in progress ends. Nothing is interrupted.
- **An item is not addressed.** It comes back as a finding (`FB-001 not addressed: …`), and the next round works on it
  again. The note says why. When it is addressed, its Status becomes `addressed` and its *Outcome* block says
  `Addressed in round N at <commit>: <evidence>`.
- **The judge says yes in a round that fails for another reason.** The item is not closed yet: a later fix unit could
  undo the change. It stays `taken` (the note keeps saying `taken into <fix unit>`), and that round's `verification.md`
  lists it under `## Feedback` as `FB-001: judged addressed, pending a PASS round`. Only a round that passes sets
  `addressed` and writes the *Outcome* line. If the judge does not answer for the item at all, a round that would
  pass fails with `FB-001 not addressed: not judged in this round`, and the item is taken again.
- **An item comes back and there is nothing left to do.** When the item was taken before and the change is already in the
  code (the judge simply left it out of its reply), the agent has nothing to change. A refactor or a test request that
  was taken before then completes with no change (the run log says `task 1.1 done: retaken FB-001: nothing left to
  change`) instead of failing, and the unit is checked again, so the judge looks at the item once more. A first take that
  changes nothing still fails, and an item whose text you changed counts as new.
- **You change an item's text after it was taken.** It is taken again.
- **The unit was already merged.** Check out the base branch and run `l4 feedback add --unit <framework>:<name> …`. It
  writes `feedback.md` into the unit's folder there (the newest `openspec/changes/archive/<date>-<name>/` when
  archived, else the change folder; `.kiro/specs/<name>/` for Kiro). Land that commit on the base branch by your usual
  route. The next base run (`l4 run` or the scheduled sweep) creates the follow-up unit `<name>-followup-<n>` on its own
  branch with its own pull request, with one task per item as above; the items' Status becomes `taken` (*Outcome*:
  `Taken into <name>-followup-<n>`). Only one follow-up is open for a unit at a time; newer items wait
  (`waiting for the next round (follow-up open)`) until it merges. Give later feedback on the parent unit, not on the
  follow-up's pull request: the follow-up takes none of its own. A unit that was abandoned takes none.

The note on the pull request has a **Your feedback** section, with one line per item (`FB-001 refactor src/x.py:4 — …`).
After the dash the line says one of:
- `draft (not sent)`;
- `submitted (waiting for the next round)`, or `submitted (changed after round N; waiting for the next round)` for an
  item you edited after it was taken;
- `taken into <fix unit>` (or `<follow-up>`);
- `waiting for the next round (fix unit full)` or `waiting for the next round (follow-up open)`;
- `addressed in round N at <commit>` (the first ten characters of the commit);
- `not addressed in round N: <why>`;
- `invalid: <the problem>`, for example `invalid: config needs Env`;
- `withdrawn`.

A section has at most 30 lines; the rest are counted as `and N more in feedback.md`.

Every note of a unit in review also ends with a hint line (the note of a follow-up or a fix unit instead ends with one
line saying that feedback goes to the parent unit's `feedback.md`):
`To ask for changes: l4 feedback add --kind refactor|duplication|tests|config|behaviour --at FILE:LINE --text "…", then commit and push (docs/feedback.md).`
`verification.md` has a `## Feedback` section for the items taken or judged in each round, and `l4 status` shows a
FEEDBACK column with the count of items per state.

## Limits

- **Feedback rounds** have their own limit, `feedback.max_rounds` in `.l4/config.yaml` (default 5). They do not use up
  the fix rounds the harness keeps for its own failures. `max_rounds: 0` turns taking off. At the limit the unit stops
  (escalated; the run exits 13) with the note `feedback round limit reached (5)`. A member can grant more with
  `l4 resume --unit … --reason "…" --extend-feedback-rounds 2`, or one more round with the `l4:resume` label.
- **A refactor that needs a test change cannot pass**, because test files are frozen for `refactor` and `duplication`.
  An example is renaming a public function that tests call. Send it as `behaviour` instead and say what the new name or
  signature must be.
- **Agents cannot edit `feedback.md`.** A change by an agent is put back.
- **One fix unit holds at most five tasks.** More items than that wait for the next round and stay submitted.
- **A request is kept whole up to 1,200 characters** in the fix task. `feedback.md` is read up
  to 2 MiB.
- **Comments on the pull request are not read.** Use the command or the file.
