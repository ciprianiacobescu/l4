# S1 comparison on `test.jsonl`

**GATE FAILED: the tuned checkpoint did not pass the laya-evals gate. It is not deployable; its numbers below are for comparison only.**

* gate failure: slice mutation:add_passing_test on exercised: tuned accuracy 0.88 (n=17) is below base Laya's 1.00 (n=17)
* gate failure: slice mutation:add_passing_test on untested: tuned accuracy 0.76 (n=17) is below base Laya's 0.94 (n=17)
* gate failure: slice mutation:none on exercised: tuned accuracy 0.67 (n=6) is below base Laya's 1.00 (n=6)
* gate failure: slice mutation:none on untested: tuned accuracy 0.50 (n=6) is below base Laya's 1.00 (n=6)
* gate failure: temperature[2] sits on Laya's clamp (5.47): the confidences are uncalibrated

dataset sha256 `ae31fe7faea073674d6a2604d66b01c5eb6a03d6f2560670d3e5506c9a804a78`

Scored against ground truth only. Engine answers were never used as labels (TypeSafe MCA 2.3(b)).

Tuned checkpoint gate: FAILED; cross-check against laya-evals ok. Not deployable.

## laya (laya-local, typed-decisions)

147 rows scored, 0 failed.

| question | n | accuracy | 95% Wilson | ECE | Brier | averaged acc |
|---|---|---|---|---|---|---|
| l4/change-covered@1/exercised | 72 | 0.486 | 0.37-0.60 | 0.262 | 0.276 | - |
| l4/change-covered@1/extent | 72 | 0.111 | 0.06-0.20 | 0.301 | 0.840 | - |
| l4/change-covered@1/untested | 72 | 0.403 | 0.30-0.52 | 0.124 | 0.257 | - |
| l4/file-relevant@1/relatedness | 18 | 0.333 | 0.16-0.56 | 0.356 | 0.717 | - |
| l4/file-relevant@1/relevant | 33 | 0.909 | 0.76-0.97 | 0.350 | 0.206 | - |
| l4/file-relevant@1/unrelated | 33 | 0.667 | 0.50-0.80 | 0.219 | 0.202 | - |
| l4/tests-ok@2/all_passed | 42 | 0.548 | 0.40-0.69 | 0.231 | 0.237 | - |

Slices (canonical, accuracy and n):

* `mutation:add_passing_test`: change-covered@1/exercised 1.000 (n=17), change-covered@1/extent 0.353 (n=17), change-covered@1/untested 0.941 (n=17), file-relevant@1/relevant 1.000 (n=2), file-relevant@1/unrelated 1.000 (n=2), tests-ok@2/all_passed 0.583 (n=12)
* `mutation:break_test`: file-relevant@1/relevant 1.000 (n=3), file-relevant@1/unrelated 1.000 (n=3), tests-ok@2/all_passed 0.857 (n=7)
* `mutation:drop_covering_test`: change-covered@1/exercised 0.500 (n=6), change-covered@1/extent 0.000 (n=6), change-covered@1/untested 0.333 (n=6), file-relevant@1/relevant 1.000 (n=2), file-relevant@1/unrelated 1.000 (n=2), tests-ok@2/all_passed 0.500 (n=6)
* `mutation:none`: change-covered@1/exercised 1.000 (n=6), change-covered@1/extent 0.333 (n=6), change-covered@1/untested 1.000 (n=6), file-relevant@1/relatedness 0.000 (n=1), file-relevant@1/relevant 1.000 (n=3), file-relevant@1/unrelated 1.000 (n=3), tests-ok@2/all_passed 0.667 (n=3)
* `mutation:skip_old_test`: file-relevant@1/relatedness 0.000 (n=1), file-relevant@1/relevant 0.571 (n=7), file-relevant@1/unrelated 0.857 (n=7), tests-ok@2/all_passed 0.357 (n=14)
* `mutation:template_edit`: change-covered@1/exercised 1.000 (n=6), change-covered@1/extent 0.000 (n=6), change-covered@1/untested 0.167 (n=6), file-relevant@1/relatedness 0.000 (n=6), file-relevant@1/relevant 1.000 (n=6), file-relevant@1/unrelated 0.167 (n=6)
* `mutation:transplant_hunk`: change-covered@1/exercised 0.158 (n=19), change-covered@1/extent 0.000 (n=19), change-covered@1/untested 0.211 (n=19), file-relevant@1/relatedness 0.000 (n=4), file-relevant@1/relevant 1.000 (n=4), file-relevant@1/unrelated 0.000 (n=4)
* `mutation:untested_function`: change-covered@1/exercised 0.000 (n=18), change-covered@1/extent 0.000 (n=18), change-covered@1/untested 0.000 (n=18), file-relevant@1/relatedness 1.000 (n=6), file-relevant@1/relevant 1.000 (n=6), file-relevant@1/unrelated 0.833 (n=6)
* `origin:canary`: change-covered@1/exercised 0.486 (n=72), change-covered@1/extent 0.111 (n=72), change-covered@1/untested 0.403 (n=72), file-relevant@1/relatedness 0.333 (n=18), file-relevant@1/relevant 0.909 (n=33), file-relevant@1/unrelated 0.667 (n=33), tests-ok@2/all_passed 0.548 (n=42)
* `project:git-35b5a131ecf1`: change-covered@1/exercised 0.458 (n=24), change-covered@1/extent 0.042 (n=24), change-covered@1/untested 0.417 (n=24), file-relevant@1/relatedness 0.833 (n=6), file-relevant@1/relevant 1.000 (n=13), file-relevant@1/unrelated 1.000 (n=13), tests-ok@2/all_passed 0.538 (n=26)
* `project:git-e13e7b2e670c`: change-covered@1/exercised 0.500 (n=48), change-covered@1/extent 0.146 (n=48), change-covered@1/untested 0.396 (n=48), file-relevant@1/relatedness 0.083 (n=12), file-relevant@1/relevant 0.850 (n=20), file-relevant@1/unrelated 0.450 (n=20), tests-ok@2/all_passed 0.562 (n=16)

## laya-tuned (laya-local, typed-decisions)

147 rows scored, 0 failed.

| question | n | accuracy | 95% Wilson | ECE | Brier | averaged acc |
|---|---|---|---|---|---|---|
| l4/change-covered@1/exercised | 72 | 0.889 | 0.80-0.94 | 0.107 | 0.103 | - |
| l4/change-covered@1/extent | 72 | 0.861 | 0.76-0.92 | 0.058 | 0.184 | - |
| l4/change-covered@1/untested | 72 | 0.889 | 0.80-0.94 | 0.078 | 0.088 | - |
| l4/file-relevant@1/relatedness | 18 | 0.944 | 0.74-0.99 | 0.034 | 0.103 | - |
| l4/file-relevant@1/relevant | 33 | 0.970 | 0.85-0.99 | 0.033 | 0.012 | - |
| l4/file-relevant@1/unrelated | 33 | 1.000 | 0.90-1.00 | 0.035 | 0.007 | - |
| l4/tests-ok@2/all_passed | 42 | 1.000 | 0.92-1.00 | 0.013 | 0.000 | - |

Slices (canonical, accuracy and n):

* `mutation:add_passing_test`: change-covered@1/exercised 0.882 (n=17), change-covered@1/extent 0.647 (n=17), change-covered@1/untested 0.765 (n=17), file-relevant@1/relevant 1.000 (n=2), file-relevant@1/unrelated 1.000 (n=2), tests-ok@2/all_passed 1.000 (n=12)
* `mutation:break_test`: file-relevant@1/relevant 1.000 (n=3), file-relevant@1/unrelated 1.000 (n=3), tests-ok@2/all_passed 1.000 (n=7)
* `mutation:drop_covering_test`: change-covered@1/exercised 0.667 (n=6), change-covered@1/extent 1.000 (n=6), change-covered@1/untested 1.000 (n=6), file-relevant@1/relevant 1.000 (n=2), file-relevant@1/unrelated 1.000 (n=2), tests-ok@2/all_passed 1.000 (n=6)
* `mutation:none`: change-covered@1/exercised 0.667 (n=6), change-covered@1/extent 0.500 (n=6), change-covered@1/untested 0.500 (n=6), file-relevant@1/relatedness 0.000 (n=1), file-relevant@1/relevant 1.000 (n=3), file-relevant@1/unrelated 1.000 (n=3), tests-ok@2/all_passed 1.000 (n=3)
* `mutation:skip_old_test`: file-relevant@1/relatedness 1.000 (n=1), file-relevant@1/relevant 0.857 (n=7), file-relevant@1/unrelated 1.000 (n=7), tests-ok@2/all_passed 1.000 (n=14)
* `mutation:template_edit`: change-covered@1/exercised 1.000 (n=6), change-covered@1/extent 1.000 (n=6), change-covered@1/untested 1.000 (n=6), file-relevant@1/relatedness 1.000 (n=6), file-relevant@1/relevant 1.000 (n=6), file-relevant@1/unrelated 1.000 (n=6)
* `mutation:transplant_hunk`: change-covered@1/exercised 0.895 (n=19), change-covered@1/extent 0.947 (n=19), change-covered@1/untested 0.947 (n=19), file-relevant@1/relatedness 1.000 (n=4), file-relevant@1/relevant 1.000 (n=4), file-relevant@1/unrelated 1.000 (n=4)
* `mutation:untested_function`: change-covered@1/exercised 1.000 (n=18), change-covered@1/extent 1.000 (n=18), change-covered@1/untested 1.000 (n=18), file-relevant@1/relatedness 1.000 (n=6), file-relevant@1/relevant 1.000 (n=6), file-relevant@1/unrelated 1.000 (n=6)
* `origin:canary`: change-covered@1/exercised 0.889 (n=72), change-covered@1/extent 0.861 (n=72), change-covered@1/untested 0.889 (n=72), file-relevant@1/relatedness 0.944 (n=18), file-relevant@1/relevant 0.970 (n=33), file-relevant@1/unrelated 1.000 (n=33), tests-ok@2/all_passed 1.000 (n=42)
* `project:git-35b5a131ecf1`: change-covered@1/exercised 0.917 (n=24), change-covered@1/extent 0.917 (n=24), change-covered@1/untested 0.917 (n=24), file-relevant@1/relatedness 0.833 (n=6), file-relevant@1/relevant 1.000 (n=13), file-relevant@1/unrelated 1.000 (n=13), tests-ok@2/all_passed 1.000 (n=26)
* `project:git-e13e7b2e670c`: change-covered@1/exercised 0.875 (n=48), change-covered@1/extent 0.833 (n=48), change-covered@1/untested 0.875 (n=48), file-relevant@1/relatedness 1.000 (n=12), file-relevant@1/relevant 0.950 (n=20), file-relevant@1/unrelated 1.000 (n=20), tests-ok@2/all_passed 1.000 (n=16)

## jev (jev, jev-1.13.0)

60 rows scored, 0 failed.

| question | n | accuracy | 95% Wilson | ECE | Brier | averaged acc |
|---|---|---|---|---|---|---|
| l4/change-covered@1/exercised | 26 | 0.577 | 0.39-0.74 | 0.350 | 0.307 | - |
| l4/change-covered@1/extent | 26 | 0.538 | 0.35-0.71 | 0.293 | 0.615 | - |
| l4/change-covered@1/untested | 26 | 0.577 | 0.39-0.74 | 0.325 | 0.296 | - |
| l4/file-relevant@1/relatedness | 8 | 0.875 | 0.53-0.98 | 0.122 | 0.178 | - |
| l4/file-relevant@1/relevant | 17 | 0.824 | 0.59-0.94 | 0.102 | 0.125 | - |
| l4/file-relevant@1/unrelated | 17 | 0.882 | 0.66-0.97 | 0.131 | 0.094 | - |
| l4/tests-ok@2/all_passed | 17 | 1.000 | 0.82-1.00 | 0.033 | 0.006 | - |

Slices (canonical, accuracy and n):

* `mutation:add_passing_test`: change-covered@1/exercised 0.750 (n=4), change-covered@1/extent 0.750 (n=4), change-covered@1/untested 0.750 (n=4), file-relevant@1/relevant 1.000 (n=1), file-relevant@1/unrelated 1.000 (n=1), tests-ok@2/all_passed 1.000 (n=5)
* `mutation:break_test`: file-relevant@1/relevant 1.000 (n=2), file-relevant@1/unrelated 1.000 (n=2), tests-ok@2/all_passed 1.000 (n=2)
* `mutation:drop_covering_test`: change-covered@1/exercised 0.667 (n=3), change-covered@1/extent 0.333 (n=3), change-covered@1/untested 0.667 (n=3), file-relevant@1/relevant 1.000 (n=1), file-relevant@1/unrelated 1.000 (n=1), tests-ok@2/all_passed 1.000 (n=4)
* `mutation:none`: change-covered@1/exercised 0.500 (n=2), change-covered@1/extent 0.500 (n=2), change-covered@1/untested 0.500 (n=2), file-relevant@1/relatedness 0.000 (n=1), file-relevant@1/relevant 1.000 (n=2), file-relevant@1/unrelated 1.000 (n=2), tests-ok@2/all_passed 1.000 (n=1)
* `mutation:skip_old_test`: file-relevant@1/relatedness 1.000 (n=1), file-relevant@1/relevant 0.400 (n=5), file-relevant@1/unrelated 0.600 (n=5), tests-ok@2/all_passed 1.000 (n=5)
* `mutation:template_edit`: change-covered@1/exercised 0.000 (n=1), change-covered@1/extent 0.000 (n=1), change-covered@1/untested 0.000 (n=1), file-relevant@1/relatedness 1.000 (n=3), file-relevant@1/relevant 1.000 (n=3), file-relevant@1/unrelated 1.000 (n=3)
* `mutation:transplant_hunk`: change-covered@1/exercised 0.300 (n=10), change-covered@1/extent 0.300 (n=10), change-covered@1/untested 0.300 (n=10)
* `mutation:untested_function`: change-covered@1/exercised 1.000 (n=6), change-covered@1/extent 1.000 (n=6), change-covered@1/untested 1.000 (n=6), file-relevant@1/relatedness 1.000 (n=3), file-relevant@1/relevant 1.000 (n=3), file-relevant@1/unrelated 1.000 (n=3)
* `origin:canary`: change-covered@1/exercised 0.577 (n=26), change-covered@1/extent 0.538 (n=26), change-covered@1/untested 0.577 (n=26), file-relevant@1/relatedness 0.875 (n=8), file-relevant@1/relevant 0.824 (n=17), file-relevant@1/unrelated 0.882 (n=17), tests-ok@2/all_passed 1.000 (n=17)
* `project:git-35b5a131ecf1`: change-covered@1/exercised 0.778 (n=9), change-covered@1/extent 0.667 (n=9), change-covered@1/untested 0.778 (n=9), file-relevant@1/relatedness 0.667 (n=3), file-relevant@1/relevant 0.714 (n=7), file-relevant@1/unrelated 0.714 (n=7), tests-ok@2/all_passed 1.000 (n=10)
* `project:git-e13e7b2e670c`: change-covered@1/exercised 0.471 (n=17), change-covered@1/extent 0.471 (n=17), change-covered@1/untested 0.471 (n=17), file-relevant@1/relatedness 1.000 (n=5), file-relevant@1/relevant 0.900 (n=10), file-relevant@1/unrelated 1.000 (n=10), tests-ok@2/all_passed 1.000 (n=7)
