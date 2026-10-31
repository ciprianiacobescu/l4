## Why

A consumer's unit (29 criteria, a diff judged in 4 parts) reached step 9 with no judge that could answer. Each part's
prompt asks for a verdict on every criterion of the unit. Two judges, a free reasoning model and its paid twin, each
with 32,000 output tokens, ended part 1 with the stream's last reason `length`: the reply did not fit the model's
output limit. The opencode adapter reports that as an error like any other, `ladder._ask_judges` discards the judge for
the round and gives the next judge the same prompt, and with no judge left the round raises `RoleUnavailable` and the
unit waits for capacity. Splitting the diff further does not help: every part still asks for all 29 verdicts.

## What Changes

- An agent run whose reply stopped at the model's output limit is marked as such (`RunResult.length_stop`); the
  opencode adapters (v1 and v2) set it when the stream's last reason is `length`. The structured-reply wrapper and the
  judge carry it (`StructuredResult.length_stop`, `JudgeRun.length_stop`); the status stays `error`, so no other role
  changes.
- When a judge's reply to a step-9 prompt stops at the output limit, the harness asks the same judge again with the
  prompt's criteria split in two halves, and splits a half that stops again, at most `verifier.judge_length_splits`
  times (default 2, so at most 4 batches and 7 calls for one part); only then is the judge discarded for the round and
  the next judge given the whole prompt, as before. The batch replies of a part are merged into one reply, so the parts,
  their merge and the follow-ups (L4-VER-057) are unchanged.
- A batch prompt says which of the unit's criteria it judges and that the others are judged in other calls with the same
  diff; the feedback, accepted, satisfied and done-task blocks go in the first batch only.
- The ledger records the split (`judge.length_split`), `verify.judge` names the batch, and `verdict.json` keeps the
  batches (`judge_batches`).

Not in this change: the follow-up calls (a length stop there already keeps the parts' verdict); length stops of other
roles; the adapters that report no output-limit stop (Claude Code, Codex, Kiro, Copilot); a reasoning or output cap
for an opencode profile without `options.provider`.

## Impact

- Code: `l4.agents.base` (`RunResult.length_stop`), `l4.agents.opencode`, `l4.agents.opencode_v2`, `l4.llm.agent_judge`
  (`StructuredResult.length_stop`), `l4.verifier.judge` (`JudgeRun.length_stop`, `BatchView`, the batch section of
  `build_judge_prompt`), `l4.verifier.ladder` (`_ask_judges`, `judge_body`), `l4.verifier.evidence` (`judge_batches`
  restored), `l4.config.schema` (`VerifierCfg.judge_length_splits`).
- Spec: L4-VER-071 (new), L4-VER-041 and L4-VER-001 unchanged; SCN-VER-265..269; change-table row 110.
- Cost: a split part costs more calls (each repeats the diff); a unit whose judges answer within their limits makes no
  extra call.
