# A server error that OpenCode reports only in words is transient, and is tried again

## Why

On 2026-10-28 a consumer's runs skipped the free OpenCode profile for the whole run with `availability.selected`
naming "opencode reported an error" [V, two GitHub Actions runs]. The provider had answered the hello with an HTTP 503,
but OpenCode 1.x wrote it into the error message only (`[503] … Service temporarily overloaded`, no `statusCode`; the
recorded fixture `tests/fixtures/recorded/opencode/1.18.33/error-upstream-503.jsonl` has the same shape):

- the v1 hello classifies with `status_class(data.get("statusCode"))`; `status_class(None)` is `other`;
- `other` is cached for `availability.cache_ttl` (15 minutes) as a profile that answered wrongly (L4-AVL-005), so the
  profile is not asked again in the run;
- the v2 hello (`_hello_v2`) has the same rule when `error.status` is missing;
- L4-AVL-006's one more hello after 20 s exists for claude only;
- OpenCode's run path writes ", retryable" into the detail but never sets `RunResult.transient`, so the in-run retry of
  L4-AVL-006 (judge, verifier agent, clarifier: 3 tries, 20 s then 60 s) never runs for OpenCode either. The bracketed
  status is kept as a string there, so `status in (401, 403)` can never match it.

The classifier the fix needs already exists: `text_class` (codex and kiro use it).

## What changes

- Both OpenCode hellos classify an error event by its integer status when there is one (`statusCode`, `error.status`,
  or a `[NNN]` at the start of the message, converted to `int`), else by `text_class(message)`. A 5xx, "unavailable",
  "overloaded", a timeout or a reset connection is `transient`, which is never cached.
- A transient error event in either hello is tried once more after `HELLO_RETRY_WAIT_S` (20 s), with the deadline checked
  before and after the wait. A limit, auth, `other`, an unsupported version, a timeout of the hello itself and an exit
  without an error event are not retried. The final result carries `hello_retry_wait_s`, and `availability.selected`
  shows it next to `hello_ms`.
- OpenCode's run path (v1 `_classify_error`, and v2's equivalent) converts the bracketed status to `int` and sets
  `RunResult.transient` for an error of the transient class, so L4-AVL-006's in-run retry covers OpenCode.
- 429, credits and quota stay limits (`normalise_limit` runs first and is unchanged).

## Impact

- Code: `l4.availability.probes` (a shared hello-retry helper), `l4.agents.opencode`, `l4.agents.opencode_v2`,
  `l4.availability.fallback` (`to_event`).
- Spec: L4-AVL-002, L4-AVL-005, L4-AVL-006 amended; SCN-AVL-28 to SCN-AVL-32 added; change-table row 89.
- A transient hello costs up to 20 s plus one more hello per selection; a permanent error worded as "unavailable" is
  asked again on each selection instead of being cached.
