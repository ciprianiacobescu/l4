## Context

Step 9 (`ladder.judge_body`) builds one judge prompt per diff part (L4-VER-041), each with every criterion of the unit,
and asks them through `_ask_judges`. `_ask_judges` calls `run_judge` on the current judge and moves to the next judge of
the chain when the status is `error` or `model_mismatch`; `schema_invalid` and `timeout` end the chain and the caller
holds the round (`the judge's reply was discarded`). A usage limit raises `RoleLimit`, which also moves to the next
judge. With no judge left the round raises `RoleUnavailable`, and the unit waits for capacity.

The opencode adapter (`agents/opencode.py`, `_result`) sets `status="error"` with the detail `the stream ended without a
final stop (last reason: length)` when the model's reply hit its output limit. Nothing downstream can tell that from any
other error, so the next judge gets the same oversized prompt. A consumer's unit (29 criteria, 4 parts) lost both of
its working judges this way on part 1 (ledger events `verify.judge{status: error, part: 1, parts: 4}` and
`availability.judge_error{detail: "... last reason: length"}`), then waited for capacity.

The output a judge writes grows with the number of criteria it is asked about (a verdict, evidence and test adequacy
per criterion), not with the diff part's size. The criteria are the lever.

## Goals / Non-Goals

Goals: a judge whose reply does not fit its output limit is asked again, by the same judge, with fewer criteria per call,
before it is discarded; the round's verdict, parts, follow-ups and records stay as they are when no reply stops at the
limit.

Non-goals: the follow-up calls (L4-VER-057: a follow-up with no usable answer already keeps the parts' verdict); other
roles; adapters that report no output-limit stop; a reasoning or output cap for an opencode profile without
`options.provider` (a separate change).

## Decisions

### D1 The signal is a field, not a detail text

`RunResult` gains `length_stop: bool = False`. `OpencodeAdapter._result` sets it in the branch that now writes `the
stream ended without a final stop` when `stream.last_reason == "length"`; the status and the detail are unchanged.
`agents/opencode_v2.py` sets it in each branch that gives no result (not `succeeded`, no final stop) when the stream's
last reason is `length`. `StructuredResult` (`llm/agent_judge.py`) gains `length_stop: bool = False`, copied from the
run on the `error` path of `complete_structured`. `JudgeRun` gains `length_stop: bool = False`; `run_judge` sets it from
the last call's `StructuredResult`. The status stays `error` everywhere, so every other reader of these results is
unchanged. No code reads the detail text to decide.

### D2 Where the split happens

`_ask_judges` takes two new keyword arguments, `criteria: Sequence[Criterion] = ()` (the criteria of the prompt) and
`rebuild: Callable[[Sequence[Criterion], bool], JudgePrompt] | None = None` (a prompt of the same part for a subset of
the criteria; the flag says whether the subset is the first batch). `judge_body` passes both for each part
(`prompt_for(..., criteria=subset, batch=BatchView(...))`, D3); `_follow_ups` passes neither, so a follow-up never
splits.

After a call of the current judge, when `judged.status == "error"`, `judged.length_stop`, `rebuild` is set, the prompt
has two or more criteria and `verifier.judge_length_splits` is above 0, `_ask_judges` does not move to the next judge.
It records `judge.length_split` (D4) and asks the SAME judge for each half of the criteria (the first half has
`ceil(n/2)`, in the criteria's order). A half whose reply again stops at the limit is split again while its depth is
below `judge_length_splits` and it has two or more criteria. With the default 2 a part has at most 4 batches and the
judge at most 7 calls for it.

- Every batch call goes through the same bookkeeping as a call of the whole prompt (one helper for both): the
  independence check of the served model (L4-VER-001), `result.judge_calls`, `result.cost_usd`, the `verify.judge`
  event, `judge.reply_repaired` and `budget.cost`.
- When every batch has a verdict, the batch verdicts are merged with `judge_parts.merge_part_verdicts` (each criterion is
  in one batch, so it is a union; findings, test adequacy and assumptions are merged as for parts) into ONE `JudgeRun`
  for the prompt: status `ok`, `calls` and `cost_usd` summed, `reply` the worst of the batches (`discarded`, `retried`,
  `repaired`, `valid`), `model_resolved` of the last batch. `judge_body` appends it to `replies` as the part's one reply,
  so the part-to-reply alignment that `_follow_ups`, `criterion_files` and `find_splits` read is kept.
- When a batch ends `error` or `model_mismatch` (also a length stop that cannot be split again), the judge is
  discarded for the round as today, with `availability.judge_error{detail}` naming the batch (`batch of K criteria at
  depth D: <detail>`), and the next judge is given the WHOLE prompt of the part (which it may split in its turn).
- When a batch ends `schema_invalid` or `timeout`, the returned run has that status and no verdict, as a whole prompt
  with that status does today (the round is held).
- A usage limit in a batch (`RoleLimit`) moves to the next judge, which is given the whole prompt, as today.

### D3 The batch prompt

`build_judge_prompt` takes `batch: BatchView | None = None` (`BatchView(shown, total)`), which composes with `part` and
is exclusive with `followup`. With it the criteria section begins with: `This call judges {shown} of the unit's {total}
criteria, listed below; the unit's other criteria are judged in other calls with the same diff. Answer only these
criteria, and give test adequacy only for them.` A prompt without `batch` is byte-identical to today's. The first batch
keeps the feedback, accepted, satisfied and done-task blocks; the other batches have none (as a follow-up), so
`run_judge` asks no missing id there. The answers block, the gate report, the owner and named changes are in every
batch. The text is built in code, like the part and follow-up sections; the implementer runs `test_template_lock` after
the change and bumps the judge prompt version only if the lock requires it, and the result says which.

### D4 Records

- `judge.length_split{round, profile, criteria, into, depth, part?, parts?}`: the ids of the prompt that stopped at the
  limit, the sizes of its two halves and the depth of the split (1 for the whole prompt).
- `verify.judge` of a batch call gains `batch_criteria` (its ids) and `batch_depth`.
- `VerifyResult.judge_batches`: one row per batch call, `{part, depth, criteria, profile, calls, reply, prompt_sha256}`
  (`part` 0 for a diff in one prompt), written by `verdict_json` and restored by `evidence.restore_round`.
- A `judge_parts` row gains `batches` (the number of batches that answered for the part, 0 when not split).
- `result.prompt_sha256` for a round with batches is the sha256 of every prompt hash of the round, the batch prompts
  included, joined by newlines (as for parts).

### D5 Configuration

`verifier.judge_length_splits: int` (default 2, 0..4). 0 keeps today's behaviour: a length stop discards the judge.

## Risks / Trade-offs

- A reasoning model spends its output limit on thinking and JSON together. Fewer criteria shorten both, but when the
  thinking alone fills the limit no batch size helps; the judge is then discarded after up to 7 calls. The remedy stays
  the consumer's: a reasoning cap through `options.provider`, or a judge with a larger output limit.
- Each batch repeats the diff, the spec and the gate report, so a split part costs more input tokens and time; step 9
  of a large unit can take longer (job budgets: L4-CI soft deadline). Only a reply that stopped at the limit pays this.
- Claude Code, Codex, Kiro and Copilot report no output-limit stop that this change reads; their judges behave as today.

## Migration

None. A unit that waits for capacity after a length stop is judged with the split at its next run on 0.4.48.
