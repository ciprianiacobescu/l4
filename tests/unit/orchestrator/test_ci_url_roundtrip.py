"""`run.started.ci_url` round trip: committed with `<forge>`, shown by `l4 status --unit` as a real link
(run-liveness 4.2, design D6, SCN-OPS-34)."""

import json

import pytest

from l4.cli import main

from ..implementer.conftest import red_step
from .conftest import BRANCH, UNIT, UNIT_DIR

PLAIN = "https://github.com/owner/repo.git"
SCP = "git@github.com:owner/repo.git"
LINK = "https://github.com/owner/repo/actions/runs/123"


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


@pytest.mark.parametrize("remote", [PLAIN, SCP], ids=["https origin", "ssh origin"])
def test_the_ci_link_is_committed_with_the_placeholder_and_status_expands_it(run_l4, tdd_repo, raw, remote, capsys):
    # `origin` is on github.com by name; git still pushes to the bare repository behind it
    raw(tdd_repo.repo, "config", f"url.{tdd_repo.origin}.insteadOf", remote)
    raw(tdd_repo.repo, "remote", "set-url", "origin", remote)
    tdd_repo.environ.update(
        {"GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "owner/repo",
         "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
    )  # fmt: skip
    run = run_l4([red_step()])  # the script ends after the red step: the run stops with no `run.finished` on the branch
    started = run.events("run.started")[0]
    assert started["ci_url"] == "<forge>/owner/repo/actions/runs/123"
    assert "https://github.com" not in run.pushed(
        f"openspec/changes/add-discount-codes/.l4/ledger/{started['run_id']}.jsonl"
    )
    # a run that was lost after its last step commit: the branch ledger has no `run.finished`
    clone = tdd_repo.repo.parent / "lost-runner"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    ledger = clone / UNIT_DIR / ".l4" / "ledger" / f"{started['run_id']}.jsonl"
    kept = [
        x for x in ledger.read_text().splitlines() if json.loads(x)["type"] not in ("run.finished", "lock.released")
    ]
    ledger.write_text("\n".join(kept) + "\n")
    raw(clone, "add", "-A")
    raw(clone, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "lost runner")
    raw(clone, "push", "-q", "origin", BRANCH)
    for ref in raw(tdd_repo.origin, "for-each-ref", "--format=%(refname)", "refs/l4/locks").split():
        raw(tdd_repo.origin, "update-ref", "-d", ref)
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    capsys.readouterr()
    code = main(["status", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    out = capsys.readouterr().out
    assert code == 0
    assert f"no end recorded: {LINK}" in out
    assert "<forge>" not in out
