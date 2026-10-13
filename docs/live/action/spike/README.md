# Spike `l4-action`: the harness as a GitHub Action (2026-10-12)

**Action:** `.github/actions/l4` at agent-supervisor c148939a (branch `l4-action`).
**Caller:** `ciprianiacobescu/l4-dummy-action`, created for the spike: public first, then private.
**Runner:** GitHub-hosted `ubuntu-24.04`.
**Command:** `l4 --version` (the harness only; no agent CLIs).

Labels: **[V]** observed in these logs or in the Actions API step timings in this folder.

| Run | Repository | Job | Result | Job time | Action step | Lines |
|---|---|---|---|---|---|---|
| 38299270512 (push) | public | private action | **failure at Set up job** | 2 s | — | `##[error]Unable to resolve action ciprianiacobescu/agent-supervisor, not found` |
| | | copy + deploy key | success, cache miss | 11 s | 7 s | uv installed 1.01 s; harness installed (`git+ssh`) 3.25 s; cache saved; `l4 --version` 0.33 s |
| 38299395945 (dispatch) | public | private action | failure at Set up job | 3 s | — | same error |
| | | copy + deploy key | success, **cache hit** | 7 s | 3 s | 25 MB restored (17 MB/s); `l4 --version` 0.40 s |
| 38299475651 (dispatch) | **private** | private action | **success**, cache miss | 11 s | 5 s | `Download action repository 'ciprianiacobescu/agent-supervisor@c148939a…'` (~2.5 s); 4597 files, 50M; uv 1.04 s; harness installed (source action) 0.92 s; `l4 --version` 0.43 s |
| | | copy + deploy key | success, cache hit | 9 s | 3 s | `l4 --version` 0.42 s |
| 38299563947 (dispatch) | private | private action | success, **cache hit** | 16 s | 2 s | the action download took ~9.8 s this time (Set up job 11 s); `l4 --version` 0.43 s |
| | | copy + deploy key | success, cache hit | 11 s | 3 s | `l4 --version` 0.28 s |

**What the spike showed:**
- **Same owner, private caller:** the harness repository's own action works with no key or secret. The harness repository's Actions access was already `user` [V].
- **Public caller:** the private action cannot be used, as GitHub documents ("access is allowed only from private repositories"). A copy of the action with a read-only deploy key works.
- **The action's repository is downloaded on every job.** The 6.7 MB archive, 50 MB unpacked because of `docs/live`, took 2.5–9.8 s. Slim release commits (design D6) target this.
- **The installed-harness cache is 25 MB** and restores in 1–2.3 s. The github-parity tool cache, harness and agent CLIs together, is 425 MB and restores in 5–10 s.
- **Clean-up:** the temporary deploy key 166229207 and the dummy's `L4_HARNESS_SSH_KEY` were deleted after the runs. The dummy is private and waits for the maintainer to delete it.

The logs here have ANSI codes stripped. The only key material in them is GitHub's public host key, which the action pins. The deploy key appears only as `INPUT_SSH_KEY: ***`.
