version: 3

# Phase: SINGLE (fix one finding, no new test)
{result_values}
This task fixes a finding the verifier reported against the committed work, and no criterion of the unit needs a new test for it: the finding is in the data block of the proposal that names it by id, and the task title cites that id. Change only what the finding needs, and nothing else. Do not add tests and do not weaken or delete existing ones.
If the task begins with a decision by a human ("Decided by ... in Q-..."), your change MUST do what that decision describes; a change that keeps the behaviour the decision calls wrong is rejected.
When you are done, run the gate command: every test that passed before must still pass.
