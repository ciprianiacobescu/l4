# Design: a reject's scenario survives the reason's cut

## D1. The bounded reason

`verdicts.MAX_VERDICT_REASON_CHARS = 4000` and `verdicts.bounded_reason(text: str) -> str`:

- `len(text) <= 4000`: the text, unchanged;
- otherwise, when `WHEN_THEN` matches the text with a non-empty `when` and `then`: let `start` be the index of the
  `WHEN` that the match's `when` group follows (`match.start("when") - len("WHEN")`) and `tail = text[start:]`. When
  `len(tail) <= 4000 - 200`, the result is `text[: 4000 - len(tail) - 3].rstrip() + " … " + tail` (the head keeps at
  least 197 characters; its length plus the marker plus the tail is at most 4000);
- otherwise `text[:4000]`.

`record_human_verdicts` records `reason=bounded_reason(parsed[1])`. Nothing else reads the cut: `fixunit.when_then`,
`ends_with_scenario` and the decisions line read the stored reason as before, and now find the whole sentence. The
answer digest (`answer_sha256`) is of the whole answer, as before. The marker is ` … ` (U+2026 between spaces).

## D2. Tag-safe brackets

`l4.specs.base.untagged(text: str) -> str` (pure):

1. NUL characters are removed;
2. each innermost pair `[...]` (no bracket inside) whose content fully matches `[\w\s-]*` becomes `(...)`; any other
   innermost pair is held unchanged;
3. every bracket left that is not part of a held pair becomes a parenthesis (`[` to `(`, `]` to `)`);
4. the held pairs are put back.

A held pair holds a character outside letters, digits, `_`, `-`, whitespace and brackets, so neither tag pattern of the
harness (`\[([A-Za-z0-9_-]+)\]` for Kiro titles, `\[([A-Za-z][A-Za-z-]*)\]` for the scan) can match it, and no bracket is
left that a held pair's bracket could pair with. `openspec._plain` and `kiro._line` call `untagged` where they replaced
every bracket.

## D3. Tests

- `bounded_reason`: a 1,207-character reason ending in the consumer's sentence (under the limit: unchanged); a
  5,000-character reason ending in a sentence (sentence whole, ` … ` before it, total at most 4000); a 5,000-character
  reason without one (cut at 4000); a reason whose sentence alone is 3,900 characters (cut at 4000).
- `record_human_verdicts` with a 4,500-character reject ending in a sentence: the event's reason ends with the whole THEN,
  and `fixunit.when_then(reason)` gives it whole.
- `untagged`: `[...DEFAULT_ROLES].sort() deep-equals ["approver", "auditor"]` unchanged; `[test-infra] do x` → `(test-infra) do x`;
  `[ ]`, `[config]`, `[A-b_1]`, a lone `[` or `]`, `[[chore]]`, `[x.[chore]` all leave no tag (each Kiro and scan pattern
  finds nothing in the result); a NUL in the text is removed.
- The fix unit of the consumer's case: the proposal line and the task title keep `[...DEFAULT_ROLES]`.
