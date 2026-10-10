"""P5 wired: what the harness commits carries `<forge>` for the forge host, and everything a person or a log reads
keeps the real link."""

import json

from l4.cli import main
from l4.state.lifecycle import Trigger

from ..forge.conftest import API, PROJECT, TOKEN, WEB  # noqa: F401
from .conftest import BRANCH, green_step, red_step  # noqa: F401

MR = f"{WEB}/-/merge_requests/1"
PLACEHOLDER_MR = "<forge>/example-group/dummy-agentic/-/merge_requests/1"


def passing(install_hooks) -> None:
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)


def test_committed_ledgers_hold_the_placeholder_and_the_trace_keeps_the_link(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw, capsys
):
    passing(install_hooks)
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    # the branch's ledger and the lock ref's pending file hold the placeholder, nowhere the host
    committed = [raw(tdd_repo.origin, "show", f"{BRANCH}:{path}") for path in raw(
        tdd_repo.origin, "ls-tree", "-r", "--name-only", BRANCH).split() if path.endswith(".jsonl")]  # fmt: skip
    pending = list(run.pending_files().values())
    assert committed and pending
    for text in [*committed, *pending]:
        assert "gitlab.example.test" not in text
    assert any(f'"url": "{PLACEHOLDER_MR}"' in t or f'"url":"{PLACEHOLDER_MR}"' in t for t in [*committed, *pending])
    (updated,) = [e for e in run.ledger() if e["type"] == "pr.updated"]
    assert updated["url"] == PLACEHOLDER_MR
    # the console line, the JSONL mirror and outcome.json hold the full link
    assert MR in capsys.readouterr().err
    mirror = "".join(p.read_text() for p in (tdd_repo.repo / ".l4-out" / "logs").glob("*.jsonl"))
    assert MR in mirror
    assert run.outcome["units"][0]["pr_url"] == MR
    # and `l4 status` expands the recorded placeholder too
    assert main(["status", "--json", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["units"][0]["pr"] == MR


def test_a_rerun_writes_no_second_pr_updated(run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw):
    """The recorded URL is compared with the live one in canonical form: a ledger of an older harness (full URL) and
    one with the placeholder are the same merge request, so no `pr.updated` is written again."""
    passing(install_hooks)
    first = run_l4([red_step(), green_step()], observability={"redact_forge_urls": False})  # as before M1.9
    assert first.code == 0 and [e["url"] for e in first.events("pr.updated")] == [MR]
    from ..orchestrator.test_review_reentry import human_commit

    human_commit(tdd_repo, raw, {"notes.txt": "a person was here\n"})
    second = run_l4([])  # the placeholder is on again: the unit re-enters review and the MR is looked up
    assert second.code == 0
    assert [e["url"] for e in second.events("pr.updated")] == [MR]  # one event in the whole ledger, the old form


def test_the_sweeper_matches_a_placeholder_url_to_the_merged_mr(tmp_path, raw, git_environ, gitlab):
    from l4.ci.sweeper import Sweeper
    from l4.postmerge import MergeDetector, PostMergeArchiver
    from l4.specs.openspec import OpenSpecProvider
    from l4.state.ledger import LedgerWriter, ledger_path
    from l4.state.pending import PendingLedger
    from l4.state.status import load_snapshot

    from .merged_world import MergedWorld

    world = MergedWorld(tmp_path, raw, git_environ, gitlab).build()
    world.environ["CI_API_V4_URL"] = API  # the forge's host is known from the job's environment
    other = "r-20261004T0950Z-dddd"
    scratch = tmp_path / "scratch"
    writer = LedgerWriter.open(scratch, world.unit_id, other, redactor=world.app().redactor)
    writer.append("pr.updated", url=PLACEHOLDER_MR, number=1, draft=False)  # what M1.9 commits
    writer.finish(0)
    PendingLedger(world.git, lock_ref=f"refs/l4/locks/openspec/{world.name}", unit=world.unit_id, run_id=other).publish(
        ledger_path(scratch, other)
    )
    world.merged_mr()  # the forge lists it with its full URL
    provider = OpenSpecProvider(world.repo, world.environ)
    (snap,) = [load_snapshot(provider, world.git, ref, branch_prefix="l4/") for ref in provider.list_units()]
    assert snap.state.pr == PLACEHOLDER_MR
    app, forge = world.app("r-20261005T1000Z-0001"), world.forge()
    archiver = PostMergeArchiver(world.cfg, app, world.git, forge, provider_for=world.provider_for)
    sweeper = Sweeper(app, world.cfg, world.git, forge, archiver, MergeDetector(world.git, base_branch="main"))
    (action,) = sweeper.run([snap])
    assert action.what == "archive_opened"  # the merged MR was recognised as the unit's own


def test_off_keeps_full_urls(run_l4, install_hooks, forge_env, use_fake_gitlab):
    passing(install_hooks)
    run = run_l4([red_step(), green_step()], observability={"redact_forge_urls": False})
    assert run.code == 0
    (updated,) = [e for e in run.ledger() if e["type"] == "pr.updated"]
    assert updated["url"] == MR
    assert all("<forge>" not in text for text in run.pending_files().values())
