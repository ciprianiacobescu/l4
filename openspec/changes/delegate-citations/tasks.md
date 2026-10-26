## 1. The delegate's citations (L4-DLG-005)

- [ ] 1.1 Tests first, in `tests/unit/delegate/test_reply.py` (helpers `check`, `reply`, `cite` of that file; read how
  its repo fixture lays out the unit folder and `design.md` before writing):
  - `test_a_wrapped_sentence_quoted_as_one_line_resolves` (SCN-DLG-116): a file whose sentence wraps over two lines;
    an entry naming the second line quotes the sentence as one line (no line break) → `Kept`; the same quote naming a
    line four lines below where it starts → `Discarded` with `checked <ref> does not resolve`; a quote present in the
    file only further down than three lines after the named line → `Discarded`.
  - `test_a_spec_reference_by_bare_name_or_repository_path` (SCN-DLG-117): with ONE `specs/<cap>/spec.md` in the unit
    folder, `spec:spec.md#requirement-x` quoting it → `Kept`; `spec:<unit folder repository path>/design.md` quoting
    design.md → `Kept`; with TWO spec deltas (`specs/a/spec.md`, `specs/b/spec.md`), `spec:spec.md` → `Discarded`
    (does not resolve); `spec:questions.md` stays the harness-written discard; a bare name of no file → `Discarded`.
  - `test_a_discard_records_its_entries_and_whether_it_may_be_asked_again`: an unresolved reference → `Discarded`
    with `retryable is True` and `checked == ({"ref": ..., "quote": ...},)` (redacted: give a redactor that replaces
    a marker string and check it is replaced); a harness-written ref → `retryable is False` with its `checked`; a
    reply with no `checked` entry → `retryable is False`; a reply that is not a valid document → `checked == ()`.
  - The existing `test_checked_entries_resolve` keeps passing unchanged (its four-lines-off cases stay discarded).

  Then, in `src/l4/delegate/reply.py`:
  - `_resolves`, `path:line`: replace the window loop with design D1 (`a = max(line - LINE_WINDOW, 1)`, `head` the
    folded lines `a .. line + LINE_WINDOW`, `rest` the folded lines from `a` to the end, resolve when
    `0 <= rest.find(quote) < len(head)`); keep the quote floor, the tracked/regular/harness checks and `_LINE_REF`.
  - `_resolves`, `spec:`: a new `_spec_file(name, head) -> str | None` as design D2 (three forms in order, each a
    tracked regular file; the bare name only without `/` and only when exactly one file under `head.unit_rel + "/"`
    has that last path part); `_safe_relative` before, `_harness_written` on the chosen path, the quote in its text.
  - `Discarded`: add `retryable: bool = False` and `checked: tuple[dict[str, str], ...] = ()`. `check_reply` fills
    `checked` (each entry's `ref` and `quote`, each through `redactor.redact_text`) for every `Discarded` it returns
    after the schema check passed, and sets `retryable=True` only where it returns `checked <ref> does not resolve`.
    Write it so the existing return statements stay readable (for example a small local function that builds the
    `Discarded`).
  Docstrings in the module's voice. Run `tests/unit/delegate/test_reply.py` and `test_reply_0421.py`.

- [ ] 1.2 Tests first, in `tests/unit/delegate/test_prompt.py`: the version is `delegate@4` (update the existing
  assertion and the module docstring's `delegate@3` in both the test and `src/l4/delegate/prompt.py`); the system text
  holds `spec:specs/<capability>/spec.md#<anchor>` and says the line of a `path:line` reference is where the quote
  starts; a `Material(previous="checked spec:spec.md does not resolve")` prompt holds a `# Your previous reply`
  section with a data block of kind `previous` and source `harness` that holds the reason, after the question block;
  a `Material()` prompt has no such section. Then change `prompt.py` as design D3 (`PROMPT_VERSION = 4`; the two
  sentences; `Material.previous: str = ""` as the LAST field so positional callers keep working; the section,
  redacted and capped with `_cap`). Run `tests/unit/delegate/test_prompt.py`.

- [ ] 1.3 Tests first, in `tests/unit/delegate/test_pass.py`, next to `test_a_discarded_reply_escalates` and
  modelled on `test_a_timeout_defers_then_escalates_at_the_limit` (`fake_clock`):
  - change `test_a_discarded_reply_escalates` so that it still tests an escalation of a reference discard: run it with
    `delegate={"max_attempts_per_question": 1}` (check how `with_delegate` merges keys), and assert also that the
    result holds `checked == [{"ref": "spec:proposal.md", "quote": "text that is not there"}]`;
  - `test_a_reference_discard_is_asked_again_once` (SCN-DLG-118): first run → one result `deferred`, `called` true,
    `discarded == "checked spec:proposal.md does not resolve"`, `checked` recorded, `reason` starts with
    `the reply was discarded: checked spec:proposal.md does not resolve`; the questions file has no `Escalated by:`
    line and the question is open; advance the clock 10 minutes; second run with the same bad reply → the last result
    is `discarded` with `checked`, the question escalated (`Escalated by:` with `the reply was discarded: …`); and the
    second ask's prompt carried the reason (monkeypatch `pass_module.build_prompt` with a wrapper that records
    `material.previous`, as `test_the_pass_hands_the_checks_the_globs_and_the_question_facts` wraps `check_reply`);
  - SCN-DLG-119: in the existing `test_a_reply_citing_a_harness_file_is_discarded_with_that_reason`, add the tag
    comment `# SCN-DLG-119` and an assertion that there is exactly one result and it is `discarded` (no deferral).
  Then, in `src/l4/delegate/run.py`, the discard branch (`if isinstance(kept, Discarded):`) as design D5: when
  `kept.retryable` and `attempts_used(events, key) + 1 < self.cfg.max_attempts_per_question`, call `self._defer(...)`
  with `why = f"the reply was discarded: {kept.reason}; it is asked again"`, `retry_after = self._now() +
  timedelta(seconds=RETRY_AFTER_S)`, `who`, `reply`, and pass `discarded=kept.reason` and `checked=list(kept.checked)`
  through to `_result` (extend `_defer` with `**more` forwarded to `_result`); otherwise `_escalate(...)` as today
  plus `checked=kept.checked`. Make sure `events` and `key` in scope there are the ones `attempts_used` is called
  with in the timeout branch. In the prompt builder (the method that builds `Material(...)`), set `previous` from the
  latest of `limits._results(events, key)` when its status is `deferred` and it has `discarded` (import what you need;
  if `_results` is private, add a small public helper in `limits.py`, `last_discard(events, key) -> str`, and test it
  in `tests/unit/delegate/test_limits.py`). Run `tests/unit/delegate`.

- [ ] 1.4 Docs:
  - `docs/SPEC.md`, L4-DLG-005: after the sentence that ends "(a `test:` entry has no quote: it MUST name a test id
    of the unit's verification evidence)." add: "A `path:line` entry resolves when its quote, whitespace folded, starts within three lines
    of the named line (its first occurrence from line `line - 3` on starts in those seven lines; it may run past them
    and keep or drop the file's line breaks). A `spec:<name>` entry names `<unit folder>/<name>`, else `<name>` when
    it starts with the unit folder's repository path, else, for a name without `/`, the one tracked file of the unit
    folder of that file name (two or more: it does not resolve)." Replace "Any other reply MUST be recorded
    `delegate.result{status: discarded}` and the question escalated." with "Any other reply MUST be recorded
    `delegate.result{status: discarded}` with its entries' `ref` and `quote`, redacted, and the question escalated,
    except that a reply discarded only because an entry does not resolve, with an attempt left under
    `delegate.max_attempts_per_question`, is recorded `delegate.result{status: deferred, discarded}` and asked again,
    and the next prompt (`delegate@4`) says why the previous reply was discarded."
  - `docs/SPEC.md`: after SCN-DLG-115, add SCN-DLG-116 (+) A wrapped sentence quoted as one line resolves · L4-DLG-005;
    SCN-DLG-117 (+) A spec reference by its bare name or repository path · L4-DLG-005 (with the two-deltas case as
    the negative Then); SCN-DLG-118 (+) A reference discard is asked again once · L4-DLG-005, L4-DLG-013;
    SCN-DLG-119 (−) A harness-written citation escalates at once · L4-DLG-005. Given/When/Then in the form of the
    scenarios around them, matching the spec delta of this change.
  - `docs/SPEC.md` change table: row 77 `delegate-citations` after row 76, in the form of rows 75 and 76 (what changed;
    the cause: three of four discarded delegate replies of one plan's day were right answers whose references did not
    resolve, a bare `spec.md` and a wrapped quote, and each stopped the plan for a person; the requirements; the folder;
    checked by the unit tests `test_reply`, `test_prompt`, `test_pass`).
  - `CHANGELOG.md`: `## 0.4.34 (unreleased)` above `## 0.4.33 (2026-10-26)`, with `### Fixed` (a `path:line` quote of
    a wrapped sentence and a `spec:` reference by bare name or repository path now resolve; a discarded reply records
    its references and quotes) and `### Changed` (a reply discarded only for a reference that does not resolve is asked
    again once within `delegate.max_attempts_per_question`, with the reason in the prompt, `delegate@4`).
  Run `uv run python scripts/check_spec.py docs/SPEC.md` and `uv run pytest tests/unit/docs -q`.
