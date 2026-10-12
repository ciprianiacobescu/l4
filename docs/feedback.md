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

## The short version

```sh
git switch l4/kiro/add-reorder-quantity          # the unit's branch
.l4/bin/l4 feedback add --kind refactor \
    --at src/inventory/reorder.py:4-9 \
    --text "Extract the pack rounding into its own helper; the loop is hard to read."
git add .kiro/specs/add-reorder-quantity/feedback.md
git commit -m "feedback(add-reorder-quantity): FB-001 extract the pack rounding"
git push
```

`l4 feedback add` prints the exact `git` lines for your item, so you can copy them.

## The five kinds

Pick the kind by what you want to happen. The kind decides what the agent may change, and how the result is checked.

| Kind | Use it when | What the agent does | How it is checked |
|---|---|---|---|
| `refactor` | the code should be restructured and behave the same | changes production code only; every test file is put back if touched | the existing tests still pass, and the judge confirms the request |
| `duplication` | the same logic is written twice or more | the same as `refactor` | the same as `refactor` |
| `tests` | tests are missing or weak | adds tests; production code is put back if touched | the new tests pass, and the judge confirms the request |
| `config` | a value is hard-coded and should come from an environment variable | writes a failing test first, then the code (red, then green) | the test, the variable's name in the changed code, and the judge |
| `behaviour` | the code should behave differently | red, then green, against the condition you state | the test, and the judge |

### `refactor`

```sh
l4 feedback add --kind refactor --at src/billing/invoice.py:40-72 \
    --text "Split build_invoice into one function per section; it is 30 lines of nested ifs."
```

`--at` is required: it shows where the code is.

### `duplication`

```sh
l4 feedback add --kind duplication \
    --at src/pricing/cart.py:18-25 --at src/pricing/order.py:31-38 \
    --text "Both compute the line total the same way; keep one function and call it from both."
```

Give every copy with its own `--at` (up to five). Alternatively, give one place and name the others in the text.

### `tests`

```sh
l4 feedback add --kind tests --at src/inventory/reorder.py \
    --text "No test covers pack_size 1 or a target of 0."
```

### `config`

```sh
l4 feedback add --kind config --at src/notify/client.py:12 --env NOTIFY_BASE_URL \
    --text "The base URL is hard-coded; read it from NOTIFY_BASE_URL and keep today's URL as the default."
```

`--at` points at the hard-coded value, and `--env` names the variable. From these the harness writes two conditions,
which the agent must make true with a failing test first:
1. When `NOTIFY_BASE_URL` is set, the code uses its value instead of the value at `src/notify/client.py:12`.
2. When it is not set, the code behaves as before.

To state the first condition yourself, add `--when` and `--then`.

### `behaviour`

```sh
l4 feedback add --kind behaviour --at src/inventory/reorder.py:7 \
    --when "PACK_ROUNDING is down" \
    --then "reorder_quantity rounds the shortfall down to whole packs" \
    --text "Some suppliers only accept full packs we already have room for."
```

`--when` and `--then` are required, because they become the acceptance criterion the agent's test must prove.

## Other options

- **`--title "…"`** sets the item's title. By default it is the first line of the text.
- **`--text -`** reads the text from standard input, for longer requests.
- **`--draft`** saves the item without sending it. Send it later with `l4 feedback submit FB-002`.
- **`--lesson`** makes the request a lesson for future units once it is addressed, for example "never hard-code
  endpoints".
- **`--unit kiro:add-reorder-quantity`** names the unit when the checked-out branch is not the unit's branch.
- **`l4 feedback list`** and **`l4 feedback show FB-001`** show the items and their state. Add `--json` for scripts.
- **`l4 feedback withdraw FB-002`** takes back an item. An item already taken is no longer checked, but its task still
  runs.

You can also edit `feedback.md` by hand. The file explains its own format at the top. An item is read only when its
**Status** is `submitted`.

## What happens after the push

- **The pull request is ready (in review).** Your push sends the unit back to work, and any approval for the old head
  is dropped.
  1. The next round takes every submitted item and writes a fix unit, with one task per item (at most five at a time).
  2. The agent works through the tasks.
  3. The unit is verified again, and the judge checks each of your items.
  4. When all of them are addressed and the rest of the verification passes, the pull request is ready again.
- **The unit is still being built.** Your items wait until the round in progress ends. Nothing is interrupted.
- **An item is not addressed.** It comes back as a finding, and the next round works on it again. The note says why.
- **You change an item's text after it was taken.** It is taken again.
- **The unit was already merged.** Run `l4 feedback add --unit …` on the base branch and get that commit onto the base
  branch as usual. The next run on the base branch creates a follow-up unit `<name>-followup-1` with its own pull
  request.

The note on the pull request has a **Your feedback** section, with one line per item: submitted, taken, waiting,
addressed (with the round and the commit), not addressed (with the reason), or invalid (with the problem).

## Limits

- **Feedback rounds** have their own limit, `feedback.max_rounds` in `.l4/config.yaml` (default 5). They do not use up
  the fix rounds the harness keeps for its own failures. At the limit the unit stops (escalated). A member can grant
  more with `l4 resume --unit … --extend-feedback-rounds 2` or with the resume label.
- **A refactor that needs a test change cannot pass**, because test files are frozen for `refactor` and `duplication`.
  An example is renaming a public function that tests call. Send it as `behaviour` instead and say what the new name or
  signature must be.
- **Agents cannot edit `feedback.md`.** A change by an agent is put back.
- **Comments on the pull request are not read.** Use the command or the file.
