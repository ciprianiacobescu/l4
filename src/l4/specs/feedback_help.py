"""The `--help` texts of `l4 feedback` (L4-FBK-003): what each kind means, which options it needs, one example each.

Kept apart from `feedback_cli` so the click shell can read them without importing the command. A `\\b` line keeps
click from re-wrapping the block after it.
"""

GROUP_HELP = """Ask for changes to the code of an open unit, in its feedback.md.

The harness reads feedback.md at its next verification round, turns every submitted item into a fix task, does it
and checks that each item was addressed. These commands only edit feedback.md in the unit folder: they never commit,
push or call the forge. After `add`, run the three git lines it prints to send the request.

The unit is --unit ID, else the one named by the checked-out branch l4/<framework>/<name>.

\b
Kinds (--kind):
  refactor     restructure code, same behaviour. Needs --at. Tests stay as they are.
  duplication  merge repeated code, same behaviour. Needs --at (name every place).
  tests        missing or weak tests. Takes no --env, --when or --then.
  config       a hard-coded value becomes an environment variable. Needs --at and --env NAME.
  behaviour    the code should behave differently. Needs --when and --then.

\b
Examples:
  l4 feedback add --kind refactor --at src/inventory/reorder.py:4-9 \\
      --text "extract the rounding into a helper"
  l4 feedback add --kind duplication --at src/a.py:10-30 --at src/b.py:12-32 \\
      --text "the same validation is written twice; keep one"
  l4 feedback add --kind tests --text "reorder_quantity has no test for a zero shortfall"
  l4 feedback add --kind config --at src/inventory/reorder.py:7-9 --env PACK_ROUNDING \\
      --text "read the rounding mode from PACK_ROUNDING (up or down), default up"
  l4 feedback add --kind behaviour --when "stock is below the reorder point" \\
      --then "reorder_quantity returns whole packs" --text "round the shortfall up to whole packs"

\b
After add:
  git add <file> && git commit -m "feedback(<name>): FB-001 <title>" && git push
  l4 feedback list | show FB-001 | submit FB-001 | withdraw FB-001
"""

ADD_HELP = """Add an item to feedback.md and print the git lines that send it.

The command only edits feedback.md (it creates it when missing); commit and push to send. Nothing is written when
the item is refused (exit 2).

\b
What each kind needs:
  refactor     --at (1 to 5). Same behaviour, production code only; the tests are not changed.
  duplication  --at (name every place). Same behaviour, production code only.
  tests        nothing more. Missing or weak tests; production code is not changed.
  config       --at and --env NAME (capital letters, digits, _). The value written at --at is read from NAME.
               --when and --then (both) replace the generated first scenario.
  behaviour    --when and --then. You write the criterion; the harness proves it red, then green.

\b
--at PATH[:L[-L]]: a file of this repository, as it is in your working tree (not under .l4/ or the spec folders).
The lines named are quoted into the item (at most 40 lines or 4,000 bytes, secrets redacted). Up to 5 times.

--text takes the request; --text - reads standard input. --title defaults to the first line of the text (72
characters). --draft writes Status draft: the harness ignores it until `l4 feedback submit`. --lesson asks that a
lesson be kept once the item is addressed.

\b
Examples:
  l4 feedback add --kind refactor --at src/inventory/reorder.py:4-9 \\
      --text "extract the rounding into a helper"
  l4 feedback add --kind duplication --at src/a.py:10-30 --at src/b.py:12-32 \\
      --text "the same validation is written twice; keep one"
  l4 feedback add --kind tests --text "reorder_quantity has no test for a zero shortfall"
  l4 feedback add --kind config --at src/inventory/reorder.py:7-9 --env PACK_ROUNDING \\
      --text "read the rounding mode from PACK_ROUNDING (up or down), default up"
  l4 feedback add --kind behaviour --when "stock is below the reorder point" \\
      --then "reorder_quantity returns whole packs" --text "round the shortfall up to whole packs"
"""

LIST_HELP = "List the items of a unit's feedback.md: id, status, kind, first place, title (and what makes one invalid)."
SHOW_HELP = "Show one item (FB-NNN) as the file holds it. With --json: its fields, its problems and its content hash."
SUBMIT_HELP = (
    "Set a draft item (FB-NNN) to submitted, so the next verification round takes it. Commit and push to send it."
)
WITHDRAW_HELP = (
    "Set an item (FB-NNN) to withdrawn: the harness never takes it, or stops judging it. Commit and push to send it."
)
