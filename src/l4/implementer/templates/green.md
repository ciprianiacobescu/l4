version: 5

# Phase: GREEN (make the red tests pass)
{result_values}
The red tests are committed and frozen: do not edit tests, fixtures, `conftest.py` or test configuration, because the harness restores them. If a red test is genuinely wrong, change nothing and report status blocked with one question of kind technical. The question's title names the test file and the line, its context states the contradiction (what the test asserts, what the spec or design says), and its first option is the exact edit in the form "Edit `<path>`: <the exact change>": a person who accepts that option unfreezes exactly that file for this task. If the prompt lists a test file as unfrozen by a human answer, you may change that file as the answer says; every other test stays frozen. If the prompt lists files under "Files this task names", you may change them as the task says: keep every existing statement, do not patch the unit's code from them, and leave them regular files. An ignore file (`.gitignore`) is never unfrozen.
Implement only what the red tests and this task's criteria need. When you are done, run the gate command: the red tests and every test that passed before must pass.
