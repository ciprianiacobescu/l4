"""Step 1 and the verifier's own e2e tests: a generated test the harness accepted carries no suppression finding,
and a file that only borrows its name is still checked."""

from l4.verifier.integrity import check_suppressions

from .test_integrity import event, new_repo

PATH = "e2e/test_l4_c_aaaaaaaa.py"
BODY = "import os  # noqa: F401\n"


def test_an_accepted_generated_test_is_excused_by_its_recorded_path(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({PATH: BODY})
    head = repo.commit("test: verifier round 1")
    repo.events = [event("verify.generated", 1, criterion="C-aaaaaaaa", status="accepted", test=PATH, tests=[])]
    assert not check_suppressions(repo.context(base, head)).findings


def test_a_refused_attempt_or_a_borrowed_name_excuses_nothing(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({PATH: BODY})
    head = repo.commit("work")
    assert check_suppressions(repo.context(base, head)).findings  # no event at all
    repo.events = [event("verify.generated", 1, criterion="C-aaaaaaaa", status="fails_at_head", test=PATH)]
    assert check_suppressions(repo.context(base, head)).findings
