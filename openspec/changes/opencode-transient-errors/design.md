# Design: opencode-transient-errors

## Context (verified on amaster b4cf62b5)

- `status_class(status)` (src/l4/availability/probes.py): only an `int` is classified (401/403 auth, 429 limit, ≥500
  transient), anything else `other`. `text_class(text)`: auth wording, then `_TRANSIENT_TEXT` (`\b5\d\d\b`,
  unavailable, overloaded, timeout, connection reset/refused/closed).
- `probe_claude` already retries an overloaded hello once after `HELLO_RETRY_WAIT_S` with `ctx.sleep or time.sleep`.
- OpenCode v1 hello (src/l4/agents/opencode.py, `_hello`): the error branch uses `status_class(data.get("statusCode"))`.
  v2 (src/l4/agents/opencode_v2.py, `_hello_v2`): `status_class(status)` with `status` None when `error.status` is not
  an int.
- `_remember` (src/l4/availability/fallback.py) caches `other` for `cache_ttl`, auth for `auth_failure_ttl`, never
  transient or unsupported_version.
- `RunResult.transient` (src/l4/agents/base.py) drives the in-run retry of `l4.llm.agent_judge`; claude-code and
  copilot-cli set it; OpenCode's `_classify_error` does not.

## D1 One status reader

A small helper in each OpenCode module (or one shared in `opencode.py`, imported by v2 as v2 already imports from
`probes`): the integer status of an error event: `statusCode` (v1) or `error.status` (v2) when it is an `int`, else
`int(m.group(1))` of `_BRACKET_STATUS` on the message, else None. Then
`kind = status_class(status) if status is not None else text_class(message)`. The auth and limit branches before it are
unchanged (they run first).

## D2 The retry

`hello_retry(ctx, once: Callable[[], T], transient: Callable[[T], bool]) -> tuple[T, float | None]` in
`l4.availability.probes`: runs `once()`; when `transient(result)` holds, calls `deadline.stop_before_probe()`, sleeps
`HELLO_RETRY_WAIT_S` with `ctx.sleep or time.sleep`, calls `stop_before_probe()` again and runs `once()` a second time;
returns the last result and the wait (None when none). Both OpenCode hellos use it; "transient" means an error event was
read and classed `transient` (D1). A timeout (exit 124), an exit without an error event, or an unreachable custom
provider are not retried. Claude's retry may move onto the helper if that is a straight swap; otherwise leave it.

The result's `detail` gets `hello_retry_wait_s`; `to_event` copies it next to `hello_ms`.

## D3 The run path

v1 `_classify_error`: `status` becomes an `int` (D1) so `status in (401, 403)` works for a bracketed 401. In the last
branch, set `result.transient = True` when `status_class(status) == "transient"` or, with no status,
`text_class(message) == "transient"` (keep the ", retryable" detail). The same in v2's run-path classifier. A limit,
auth and the provider-unavailable branch are unchanged.

## D4 Not changed

429 and credits stay limits. No retry is added to `ProbeLadder.run` (it would retry claude twice and wait after
timeouts). No change to the cache TTLs.
