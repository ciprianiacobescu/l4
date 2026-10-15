# `l4 eval`: measuring a change, and the regression gate (M1.14)

Before M1.14 no template change, CLI pin bump or profile change was ever measured: the free-model run of 2026-10-06
([free-resources.md](free-resources.md), [live/free/](live/free/)) was a set of shell scripts. `l4 eval` is that method
as a command, and `l4 eval --compare` is the gate (SPEC 20.1, handbook items 16 and 39 in
[research/08](research/08-understanding-harness-engineering.md)).

## What it measures, and what it does not

* A **seed set** of 4 units in this repository, `tests/eval/seeds/`: a dependency-free base project and the units
  `add-shelf-code`, `add-tip-amount`, `add-reorder-quantity` (the three free-run units) and `add-late-fee`, a unit with a
  **designed defect** (the reference fee ignores the balance; the expected judge verdict is `NEEDS_HUMAN`).
* **Implementer cells**: one profile writes red and green on a unit, through the real `l4 run` (adapter, sandbox, gates,
  ladder, ledger; only the forge is local), then a fixed reference judge gives a verdict. Pass = red and green ended ok
  and the verdict is PASS.
* **Judge cells**: a deterministic `command` profile (`python -m l4.eval.replay`) writes the unit's reference red and
  green through the real implement path, then **one** judge profile judges. Pass = its verdict is the expected one.
* A cell is `pass`, `fail` or `invalid`. `invalid` (HTTP 429, endpoint unavailable, a missing login, a vendor that is
  the judge's, a cold offline cache, a cell timeout, a busy runner, `harness_error`: the child `l4 run` exited 1, 2
  or 3, so the harness or its environment failed, or a model under test that never ran: `baseline_failed` and
  `halted_before_agent` when an implementer run halted before its first agent step, `judge_not_reached` when a judge
  was never called, `reference_unavailable` when the fixed judge or the replay could not run: that stops the cells of
  its role, not the profile under test) is listed with its reason and left out of every rate. A schema error and an agent timeout are
  failures.

It sees: a profile that **lost a cell** (one of four is 0.25, past the default `--max-drop 0.20`), a judge that
**passes the held-back defect**, a prompt change that makes weak models write invalid results. It does not see: a 5 point
drift, anything under k = 1 noise, a regression on code the 4 units do not exercise. There is no confidence interval
and no significance test: the gate is a threshold on a rate over a handful of cells, from one environment (the
scorecard records it). Hidden held-out acceptance tests for implementers and replay of human-labelled live units are
not built (they need maintainer-written oracles).

## Seed layout and how to add a unit

```
tests/eval/seeds/base/                the project every unit starts from (pyproject.toml, uv.lock, src/, tests/)
tests/eval/seeds/units/<id>/          proposal.md, tasks.md (one task), specs/<cap>/spec.md (two scenarios, distinct
                                      WHENs), .openspec.yaml, expected.json,
                                      reference/red/<paths>, reference/green/<paths>, [reference/hidden_check.py]
```

`expected.json`: `{"implementer": {"outcome": "pass"}, "judge": {"verdict": "PASS"}}`; a judge-only unit has no
`implementer` key. Tag the reference tests with the criterion ids (`uv run python -c "..."` over
`l4.specs.criteria.openspec_criteria`), and run `uv run pytest tests/unit/eval` (the validity tests run the base gate on
each reference). **Any byte of the seed set changes `seed_set_sha256`**, so a new unit starts a new baseline: the gate
refuses to compare across it (`--allow-seed-change` prints deltas only).

Seed-set changes so far: (1) the `## Purpose` of `add-late-fee` was lengthened from 40 to 57 characters, because intake
rule L4-OSP-007 (a delta of a capability with no baseline in `openspec/specs/` needs a Purpose of 50+ characters) now
applies to the seeds; the new `seed_set_sha256` is `0169574d...`. **This breaks comparability with every earlier
baseline**, including `docs/eval/2026-10-08/` (`ed59f51d...`), whose cells would be rejected at intake today: the next
live run is a new baseline, and `--compare` against the old one needs `--allow-seed-change` (deltas only). The hash is
computed, not stored; the copy in `tests/integration/golden/eval_scorecard.json` is updated with the seed.

## Command lines

Put `--out` outside `/tmp` (the gate sandbox mounts a tmpfs there; finding H1 of the free run). Warm the uv cache once
(the only step that reaches an index, into `<L4_CACHE>/eval/uv`); each cell then gets a private copy of it inside its own
`L4_CACHE` (`$L4_CACHE/eval-uv`: `l4 run` refuses a cache path outside its runner cache, and no cell writes the shared
one) and runs `uv sync --frozen --offline`:

```
uv run l4 eval --warm-cache
uv run l4 eval --config profiles.yaml --impl f-big-pickle --impl f-mimo --ref-judge claude-code \
    --out ~/eval/2026-10-07 --runner --idle-check scripts/runner/eval-quiet.sh
uv run l4 eval --config profiles.yaml --judge f-big-pickle --judge f-muse --out ~/eval/2026-10-07-judges
uv run l4 eval --config profiles.yaml --impl f-mimo --ref-judge claude-code --dry-run     # the matrix, nothing started
```

`--config` is a file with a `profiles:` mapping (the same shape as `.l4/config.yaml`, so a project's own config works
as is); a cell keeps of it only the profiles and the `sandbox` and `availability` sections (a slow local model such as
`magnitude-qwen` needs the project's `probe_timeout`). One cell runs at a time; a 429 on a profile stops that profile for
the run; `--resume` with the same `--out` skips cells already measured (`pass` or `fail`) on the same seed set in the
same environment (harness commit, templates, CLI versions, uv and OpenSpec versions, profiles, kept sections); an
`invalid` cell (a 429, a busy runner, a harness error) runs again. `<out>/scorecard.json` (canonical JSON, `l4/eval-scorecard@1`)
is rewritten after every cell and is the only file `--compare` reads; `scorecard.md` is the same for people. A profile
may declare `options.free: true` so its cost reads `0.0` instead of `null`.

Runner rules: run as `gitlab-runner`, start cells only when the runner is quiet (`--idle-check`; past `--idle-wait` the
run stops with exit 12). `scripts/dev/l4_idle.py` reads GitLab through Mintkey and runs on the maintainer's Mac only; on
the runner use `scripts/runner/eval-quiet.sh` (no CI job running on this runner and no hold file, which a loop on the Mac
sets while `l4_idle.py` says busy; [eval/README.md](eval/README.md)), never copy or refresh CLI logins, never print the Mintkey secrets
`magnetude-api-key` and `typesafe-jev-api-key`. Nothing in the run directory holds a raw prompt or an unredacted log.

## The gate and the practice

```
uv run l4 eval --compare docs/eval/<baseline>/scorecard.json --new <out>/scorecard.json   # two files, no agent
uv run l4 eval --config profiles.yaml --impl ... --ref-judge ... --out <out> --compare docs/eval/<baseline>/scorecard.json
uv run l4 eval --baseline-dir docs/eval --new <out>/scorecard.json   # newest baseline of the same seed set
```

Exit 0: nothing regressed. **Exit 15** (`regression`): a profile's pass rate fell by more than `--max-drop`, a judge's
agreement fell by more, a judge now passes a defect the baseline did not miss (at any threshold, even when the
baseline's cell for it was invalid or the profile is otherwise unrated), or with `--require-all` a baseline profile was
not evaluated. Exit 2: a missing or invalid file, different seed sets, an incomplete scorecard (`complete: false`: finish
it with `--resume`), or **nothing compared** (no profile has a cell rated in both scorecards: a gate with no evidence
never passes). Only the cells present and rated in both scorecards are compared; a profile that is more than half
`invalid` in either is `unrated`. `--baseline-dir` takes the newest complete baseline that started before the new run,
never the new scorecard itself (so `--out docs/eval/<date>` is safe). The report
begins with the environment diff (harness commit, template versions, CLI versions, models, options, machine).

**Run `l4 eval --compare`** (a) on every bump of a template version, (b) on every CLI pin bump
(`recorded_versions.json`, [runner/README.md](runner/README.md)), (c) before removing a free model from a chain. When the
gate passes, or the regression is accepted with a note, **commit the new scorecard** under `docs/eval/<date>/` as the
next baseline. Baselines are made on the runner after a live run, never in CI. `l4 doctor` row `EVAL-001` warns when a
template differs from the newest baseline; it is a reminder, never a gate.
