# 06 Spike: an auto setup step on runners nobody customized (GitHub-hosted)

**Date:** 2026-10-11 · **Branch:** `spike/hosted-agent-setup` · **Run:** GitHub Actions run 38144352581 of
`.github/workflows/spike-hosted-setup.yml` at `831c0e7`: jobs `cold (ubuntu-24.04)` 114484478622 (104 s),
`cold (ubuntu-22.04)` 114484478868 (109 s), `warm` 114484850081 (97 s, ubuntu-24.04). Labels: **[V]** observed in that
run, **[D]** vendor documentation, **[I]** inferred, **[U]** unknown.

## 0. Verdict

**It works with one flag.** On a bare GitHub-hosted image, `L4_SELF_PROVISION=true` and the prototype setup step take
a job from "no uv, no bwrap, no agent CLI" to these results [V]:
- all four agent CLIs are installed at the pinned versions;
- the harness's bwrap sandbox works;
- one real OpenCode free-model call succeeds inside that sandbox;
- `l4 simulate --all` gives the same result as locally.

This took under two minutes per job cold. With the cache, the install step drops from 41–44 s to 7 s.

- **Ubuntu 22.04 needs no root** [V]. A bwrap extracted into the home folder runs as the job user.
- **Ubuntu 24.04 needs one root command and nothing else** [V]: `sysctl kernel.apparmor_restrict_unprivileged_userns=0`.
  - Before it, the home-folder bwrap fails with `setting up uid map: Permission denied`. The apt-installed
    `/usr/bin/bwrap` fails the same way, because the image has no AppArmor profile for bwrap.
  - After it, the home-folder bwrap passes. So `apt-get install` is never needed.
- 22.04 is not a long-term way around the root step. GitHub deprecates the ubuntu-22.04 image with brownouts from
  2026-09-17 and removes it on 2027-04-17 [D, sources in §6].
- Claude Code, Codex and Kiro install and are reported `installed-not-authenticated`. Their login from environment
  variables was **unproven** in this run: no secrets were set, and the harness had gaps there (§4).
- **Update after change 14 was implemented (§7):**
  - the real `l4-setup` reproduces all of this;
  - `l4 probe` passes Claude Code from `CLAUDE_CODE_OAUTH_TOKEN`;
  - the harness Python is pinned to 3.12;
  - Codex and Kiro now report their missing variable by name.

## 1. Questions and results (pre-registered before the run)

| id | question | 24.04 | 22.04 |
|---|---|---|---|
| A | `RUNNER_ENVIRONMENT=github-hosted` set? (runner-provisioning design, "confirm in spike 19") | yes | yes |
| B | flag on: setup step + `doctor --ci --fix` install the CLIs, ENV-001/003/004 pass | yes, 41 s | yes, 44 s |
| C0 | user-space bwrap (`apt-get download` + `dpkg -x`, no sudo) works | **no** (uid map) | **yes** |
| C | bwrap usable by the job user after the setup step | yes, after the sysctl | yes, no root |
| D | OpenCode free model: probe hello, and one call inside the harness's bwrap | ok 4.5 s; in bwrap ok 7.0 s | ok 7.8 s; in bwrap ok 5.9 s |
| D' | claude-code / codex / kiro-cli with no secret | `installed-not-authenticated` (PRV-001) | same |
| E | `l4 simulate --all` | 5 passed, 0 failed, 16 pending | same |
| F | flag off: the setup step changes nothing | one SKIP line; no uv, no bwrap, `~/.local/bin` empty | same |
| G | warm job with `actions/cache` | cache hit; every install `already present`; doctor --fix 7 s | — |

## 2. The setup lines, verbatim (HSU = hosted setup)

ubuntu-24.04 (image `ubuntu24/20261004.327.1`, kernel 6.17.0-1022-azure, user `runner`, `sudo -n` works, git 2.55.0,
Python 3.12.3, Node 22.23.3, no uv, no bwrap):

```
[HSU-02] FIXED uv — installed uv 0.12.22 (x86_64-unknown-linux-gnu) into ~/.local/bin in 1 s
[HSU-03] INFO apparmor bwrap profile — files in /etc/apparmor.d matching bwrap: none;
[HSU-04] INFO preinstalled bwrap (/usr/bin/bwrap) — ABSENT
[HSU-05] FIXED user-space bwrap install — bubblewrap_0.9.0-1ubuntu0.3_amd64.deb extracted to /home/runner/.local/share/l4/bwrap in 3 s, linked from ~/.local/bin/bwrap
[HSU-04] INFO user-space bwrap — FAIL rc=1 (/home/runner/.local/share/l4/bwrap/usr/bin/bwrap): bwrap: setting up uid map: Permission denied
[HSU-07] FIXED root fallback: apt-get install bubblewrap — installed in 5 s (no apt-get update needed)
[HSU-04] INFO root fallback: bwrap after apt install — FAIL rc=1 (/usr/bin/bwrap): bwrap: setting up uid map: Permission denied
[HSU-08] FIXED root fallback: apparmor userns sysctl — set kernel.apparmor_restrict_unprivileged_userns=0 (was 1; now 0)
[HSU-04] INFO root fallback: user-space bwrap after sysctl — PASS (/home/runner/.local/share/l4/bwrap/usr/bin/bwrap: bubblewrap 0.9.0)
[HSU-09] INFO bwrap final — sandbox usable by runner: yes, via user-space-after-sysctl
```

ubuntu-22.04 (image `ubuntu22/20261004.315.1`, kernel 6.8.0-1064-azure, Python 3.10.12, otherwise the same):

```
[HSU-05] FIXED user-space bwrap install — bubblewrap_0.6.1-1ubuntu0.3_amd64.deb extracted to /home/runner/.local/share/l4/bwrap in 2 s, linked from ~/.local/bin/bwrap
[HSU-04] INFO user-space bwrap — PASS (/home/runner/.local/share/l4/bwrap/usr/bin/bwrap: bubblewrap 0.6.1)
[HSU-07] SKIP root fallback — not needed, sandbox works via user-space bwrap
```

The bwrap test is the harness's own sandbox self-test shape:
`bwrap --ro-bind / / --dev /dev --proc /proc --unshare-user --unshare-pid --die-with-parent true`.

## 3. What `doctor --ci --fix` did (cold, both images) [V]

```
fix  uv        already present  uv 0.12.22
fix  node      already present  node 22.23.3     (the image's)
fix  openspec  applied          openspec 1.14.0
fix  claude    applied          claude 2.1.288
fix  codex     applied          codex 0.160.0
fix  opencode  applied          opencode 1.18.34
fix  kiro-cli  applied          kiro-cli 2.29.1
```

ENV-001..004 pass. PRV-002 says "no root-only prerequisite is missing" and SANDBOX-002 passes. Doctor exits 0.

PRV-001 (warn) reads: "claude-code installed-not-authenticated; codex installed-not-authenticated; kiro
installed-not-authenticated; oc-free opencode ready".

`ENV-008 serena not found` is a warning only.

## 4. Findings the spec must carry

1. **The shim cannot bootstrap itself.** `.l4/bin/l4` exits 3 without uv, and no GitHub image has uv [V]. So uv must
   come from a step that runs before the shim.
2. **The apt install is dead weight on 24.04.** It fails exactly like the home-folder binary [V], and the warm run spent
   6 s on it. The only useful root step is the sysctl. The production order is:
   1. home-folder bwrap;
   2. if it fails on the uid map and the sysctl is 1, set the sysctl;
   3. test again.
3. **The bwrap extraction is not idempotent in the prototype.** The warm run extracted it again. It needs an
   `already present` check like the other tools.
4. **Python drifts on 22.04.** The image has 3.10, so uv provisioned 3.14.8 for the vendored harness (ENV-001
   "Python 3.14.8") [V]. The test suite, CI's checks and `prereqs.sh` PRQ-06 use 3.12. The GitLab reference runner has
   drifted too: its harness reports 3.13.16 (ENV-001, `docs/live/kiro-e2e/h2/ci/job-6146.log`) [V]. The shim should pin
   3.12.
5. **Kiro installs whatever version is current**: 2.29.1 against the 2.28.0 floor [V]. With the cache, the version that
   lands first stays until the cache key changes.
6. **Auth from environment variables is not wired for the three paid CLIs**, from reading the code [I]:
   - `availability/probes.py:75` refused `api_key` profiles (until change 14, L4-PRV-024) ("api_key is not supported in M0 (the sandbox passes no
     credential variable)").
   - The probe and sandbox environments forward no credential variable.
   - The probe lines never name the missing variable. Only PRV-001's fix hint does ("run `claude setup-token`...").
7. **The in-sandbox call bypassed the adapter.** It was a standalone script
   (`scripts/runner/spike-hosted/sandboxed-hello.py`). It used the harness's `select_sandbox` and an agent
   `SandboxSpec`, but not the OpenCode adapter's own argv and environment. The adapter path on a hosted runner is
   proven only by a full `l4 run` against a GitHub forge, which belongs to change 13 (`live-validation`).
8. **GitLab Docker executors stay out of scope.** In an unprivileged container, bwrap fails with the same uid-map error
   [V, local Docker rehearsal of the same script, arm64 `ubuntu:24.04`].
9. **Free-model latency varies.** The probe hello took 4.5 s cold and 43 s warm on the same image [V]. A probe timeout
   must allow for it.
10. **Claude Code works from `CLAUDE_CODE_OAUTH_TOKEN` alone, in the sandbox too** [V, run 38156758955, jobs
    114521218781 (24.04) and 114521218926 (22.04), commit 1a92dd8]. The token came from `claude setup-token`, was stored
    by the maintainer in Mintkey, and was copied into a GitHub secret without being printed. Both images gave the same
    lines:
    ```
    auth_status {'loggedIn': True, 'authMethod': 'oauth_token', 'subscriptionType': None}
    outside_sandbox {'is_error': False, 'api_error_status': None, 'result': 'OK'}
    sandbox=bwrap rc=0 seconds=2.3 token_in_bwrap_argv=False token_in_bwrap_env=False value_file_removed_by_loader=True
    token_leak_check=clean
    [l4] probe: claude-code skipped — auth: claude is not logged in
    ```
    Inside bwrap, the token was delivered by `scripts/runner/spike-hosted/sandboxed-claude.py`: a 0600 file in the step's
    private directory and a `/bin/sh` loader that reads it, deletes it, exports the variable and execs `claude`. It never
    went through `--setenv`, whose values are in bwrap's argv and readable by any local user. The last line is finding
    6: `l4 probe` drops the variable.
11. **Pipeline secrets are environment secrets** (2026-10-11). The maintainer asked for GitHub Environments instead of
    repository secrets. They work on this private repository on the Free plan [V]:
    - environment `hosted-agents` holds `CLAUDE_CODE_OAUTH_TOKEN`, with a deployment branch policy of `spike/*`;
    - environment `publication` holds `L4_PUBLICATION_RULES`, for `checks.yml`;
    - the repository has no repository-level secret.

## 5. Reproduce

Push to any `spike/**` branch of the harness repository. The workflow runs the cold job on both images and the warm
job on 24.04, and uploads `spike-cold-<os>` and `spike-warm-ubuntu-24.04` artifacts. Each artifact holds `facts.txt`,
`setup-flag-off.txt`, `setup-flag-on.txt`, `doctor-fix.txt`, `probe.txt`, `sandboxed-hello.txt`, `claude-token.txt`,
`simulate.txt`, `timings.txt` and `results.json`.

Optional secrets complete D' for the three paid CLIs: `CLAUDE_CODE_OAUTH_TOKEN`, `CODEX_API_KEY` and `KIRO_API_KEY`.
They are secrets of the GitHub environment `hosted-agents`, which both jobs name. The run uses them in the probe step and
in the Claude Code step. A step before the upload fails the job if an artifact file contains the token.

## 6. Sources [D]

- The ubuntu-22.04 image lifecycle, with deprecation brownouts from 2026-09-17 and removal on 2027-04-17:
  https://endoflife.date/github-actions-runner-images,
  https://endoflife.ai/github-actions-runner-images/ubuntu-22.04
- The Ubuntu 24.04 AppArmor user-namespace restriction and bwrap's uid-map error:
  https://etbe.coker.com.au/2024/04/24/ubuntu-24-04-bubblewrap/
  - A narrower alternative to the sysctl is the `bwrap-userns-restrict` profile from `apparmor-profiles`. It also needs
    root, and it attaches to `/usr/bin/bwrap` only. Not tested here [U].

## 7. The implementation, on hosted runners (change 14 task 1.6; run 38164195347)

The run is GitHub Actions run 38164195347 at `28b9902`, with jobs `cold (ubuntu-24.04)` 114543217276,
`cold (ubuntu-22.04)` 114543217108 and `warm` 114543691451. All three succeeded. The workflow first renders
`src/l4/ci/templates/l4-setup.sh` from the checkout, which is the uv bootstrap: `l4 init` needs uv first. After
`l4 init` it runs the vendored `.l4/bin/l4-setup` that init wrote, and the two files are byte-identical in all three jobs
(`setup_identical=yes`) [V].

**Flag off and `auto` on a hosted runner** change nothing. Each prints one line:
```
[HSU-00] SKIP hosted setup — L4_SELF_PROVISION is not set; the shell cannot read ci.self_provision from the config, so only true or auto act
[HSU-00] SKIP hosted setup — L4_SELF_PROVISION=auto on a disposable runner means off; set it to true to run
```

**24.04, cold.** One root command, the sysctl. No package is installed:
```
[HSU-04] FIXED bwrap — bubblewrap_0.9.0-1ubuntu0.3_amd64.deb extracted to /home/runner/.local/share/l4/bwrap but fails the self-test: bwrap: setting up uid map: Permission denied
[HSU-05] FIXED root step — kernel.apparmor_restrict_unprivileged_userns set to 0 (was 1; now 0)
[HSU-06] INFO bwrap after the sysctl — self-test passes via user-space
```

**22.04, cold.** No root at all:
```
[HSU-04] FIXED bwrap — bubblewrap_0.6.1-1ubuntu0.3_amd64.deb extracted to /home/runner/.local/share/l4/bwrap in 2 s, linked from ~/.local/bin/bwrap
[HSU-05] SKIP root step — would run: sudo -n sysctl -w kernel.apparmor_restrict_unprivileged_userns=0; not run: not needed, bwrap already works
```

**24.04, warm** (`cache_hit=true`). The cached binary fails on a fresh VM and is not downloaded again. The sysctl runs,
then the binary passes:
```
[HSU-04] INFO bwrap link — removed ~/.local/bin/bwrap, it failed the self-test: bwrap: setting up uid map: Permission denied
[HSU-04] INFO bwrap — cached /home/runner/.local/share/l4/bwrap/usr/bin/bwrap fails the self-test, not downloading again: bwrap: setting up uid map: Permission denied
[HSU-05] FIXED root step — kernel.apparmor_restrict_unprivileged_userns set to 0 (was 1; now 0)
```

**Doctor.**
- Cold, `doctor --ci --fix` took 46–47 s.
- Warm, it took 5 s, with every `fix` line `already present`, kiro-cli 2.29.1 included. So the binaries need neither
  `~/.local/share/opencode` nor `~/.local/share/kiro-cli`, and the cache leaves both login directories out.
- ENV-001 reports **Python 3.12.3** on 24.04 and **3.12.15** on 22.04. The spike's 3.14.8 is gone (L4-PRV-025).

**Probe** (the same lines in all three jobs):
```
[l4] probe: oc-free ok (binary 1.18.34 · auth skipped · quota skipped · hello 4.3s)
[l4] probe: kiro skipped — auth: KIRO_API_KEY is not set
[l4] probe: codex skipped — auth: CODEX_API_KEY is not set
[l4] probe: claude-code ok (binary 2.1.288 · auth subscription · quota skipped · hello 2.3s)
```
- Claude Code authenticates from the environment secret alone (SCN-PRV-67).
- Codex and Kiro name the variable they lack (SCN-PRV-68). Their secrets do not exist yet, so task 2.4 stays open for
  those two.
- The doctor step of this evidence workflow has no secrets in its environment, so PRV-001 names all three variables:
  `claude-code: CLAUDE_CODE_OAUTH_TOKEN is not set; codex: CODEX_API_KEY is not set; kiro: KIRO_API_KEY is not set`.
  The generated job maps them into the job's env (SCN-PRV-74).

**Agent calls inside the harness's bwrap.**
- OpenCode's free model answered `OK` in 5.5 s (24.04), 12.5 s (22.04) and 9.3 s (warm).
- Claude Code answered `OK` in 2.3 s with `token_in_bwrap_argv=False token_in_bwrap_env=False
  value_file_removed_by_loader=True`.
- `token_leak_check=clean` in both cold jobs. `l4 simulate --all` exit 0 in both cold jobs.

**Findings.**
12. **Each step appends `~/.local/bin` to `$GITHUB_PATH` again.** GitHub gives every step its own `$GITHUB_PATH`
    file, so the "already listed" check cannot see the earlier step's line. A duplicate PATH entry is harmless.
13. **PRV-001's human steps say "masked CI variable" on GitHub too.** That is GitLab's wording. On GitHub it should say
    "a secret of the GitHub environment `l4`". This is open, a text fix in `provision/readiness.py`.
14. **The generated `l4.yml` itself did not run on a hosted runner here.** The evidence workflow runs the same commands
    in the same order. A real `l4 run` against a GitHub forge stays change 13 (`live-validation`).
