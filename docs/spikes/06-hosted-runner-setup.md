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
  variables is **unproven**: no secrets were set, and the harness has gaps there (§4).

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
   "Python 3.14.8") [V]. The reference runner and the test suite use 3.12. The shim should pin it.
5. **Kiro installs whatever version is current**: 2.29.1 against the 2.28.0 floor [V]. With the cache, the version that
   lands first stays until the cache key changes.
6. **Auth from environment variables is not wired for the three paid CLIs**, from reading the code [I]:
   - `availability/probes.py:75` refuses `api_key` profiles ("api_key is not supported in M0 (the sandbox passes no
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

## 5. Reproduce

Push to any `spike/**` branch of the harness repository. The workflow runs the cold job on both images and the warm
job on 24.04, and uploads `spike-cold-<os>` and `spike-warm-ubuntu-24.04` artifacts. Each artifact holds `facts.txt`,
`setup-flag-off.txt`, `setup-flag-on.txt`, `doctor-fix.txt`, `probe.txt`, `sandboxed-hello.txt`, `simulate.txt`,
`timings.txt` and `results.json`.

Optional secrets complete D' for the three paid CLIs: `CLAUDE_CODE_OAUTH_TOKEN`, `CODEX_API_KEY` and `KIRO_API_KEY`.
The run uses them only in the probe step.

## 6. Sources [D]

- The ubuntu-22.04 image lifecycle, with deprecation brownouts from 2026-09-17 and removal on 2027-04-17:
  https://endoflife.date/github-actions-runner-images,
  https://endoflife.ai/github-actions-runner-images/ubuntu-22.04
- The Ubuntu 24.04 AppArmor user-namespace restriction and bwrap's uid-map error:
  https://etbe.coker.com.au/2024/04/24/ubuntu-24-04-bubblewrap/
  - A narrower alternative to the sysctl is the `bwrap-userns-restrict` profile from `apparmor-profiles`. It also needs
    root, and it attaches to `/usr/bin/bwrap` only. Not tested here [U].
