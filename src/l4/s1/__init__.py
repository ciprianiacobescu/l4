"""S1 questions, records, data set and canaries (M1.6 Stage B).

Jev's output is never a training label or a selection signal (TypeSafe MCA 2.3(b), plan D1): `export`, `canary`
and `labels` read ground truth only, and `score` and `report` are the only readers of engine answers.
"""
