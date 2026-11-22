## Context

Read at 0.4.59 (62188257):

- `verifier/generate.py` `_discriminates` (182-222) runs the generated file at the merge base, then at the head
  (`_head_run`, 154-179, only the generated file is collected: `collect_only_env`). A head run with a failing test of
  the file returns `_Verdict("fails_at_head", "the test fails at the head: <ids>", artifacts, ...)` (213-221); the
  head report (`at_head.report`) is then dropped. `generate_ui_test` (225-297) keeps the reply's code in `code` (274),
  writes it to both trees (277-279), drops the file again unless it was accepted (285-288), builds the outcome with the
  raw code (251-255) and, on a retry, sets `retry_reason = last.reason` (296).
- `verifier/types.py` `GeneratedOutcome` (197-223): `code` is "the last test written: the evidence for a test that
  fails at the head" (206); `GenStatus` (190-193).
- `verifier/report.py`: `MAX_CODE_CHARS = 4_000` (65); `_generated_rows` (111-127) and `_links` (85-90) show the path
  and the artefact paths; `_generated_json` (352-360) stores `code` cut at 4,000 characters for an outcome that was not
  accepted; `write_round_evidence` (414-438) redacts the whole verdict afterwards (427).
- `verifier/evidence.py` `_generated` (168-176) restores an outcome with `GeneratedOutcome(**d)`: every stored key must
  be a field.
- `verifier/verdicts.py`: `_ui_hold_lines` (672-686) adds `Step 5 for C-…: <status> after <n> attempt(s); <reason>`
  (reason cut at 300) to the hold's Context; `_hold_question` (689-750) builds the `NewQuestion` with no `notes`;
  `_hold_finding` (225-265) makes a rejected hold of kind `other` a major finding titled `Rejected hold: <hold>`
  (261), deterministic when the reason ends with a `WHEN … THEN …`, else the human's, with no `criterion`;
  `settle_holds` (268-306) adds it only when no finding of the round has its id yet (300-305).
- `specs/questions.py`: `NewQuestion.notes` (59-70) is written as its own `### Harness notes` subsection
  (`_render_section`, 125-146) through `_block` (94-97), which redacts and backslash-escapes a line that matches
  `_STRUCTURAL` (47). `clarifier/ports.py` `QuestionView.context` (52-56) is the Context followed by the notes.
- `implementer/excerpt.py`: `failure_excerpt` (112-152) is the retry prompt's excerpt (8 lines per test, 8 tests, 40
  lines, 3,000 characters; the body redacted whole before a line is dropped, paths made relative, the result redacted
  again); `_redact_keys` (48-57) and `_cut_at_line` (60-67). `implementer/tdd.py` `excerpter` (639-644) calls it with
  `tmp_root=wb.unit_cache / "gate-tmp"`.
- `verifier/fixunit.py` `_candidates` (217-319): a FAIL round picks the deterministic, human and feedback blockers and
  majors, then adds a synthetic `Criterion … fails` finding for each failing criterion that no picked finding cites
  (232-238); the picked findings are sorted only by "joins a gate finding" (252); a human finding with no criterion and
  no scenario is skipped (270-278); the group key is the criterion, else the finding's id (289); the scenarios of a
  group are deduplicated by text (315-317). `plan_fix_unit` names a scenario by its WHEN clause in a synthetic group,
  else by the finding's title (425); `_requirement_for` (357-375).
- `delegate/prompt.py`: evidence is the repository, the unit's spec and the report's test ids, never `questions.md`,
  `verification.md` or a unit folder's `.l4/` (70-77); `_generated_row` (482-491).

## Goals / Non-Goals

**Goals:** whoever answers a UI hold sees the test step 5 wrote and why it failed at the head; the writer's second
attempt sees that too; one rejected behaviour gives one fix task. Every piece is bounded and redacted before it is cut.

**Non-Goals:** the hold's text, id and accept binding (L4-VER-067); what an answer settles; the ledger; the writer's
template; the traces and screenshots; the context the writer gets on its first attempt (D7).

## Decisions

### D1. What step 5 keeps of a test that is not accepted

`_Verdict` gains `excerpt: str = ""`. In the `fails_at_head` branch of `_discriminates` (213-221) it is
`failure_excerpt(at_head.report, failing, worktree=wb.worktree, tmp_root=wb.unit_cache / "gate-tmp",
redact=wb.redactor.redact_text)`: the retry prompt's excerpt (`tdd.excerpter`), per failing test of the generated file
its `E` lines, the deepest repository frame's `>` line and its location and the last location, at most 8 lines per
test, 8 tests, 40 lines and 3,000 characters. The head run collects the generated file only, so the excerpt is about
the generated tests and nothing else. No other status gets one.

`GeneratedOutcome` gains `excerpt: str = ""` as its last field (the positional call at 252-255 stays valid). The
`outcome` closure of `generate_ui_test` passes `verdict.excerpt` and, as `code`, the evidence copy of the code:
`_redact_keys(redact, _cut_at_line(_redact_keys(redact, code), MAX_CODE_CHARS))` with `redact =
wb.redactor.redact_text` and `MAX_CODE_CHARS = 4000` (`report.py:65`; move the constant where both modules read it).
That is: the whole code redacted (and a private-key block with one marker removed to the edge, L4-VER-078), then cut at
the last line end before 4,000 characters (a single longer line at 4,000), then redacted again. A cut after the
redaction can only drop text, never uncover it. Give the helper a public name in `l4.implementer.excerpt` (not starting
with `test`), for example `redacted_cut(text, redact, limit)`. The raw code is still what is written to the trees (278,
292) and hashed (293): only the outcome's copy is bounded. The code and the excerpt of an outcome always come from the
same attempt: the closure takes both from the last `_Verdict` and the last reply.

### D2. `verdict.json` and a reused round

`_generated_json` keeps `excerpt` when it is not empty and deletes the key when it is, as it does for `code`. `code`
stays `"" if g.accepted else g.code[:MAX_CODE_CHARS]`, a no-op cut of a copy that D1 bounded and redacted, and
`write_round_evidence` redacts the whole object again (the third pass). This fixes the order of 0.4.59, which cut the
raw code and redacted after the cut.

`evidence._generated` needs no change: a 0.4.59 record has no `excerpt` and restores with `""`; its `code` is the copy
0.4.59 stored and is shown as it is (the question's writer redacts it again). An older harness never reads a 0.4.60
verdict. `verify.generated` in the ledger is unchanged: the excerpt and the code are in `verdict.json` only.

### D3. The hold's question

`_hold_question` (689-750) passes `notes=_ui_hold_notes(ui, generated)` for a UI hold. `_ui_hold_notes(criterion,
generated) -> str` finds the criterion's outcome as `_ui_hold_lines` does and returns `""` when there is none or it
has neither an excerpt nor (code and a path). Else the lines, joined by `\n`:

- when `excerpt`: `Harness note: why the test step 5 wrote failed at the head (redacted; paths relative to the
  repository):`, an empty line, and each line of the excerpt after four spaces;
- when `code` and `path`: an empty line when an excerpt came before, `Harness note: the test step 5 wrote at its last
  attempt, <path> (<status>; not committed, the file is removed after the run; at most 4,000 characters):`, an empty
  line, and each line of the code as four spaces, its number right-aligned in four columns, two spaces and the line
  (an empty line of code is its number alone).

`_ui_hold_lines` adds one sentence to the Context when the notes are not empty: with an excerpt, `The harness notes
below show the test step 5 wrote and why it failed at the head: read them to tell a wrong test from wrong code.`;
without one, `The harness notes below show the test step 5 wrote.`

Why the notes and not the Context: as in L4-IMP-102 (its D6), what an accepted suggestion may unfreeze is judged
against the title, the Context and the Options (L4-IMP-015), and text that a model wrote or a test printed must not
count as "the question names it". Why not the hold's text: its hash is the hold's id and the accept is bound to it
(L4-VER-067); the notes change from round to round. `question.raised` and its `text_sha256` are unchanged.

Rendering, checked with a probe of `raise_questions` and `QuestionsFile.load`: a numbered code line starts with spaces
and a digit, so `_STRUCTURAL` never matches it and `_block` escapes none; `_SUBHEADING`, `_HEADING_ID`, `_ROW_ID` and
the index markers are anchored at the line start and `_FENCE` allows at most three spaces, so no line of the code can
open a subsection, a question, a fence or an index row. A test whose lines held `## Q-900:`, `### Answer`, `---`, a
fence, `| a | b |`, `- **Status:** answered` and `<!-- write below this line -->` was written with no escaped line,
parsed back with the same five subsection headings, and `unescape_text(notes_text)` returned the notes unchanged. In
Markdown the block is an indented code block that shows the numbers, which match the locations of the excerpt. An
excerpt line is indented by four spaces; one that starts with a structural mark after them (possible only in a
message-only excerpt) is backslash-escaped by `_block` and shows as text.

The delegate reads `QuestionView.context`, the Context and then the notes, so it sees both. It cannot cite the
generated test: the file is not in the tree, and `questions.md`, `verification.md` and `.l4/` are no evidence
(`delegate/prompt.py:70-77`). It checks what the test's premise is about in the repository (the routes the product
serves, the code that reads the session, the e2e suite's support files) and cites that as `path:line`. The delegate's
prompt and `_generated_row` do not change, so no template or lock changes.

### D4. `verification.md`

After `## Generated UI tests` (`report.py:296-297`), `render_verification_md` adds `## Generated UI tests that were not
accepted` when an outcome that is neither accepted nor waived has an excerpt, or code and a path. For each such
outcome: a list item `- <criterion> (<status> after <n> attempt(s)): `<path>``, an empty line, then every line of the
block indented by six spaces (an indented code block inside the list item, as L4-IMP-102 writes its block into an
OpenSpec proposal): `Failure at the head:` and the excerpt's lines after two more spaces, when there is an excerpt;
then `The test (at most 4,000 characters):` and the numbered code lines of D3. The file is redacted and scrubbed whole
as before (`report.py:426`). The delegate's `verification_section` (`delegate/prompt.py:413-417`) picks the lines that
name a target: the item's line names the criterion, and a code line that holds the criterion's id (its `l4` mark) is
picked too, within the 50-line bound.

### D5. The writer's retry (L4-VER-084)

At 296: when `last.status == "fails_at_head"` and `last.excerpt`, `retry_reason = f"{last.reason}\nWhy it failed at
the head:\n{last.excerpt}"`; any other status keeps `last.reason`. It is the prompt's `retry reason` data block
(`testwriter.py:145-146`), and `build_writer_prompt` redacts the whole user text. The template and `testwriter@7` stay,
and `templates.lock.json` is untouched: the retry reason is data.

Fail safe: the second test still has to fail at the base and pass at the head; what the writer reads never changes
what is accepted. Named risk: a writer that sees why its test failed can write one that passes by asserting less. The
judge's adequacy review of an accepted generated test (step 9) stands before a PASS, as for any generated test; a retry
already carries that risk today with less to go on.

### D6. Not done: a wait timeout at the head as a writer failure

Recommended no:

1. It removes no hold. `unclosed_holds` (`ui_step.py:170-182`) holds every outcome but `accepted`, `waived` and a
   `not_testable` that step 4 covers, `writer_failed` included, and both statuses already get the retry (294-296).
2. A wait that times out for an element that never appeared is also how Playwright reports a behaviour the product
   does not have. The label would tell the reader "the test is wrong" exactly where the product may be wrong, and push
   an accept, which waives step 5 for the criterion (L4-VER-067).
3. It would read Playwright's message wording, which changes across versions.

The excerpt of D1 shows the timeout and the locator, which is what the reader needs to decide.

### D7. Not done here: an existing passing e2e test as the writer's context

Today the writer gets the scenario, the UI diff (30,000 characters), the head page snapshot (30,000) and the suite's
support files at the merge base (`e2e/conftest.py` and helper modules, six files and 20,000 characters, L4-VER-077).
Test modules are left out on purpose (`conventions.py:170`; SCN-VER-306 pins it). The premise errors of the evidence
(how a session is set up, a route prefix, what the session call returns) are what an existing test of the same page
shows. Recommended as a follow-up with its own requirement: one e2e test module at the merge base that the unit did
not change, picked deterministically (the module whose tests trace the most criteria of the gap's requirement, then
the first by path), cut at 8,000 characters, after the support files; the e2e rules name it (`testwriter@8` and its
lock entry). Cost: about 60-90 lines in `conventions.py` and `generate.py`, two test files, up to 8,000 more characters
per writer call. Why later: it changes the writer's template and SCN-VER-306, and the retry of D5 may fix most premise
errors on the second attempt. Measure that first.

### D8. One behaviour, one fix task (L4-VER-085)

`_hold_finding`: for a UI hold (`ui_hold_criterion(hold)`, `verdicts.py:112-115`, gives `C`) the finding gets
`criterion=C`, whether it is deterministic (a reason with a `WHEN … THEN …`) or the human's. Its title, detail,
severity, source and id (`hold_id(hold)`) do not change. `is_ui_hold_finding(f) = f.id.startswith("H-") and
f.criterion is not None` (in `verdicts.py`): only `_hold_finding` of a UI hold gives an `H-` finding a criterion.

`_candidates`:

1. `cited` (232) leaves out UI hold findings, so a failing criterion keeps its `Criterion … fails` finding even when its
   hold's finding cites it.
2. The sort (252) takes the key `(f.id in joined, is_ui_hold_finding(f))` (stable), so a UI hold's finding comes after
   the criterion's own finding and joins its task (`| <title>: <detail>`, 297-298); the criterion's finding gives the
   task its title and detail.
3. The skip of 270-278 also takes a UI hold finding whose criterion has no reject in force (`criterion not in
   rejects`) and that gives no scenario: a UI hold rejected alone without a `WHEN … THEN …` stays the human's finding,
   not converted, as today. Without this a criterion would turn it into a red/green task with nothing to pin.
4. A scenario that a UI hold finding contributes is named after its criterion's scenario (`by_id[C].scenario`) instead
   of the finding's title: `cand.scenarios` takes that name in the place of the title. The text is the reason's
   `WHEN … THEN …` as before.

What follows, read through the code:

- The criterion and its UI hold both rejected in the round: one group keyed by `C` (289). `_verdicts_of` (198-204)
  gives the synthetic finding the criterion's reject and the hold's finding both rejects, each question once, so
  `decisions` holds both reasons (the criterion's first) and `consumed` both questions. Scenarios are deduplicated by
  text after `when_then` folds whitespace (174-180, 315-317): the same text is pinned once; two different texts are
  both pinned, in the one task. No other matching: a person's scenario is never dropped. A synthetic group names its
  scenarios by their WHEN clause, as today (425).
- Only the hold rejected, with a `WHEN … THEN …`: the task cites `C` and is red/green (440); `_requirement_for`
  (365-367) puts the scenario under `<C's requirement> — regression <n>`, named after `C`'s scenario (`(2)` when that
  name is taken there), never under `Rejected hold: … — finding H-…`.
- Only the hold rejected, without one: not converted (point 3).
- `C` not among the family's criteria (263): as today.
- Kiro: the plan is the provider's input, so a Kiro fix unit gets one `2.n` item where it got two.

Fail safe: the round's verdict, its findings' ids, severities and sources, which rejects exist and what each answer
settles do not change; the planner groups and names differently, nothing more. No reject is consumed by a task that
does not carry its reason. `ui_waivers` (`ui_step.py:269-276`) still ends a waiver on a later reject of the hold,
consumed or not.

### D9. Upgrade

A consumer moving from 0.4.59 with units in flight:

- `verdict.json` gains an optional key; a 0.4.59 verdict restores with no excerpt and its stored code.
- Questions that 0.4.59 raised keep their text: a waiting question is not raised again (L4-VER-070). The next fresh
  round's new questions carry the notes.
- A FAIL round's findings are planned right after the round. Only a NEEDS_HUMAN round is reused
  (`evidence.reusable`, `evidence.py:108-116`), and its stored findings never hold a rejected hold's finding (a rejected
  hold makes the round FAIL). So the answers to a round that 0.4.59 asked are settled by this harness's `_hold_finding`
  when the round is reused, and the one-task plan applies from the first round after the upgrade. A fix unit spawned
  by 0.4.59 keeps its two tasks.
- No new event; ledgers written by 0.4.59 fold unchanged.

## Risks / Trade-offs

- A model-written test and a failure's text now reach `questions.md` and `verification.md`, which are committed and,
  on a public forge, public. Both are redacted before the cut, after it, and again by the file's writer; the code was
  already in `verdict.json`. A secret shape the redactor does not know is copied into two more files.
- A hold's question grows by up to about 7,800 characters, so a unit with many failing generated tests has a long
  `questions.md` and a longer delegate prompt.
- A writer that reads why its test failed may write a weaker one (D5).
- Two different scenarios for one behaviour stay two criteria, in one task: near-identical sentences from a reviewer
  are not merged.
