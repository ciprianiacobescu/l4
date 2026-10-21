# Laya round 2 (2026-10-08): stopped at the shortcut check, before training

**Verdict.** No checkpoint was trained, no engine was scored, and there is no comparison table this round. The first
data set that includes sample-consumer units failed the shortcut check that runs before training. On the test
split, one token (`inventory`) decides `relevant` / `unrelated` with 0.938 accuracy and 0.907 balanced accuracy. The
rule stops training at 0.9 or above (`m16-progress.md`, "Shortcut check, before training").

* No checkpoint can be deployed. The engine order from 2026-10-07 stands unchanged ([free-resources.md](../free-resources.md)
  §13: `s1_judge` is `[laya, ollama-tev1, ...]` in both projects).
* Jev requests: 0. Calls to Ollama tev1: 0. Laya runs: 0.

Labels: **[V]** re-checked in this session from the files, **[I]** inferred.

sample-consumer (GitLab 119) is private. This file therefore gives only aggregate numbers for it: no unit names, no
paths, no module names and no state text. Everything derived from it is kept under the session scratchpad
(`<scratch>/laya2/`), with a copy in the git-ignored `docs/adoption/sample-consumer/live/laya2/`.

## How the data set was made

1. **Clones.** I made fresh clones of `example-group/dummy-agentic` and sample-consumer:
   * every branch is a local branch;
   * the push URL is `/nonexistent/read-only`;
   * nothing was pushed.

   I also built a fresh `py_multi` (`build_repo`, root `e13e7b2e`).

   sample-consumer has project key `git-4103b23e74dd`. The other two keys are as in [README.md](README.md).
2. **Harness fix before the canary** (`cc03f62`, on `main`). The defect was in `find_source_units`, which took a merged
   unit's archive commit (`L4-Phase: archived`) as the unit's head:
   * the scope is read at the base, and the archive path does not exist there;
   * so no file got a label;
   * so every merged sample-consumer unit came out `baseline_failed`.

   The fix skips archive commits when it chooses the head. The test is `tests/unit/s1/test_canary_archived.py`. It fails
   without the fix, and it passed again in this session (1 passed) [V].
3. **Canary.** The command was:

   ```
   L4_CACHE=<scratch>/laya2/cache L4_S1_CANARY_ROOTS=<scratch>/laya2 l4 s1 canary --repo <sample-consumer> --also-repo <dummy> --also-repo <py_multi> --seed 1606 --target 600 --test-command "<sample-consumer venv python> -m pytest -q -p no:cacheprovider --junitxml=.l4-out/junit.xml -o pythonpath=src --ignore=<one sample-consumer test module>"
   ```

   * The `--ignore` leaves out one sample-consumer test module, which spends about 20 s in sleeps on every run.
   * The venv has sample-consumer installed editable, plus the extras its tests need.

   Results [V, canary log]:
   * **2390 items.** Classes:

     | set | false | true |
     |---|---|---|
     | `change-covered@1` | 494 | 426 |
     | `file-relevant@1` | 253 | 743 |
     | `tests-ok@2` | 316 | 158 |

   * **Units:** 44 in all (dummy-agentic 24 and sample-consumer 12, both counts including fix units, plus py_multi 8).
     5 baselines failed (`none:baseline_failed` 5, `none:ok` 39), so 39 units reached the export.
   * **Exit 2. The quotas were not met**, verbatim: `l4/file-relevant@1/relevant=false: share 25% below 30%;
     l4/file-relevant@1/relevant=false: 27 in the test split, 30 wanted`. The targets were not lowered.
4. **Export.** `l4 s1 export --seed 1606` gave **2129 rows**, after a balance cut of 261.
   * Splits: train 1566, calib 306, test 257. Source units: 27 / 6 / 6.
   * Label sources: `deterministic:diff-coverage` 920, `deterministic:scope` 759 and `deterministic:tests-ran` 450.
     Nothing else: 0 rows were rejected for their label source. No engine answer is a label (TypeSafe MCA §2.3(b)).
   * `laya-evals validate` (laya 0.3.24, `uv run --isolated --no-project --python 3.12 --with laya==0.3.24`) exits 0 for
     each split: 1566, 306 and 257 examples, 7 question ids [V, run in this session].
   * The manifest is [manifest-2026-10-08.json](manifest-2026-10-08.json). It holds counts only.

### Rows per split

| split | dummy-agentic mutated / untouched | sample-consumer mutated / untouched | py_multi mutated / untouched | units |
|---|---|---|---|---|
| train | 841 / 80 | 108 / 15 | 495 / 27 | 27 |
| calib | 111 / 16 | 58 / 22 | 95 / 4 | 6 |
| test | 119 / 12 | 35 / 8 | 80 / 3 | 6: dummy-agentic 4 (`add-is-empty`, `add-item-count`, `add-return-notice`, `show-item-count`), sample-consumer 1, py_multi 1 (`cart-totals`) |

"Mutated" rows are synthetic mutations, even when the repository is real.

Class balance, true / false:

| question | train | calib | test |
|---|---|---|---|
| relevant | 366 / 183 | 86 / 43 | 54 / 27 |
| exercised | 338 / 343 | 47 / 76 | 41 / 75 |
| all_passed | 120 / 216 | 18 / 36 | 20 / 40 |

## Shortcut check (before training)

The check finds the best single token per question, chosen on train and scored on test. The output is
[shortcuts-2026-10-08.json](shortcuts-2026-10-08.json). I recomputed the `inventory` and `not` rows from the split files
[V].

| question | token (bigram) | train acc | test acc | test balanced acc | test majority | stops training? |
|---|---|---|---|---|---|---|
| relevant / unrelated | `inventory` (`/ inventory`) | 0.811 | **0.938** | 0.907 | 0.667 | **yes** |
| relatedness | `inventory` | 0.777 | 0.891 | 0.907 | 0.587 | borderline (score question, outside the gate policy) |
| all_passed | `not` (`0 skipped`) | 0.827 | 0.883 | **0.912** | 0.667 | borderline (balanced accuracy only) |
| exercised / untested / extent | `def` (`: def`) | 0.794 | 0.802 | 0.758 | 0.647 | no |

### Why `inventory` decides the test split

The rule tested here is "if `inventory` is in the state, answer no". These are the test `relevant` rows by project [V]:

| project | `inventory` in the state | n | stump right |
|---|---|---|---|
| dummy-agentic | yes | 12 | 12 (all `false`) |
| dummy-agentic | no | 40 | 40 (all `true`) |
| py_multi | yes | 10 | 10 (all `false`) |
| py_multi | no | 11 | 10 |
| sample-consumer | no | 8 | 4 (its 4 `false` rows have no `inventory`) |

The stump gets 76 of 81 right and makes 5 errors: 4 on sample-consumer rows and 1 on a py_multi row. The data report counted only
the 4 sample-consumer rows.

Every `inventory` row in the test split is a `template_edit` or `transplant_hunk` row labelled out of scope. In
dummy-agentic and py_multi, these two mutations always put the out-of-scope file in the same "other" module. In train, every one of those rows
in the two repositories contains `inventory` [V, counts by mutation].

Rows with `inventory`, true / false:

| split | true | false |
|---|---|---|
| train | 83 | 162 |
| calib | 18 | 30 |
| test | **0** | **22** |

So a tuned model that learned "`inventory` means out of scope", without reading the declared scope, would still score
about 0.94 on test. The test split cannot tell that model from one that reads the spec.

That is why the stop is about the data, not about Laya. The 0.9 rule exists because the earlier checkpoints learned
the canary templates and then failed the gate (rounds 4 and 5 in `m16-progress.md`).

### `not` and `0 skipped` (all_passed)

These tokens come from the "Not passed" block and the run counts in the tests-ok state. That state carries its own
answer: round 4 already found the sanity question decidable by bag-of-words. The score is 0.883 accuracy and 0.912
balanced accuracy, so the token is a shortcut on balanced accuracy only.

## Real versus synthetic labels

* **There are still no real negatives, sample-consumer included [V].** None of the 187 untouched rows
  (`mutation:none`: dummy-agentic 108, sample-consumer 45, py_multi 34) is labelled `relevant=false` or
  `exercised=false`.
  * Every `relevant=false` and every `exercised=false` row comes from a mutation.
  * The merged sample-consumer units have no real out-of-scope file.
* **`all_passed` on sample-consumer is degenerate [V].** All 57 sample-consumer `all_passed` rows (train 32, calib 16, test 9)
  are `false`, because sample-consumer's suite always has a skipped test. Under `tests-ok@2`, any skipped test makes `all_passed`
  false. So sample-consumer contributes no positive class there, and a real sample-consumer run with that skip would always be "not all passed".
* **The real-repository slice of the test split is small.** sample-consumer has one unit (43 rows), with
  `relevant` 4 true / 4 false (the 4 false are mutations). dummy-agentic has 4 units.

## Why there is no engine comparison

The guard is D1, the order rule from round 3. `l4 s1 score` refuses an exported calib or test split for every engine
except `laya-local` unless it gets a `--gate gate.json` whose `test_sha256` is that file. `l4 s1 report` refuses the same
way.

No checkpoint was trained, so no `gate.json` exists for this split. That guard alone blocks Jev and Ollama `tev1` on
it (and would block a tuned checkpoint that has no gate). Base Laya (`laya-local`) is exempt from the guard; it was not
scored because the round stops at the data check, and a base-only number has no tuned side and no gate to read it
against.

The `ollama` engine is on `main` (`l4/llm/system_one.py`, `ENGINES`), but this round did not use it. The latest engine
numbers are still the 2026-10-07 tev1 addendum on the 2026-10-05-live split (README, free-resources §13).

## What has to change before round 3 (recommendation, not done)

1. **Mutation targets.** `template_edit` and `transplant_hunk` must not always land in one module per repository.
   * Draw donors and targets from several modules, including other modules of the same package.
   * Also generate in-scope edits inside the module that is currently "always other", so that its name appears with
     both labels in every split.
2. **The split.** Do one or both of these:
   * hold out whole projects (split by `project:` key);
   * check before training that every token which is a strong train-split feature appears with both labels in test.

   Also run the shortcut check per project, so that a tell confined to one repository is visible.
3. **Real out-of-scope labels.** The canary cannot produce them from these repositories. They have to come from
   `human:verdict` labels on real scope holds (join line 29 writes them), or from real units in repositories with more
   than one package.
4. **sample-consumer and `tests-ok`.** Either leave sample-consumer out of `tests-ok@2` until its always-skipped test is fixed, or
   accept that sample-consumer gives only negatives there. Do not change the label rule to suit one repository.
5. **The quotas** (`relevant=false` share and test count) stay unmet until 1 and 3 are done.

## Files

The following files are committed. They hold counts and tokens only; neither contains a unit name or source text:

* `manifest-2026-10-08.json` (sha256 `1d08413dd8d508562ae86ee6968bf63e5a145aef9d015c634855586ae10caa2d`);
* `shortcuts-2026-10-08.json` (sha256 `209c73b29c6d990d7d0e27ee60271ca67045a652e80ee8e0c9110e309b036f6c`).

The rest are not committed, because they carry source text of a private repository. They are pinned by sha256 and kept
under `<scratch>/laya2/` and the git-ignored `docs/adoption/sample-consumer/live/laya2/`:

| file | sha256 |
|---|---|
| `canary.jsonl` | `527f965a25c727d4409cac3c73bee3b1f9336bfe1d3468060225dc0a725e8a1f` |
| `train.jsonl` | `e32700755d9e8e79a3c72b5083dba56bfaea1d63342439e7ed9c720d8786c192` |
| `calib.jsonl` | `7bdf20dcdbeb10b25217a6467af28f1b7e09072c95f7c96a5263be8fbe3ecfe6` |
| `test.jsonl` | `d1ed69451e6aee3ea07245e3e4aa72266f39e3b98a4767eef9d76597f5091650` |
| data set (`manifest.json` `dataset_sha256`) | `d3efaaabc57ffe10988274e43f81f1c859ed6ac78140ab3b3ef7c7e3c520a7d6` |

The canary log names sample-consumer units, so it is not committed either.
