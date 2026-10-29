# A push that fails on the forge's side is tried again, and is not called a refusal

## Why

L4-LCK-001 says that a push the forge itself rejects, a transient error included, is retried once after a short delay.
No code does that: `Git._push` runs `git push` once.

On 2026-10-28 a consumer's run lost a 746 s implementer step to a single server error [V, the run's log]:

    push of l4/openspec/<unit> to origin failed: remote: fatal error in commit_refs_rules | To https://github.com/<owner>/<repo> | ! [remote rejected] …
    l4 exit 1 (internal_error): push refused by the forge: …

`explain_push_failure` reads `[remote rejected]` as a hook refusal, so the failure is `PushFailed(refused=True)`. That
has two effects:

- the unit's line says "push refused by the forge", which sends a person to look for a push rule;
- the sweeper counts the archive push as a definitive failure (`definitive_reason`), although the next try would work.

## What changes

- `l4.vcs.push` classifies a failed push's stderr: `is_transient_push_failure`.
  - Transient: a server error or a broken connection. Examples: GitHub's `fatal error in commit_refs_rules`,
    `Internal Server Error`, HTTP 500/502/503/504, `RPC failed`, `the remote end hung up unexpectedly`, `early EOF`, a
    reset or timed-out connection, a failed TLS handshake, a name that does not resolve.
  - A credential or permission marker always wins: such a failure is never transient.
  - `is_permission_failure` and its markers move to `l4.vcs.push`, and `l4.forge.pushfail` keeps the name as an import.
- `Git._push` tries a transient failure up to 3 times, waiting 5 s and then 15 s, and starts no try more than 60 s after
  the first.
  - Before each new try, and after a lease or non-fast-forward refusal that follows a transient one, it asks the remote
    (`git ls-remote`) whether every ref of the push already holds the value pushed (absent for a delete). If so, the
    push landed although git reported an error, and it returns as a success.
  - Every retry is logged as a warning, and `cancel.check()` runs before it.
- `explain_push_failure` reads a transient failure first.
  - It returns `PushFailed(transient=True, refused=False)`, exit 1.
  - Its hint: the forge failed on its side (a server or network error, not a refusal), the harness tried again, nothing
    is wrong with the branch or the credential, and the next run pushes again.
  - The unit's line says "push failed on the forge's side", not "push refused by the forge".

## Impact

- Code:
  - `l4.vcs.push`: the classifier, and the permission markers moved there;
  - `l4.vcs.git`: `_push`, `_landed`, and the test seam for sleep and clock;
  - `l4.forge.pushfail`: `PushFailed.transient`, and the order of the checks;
  - `l4.orchestrator`: `_failed_unit`'s line.
- Behaviour:
  - a server error costs up to 20 s of waiting instead of a lost step;
  - a hook, a rule or a credential failure is not retried, as today;
  - the sweeper retries a transient archive push at its next pass.
- Docs:
  - L4-LCK-001 (the retry sentence), SCN-LCK-10 (a definitive refusal is not retried), new SCN-LCK-11 and SCN-LCK-12;
  - change-table row 86, CHANGELOG 0.4.39.
