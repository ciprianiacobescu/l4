# Design: a test in a file of another language is found, and is not rejected by runs that cannot reach it

## D1. One lookup for a test's file, in its own module

Three places follow a test id to its file, each its own way: `discrimination._test_file` (dotted Python modules only),
`earlier_red._test_file` (the head as a path, or a dotted Python module, at a commit) and `held_patch._test_path` (the
same in the work tree). None maps a dotted id whose file is not Python. `test_locate.file_of_id` is pure: it takes the
id and the list of paths, so the caller decides which files count (the work tree's, with untracked ones, because a
held step's new test files are untracked when the question is written) and the tests need no repository.

The head is the id's part before its first `::`. In order:

1. the head itself is one of the paths (`src/pricing/total.test.ts::…`, the slash form some reporters write);
2. a path whose `/`-to-`.` form equals the head (`src.pricing.total.test.ts`): exactly one → it; several → the one in
   `preferred` if exactly one is, else None (no later step is tried);
3. a dotted Python module: the longest dotted prefix whose `/`-joined form plus `.py` is a path (as today);
4. the paths whose `/`-to-`.` form ends with `.` + head (a reporter whose classname starts below the repository
   root): exactly one → it; several → the one in `preferred` if exactly one is; else None.

The exact dotted path comes before the module walk because the walk would read `src.pricing.total.test.ts` as the
module `src/pricing/total.py` (or `src/pricing.py`, or `src.py`) when such a Python file lies beside the test, and the
TypeScript test would then be taken for a Python one. `preferred` may be given as a function, so that the step's
changed files are listed only when several paths match.

A file name may hold dots (`total.v2.test.ts`), so the head is never split to guess a path: only whole paths are
compared. A pre-filter on the last dotted part keeps it cheap on a large repository.

## D2. The test's own lines

`window(text, name)` looks for the line of a test call that names the test: a line where `test`, `it`, `describe`,
`suite` or `bench` (also with `.only`, `.skip`, `.each` before the paren) opens with a string literal that is a suffix
of the reported name (reporters join describe names with a space or ` > `), or Go's `func <name>(`. Of the candidates
the longest literal wins; with none, the first line that holds the name. From that line the window runs to the first
later non-blank line indented no deeper than it, including that line when it only closes (`}`, `});`, `})`), and at
most 40 lines (`MAX_SOURCE_LINES`, the existing cut still applies after redaction). Nothing found → None, and the
question says `(the source of this test was not found)` as before.

## D3. Not reached is not rejected

Both runs change Python files on disk. A test in a file that is not Python normally loads none of them, so passing both
runs says nothing about whether it checks the answer. The runs are still made as before (a test in another language
can reach Python code through a process the gate starts; if a run then makes it fail by assertion, that is a proof and
it is accepted). Only the rejection changes: such a test that no run accepted is inconclusive with `NOT_PYTHON`. A test
that failed on the base by an error keeps `ERROR_AT_BASE` and is rejected: the base run did reach it.

Which file a test is in comes from `file_of_id` over the work tree's files. A test whose file is not found keeps today's
rules (a Python test id in an unusual layout must not become inconclusive by accident).

## D4. No run, no rejection

`discriminate_extra` rejects a test only when a run was made that could have made it fail. When `made` is empty, every
test is inconclusive: `NO_RUN` when the zero-value scope and the production files were both empty (0.4.37), `NO_ZERO`
when the scope had files but `zeroed_run` could vary none and there was no production file to swap.

## D5. The hold and the failure say what happened

`ExtraRun.made` is the tuple of run names in the order made. The hold's `runs` is `outcome.made`, so the question's
`Runs:` line is `test-extra-zero` when only that run was made. With some tests rejected and the others inconclusive, the
chore still fails (a rejected test shows a test of the chore that the runs could reach does not check the answer), but
the text lists only the rejected ones as passing both runs, and then `<test>: inconclusive: <reason>` for the others
(capped like today's list).

## D6. What does not change

- Step 4 of the verifier (`ladder._extra_proof_step`) takes only tests whose file `file_of_test` finds, which is Python
  only. A test in another language stays no candidate there and keeps its `no proof` finding.
- `earlier_red._test_file` reads files at a commit, not the work tree; it is left as it is.
- The 40-line cap of a diff in the question stays: the test's own source now carries the assertions.
