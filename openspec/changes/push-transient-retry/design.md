# Design: retry a transient push failure in one place

## D1. Where: `Git._push`

Every harness push goes through `Git._push`: the unit branch, the archive branch, a lock ref and the pending ledger, a
delete, a keep ref, a restart, a retire, and the questions CLI's push. One loop there covers them all, and no caller has
to change. The `moved` callable stays as it is: a ref that moved on is never transient.

## D2. The classifier

`is_transient_push_failure(stderr) -> bool` is True when the lowercased stderr holds a transient marker and no
permission marker (`is_permission_failure`). The transient markers:

- `fatal error in commit_refs_rules`
- `internal server error`
- `internal api error`
- `the requested url returned error: 500`, `502`, `503` and `504`
- `rpc failed`
- `the remote end hung up unexpectedly`
- `early eof`
- `connection reset`
- `connection timed out`
- `operation timed out`
- `failed to connect to`
- `could not resolve host`
- `gnutls_handshake() failed`
- `ssl_error_syscall`
- `unexpected disconnect while reading sideband packet`
- `service unavailable`
- `temporarily unavailable`
- `please try again later`

A push rule's own text is never in that list, so a rule that says no stays a refusal.

`is_permission_failure` and `_DENIED` move from `forge/pushfail.py` to `vcs/push.py`, because the classifier needs
them and `vcs` must not import `forge`. `forge.pushfail` imports both back, so every existing import works.

## D3. The loop

    tries = 3; waits = (5.0, 15.0); budget = 60.0 s from the first try
    for n in 1..tries:
        try: return run(push)
        except GitError as exc:
            if moved(exc.stderr):
                if an earlier try was transient and self._landed(args, config): return success
                raise PushRejected
            if not transient(exc.stderr) or n == tries or elapsed + waits[n-1] > budget: raise
            log.warning(...); sleep(waits[n-1]); cancel.check()
            if self._landed(args, config): return success

- `_landed(args, config)` reads the refspecs after `--`: the first word is the remote, each refspec is `src:dst`.
  - It runs `ls-remote <remote> <dst>…` with the same `config`, which carries the push credential.
  - It wants `rev_parse(src)` for each `dst`, or that `dst` is absent when `src` is empty (a delete).
  - It returns True only when every `dst` matches. Any error of `ls-remote` is "not known to have landed", so the
    loop tries again.
- Success when the push landed: `GitResult(0, "", <the last stderr>)`, plus an info line "the push landed although git
  reported a server error".
- The test seam: `Git` takes `sleep` and `monotonic` as keyword arguments, `time.sleep` and `time.monotonic` by default.
  Or use module attributes that tests patch, whichever the module already does for its other seams.

## D4. The explanation

`explain_push_failure` checks a transient failure before `PushRejected` (a `PushRejected` is never transient) and
before the hook check. The text:

    push of <branch> to origin failed: <first lines>. The forge failed on its side (a server or network error, not a
    refusal); the harness tried again. Nothing is wrong with the branch or the credential: the next run pushes again

`PushFailed(ExitCode.INTERNAL_ERROR, …, transient=True)`. `_failed_unit` writes `push failed on the forge's side: …`
for it. The sweeper's `definitive_reason` already returns None when `refused` is false.

## D5. Not in scope

- The `push.rejected` ledger event that L4-LCK-001 names is not recorded today, and this change does not add it.
  L4-LCK-001's sentence is amended to say what happens: the unit's failure line with the server's message.
- A fetch that fails on the forge's side keeps its own handling (`fetch_cause`).
