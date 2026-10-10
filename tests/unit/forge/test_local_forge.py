import pytest

from l4.forge.base import Forge, ForgeNotFound
from l4.forge.local import LocalForge

BRANCH = "l4/openspec/add-discount-codes"


def test_local_forge_pr_roundtrip(tmp_path):
    forge: Forge = LocalForge(tmp_path / "forge")
    pr = forge.create_pr(BRANCH, "main", "[l4] add", "body")
    assert (pr.number, pr.draft, pr.state, pr.head_branch, pr.base_branch) == (1, True, "open", BRANCH, "main")
    assert forge.create_pr(BRANCH, "main", "again", "b") == pr  # idempotent per head branch
    assert forge.find_pr(BRANCH) == pr and forge.find_pr("other") is None
    ready = forge.update_pr(1, draft=False, title="new")
    assert (ready.draft, ready.title) == (False, "new")
    assert forge.get_pr(1) == ready
    forge.ensure_labels(["l4:queued", "l4:in_review"])
    labelled = forge.set_managed_labels(1, ["l4:in_review"], "l4:")
    assert labelled.labels == ("l4:in_review",)
    forge.upsert_sticky_note(1, "status")
    assert forge.project_url() == "local://forge"
    with pytest.raises(ForgeNotFound):
        forge.get_pr(9)
    with pytest.raises(ForgeNotFound):
        forge.upsert_sticky_note(9, "x")


def test_managed_labels_keep_foreign_ones_and_validate_the_prefix():
    forge = LocalForge()
    forge.create_pr(BRANCH, "main", "t", "b")
    forge.set_managed_labels(1, ["l4:a", "l4:b"], "l4:")
    forge._prs[1]["labels"].append("bug")  # a human adds a label
    assert forge.set_managed_labels(1, ["l4:b"], "l4:").labels == ("bug", "l4:b")
    with pytest.raises(ValueError):
        forge.set_managed_labels(1, ["nope"], "l4:")


def test_state_is_shared_through_the_directory(tmp_path):
    first = LocalForge(tmp_path)
    first.create_pr(BRANCH, "main", "t", "b")
    first.ensure_labels(["l4:x"])
    first.upsert_sticky_note(1, "note")
    second = LocalForge(tmp_path)
    assert second.get_pr(1).head_branch == BRANCH and second.note(1) == "note"
    assert second.create_pr(BRANCH, "main", "t", "b").number == 1  # no second PR for the same branch
    second.update_pr(1, draft=False)
    assert LocalForge(tmp_path).get_pr(1).draft is False
    assert [p.name for p in tmp_path.iterdir()] == ["forge.json"]  # no temp file left behind


def test_list_prs_filters_by_prefix_and_state_newest_first():
    forge = LocalForge()
    for name in ("l4/openspec/a", "l4/kiro/b", "feature/c"):
        forge.create_pr(name, "main", name, "")
    forge.merge(1, "a" * 40)
    forge.close(2)
    assert [p.number for p in forge.list_prs("l4/")] == [2, 1]
    assert [p.number for p in forge.list_prs("l4/", "merged")] == [1]
    assert forge.get_pr(1).merge_commit_sha == "a" * 40 and forge.get_pr(1).state == "merged"
    assert [p.number for p in forge.list_prs("l4/", "closed")] == [2]
    assert forge.find_pr("l4/openspec/a") is None  # merged: not open


def test_call_log_separates_reads_from_writes():
    forge = LocalForge()
    forge.find_pr(BRANCH)
    forge.project_url()
    assert forge.writes() == []
    forge.create_pr(BRANCH, "main", "t", "b")
    forge.upsert_sticky_note(1, "n")
    assert [c.name for c in forge.writes()] == ["create_pr", "upsert_sticky_note"]
    assert forge.called("find_pr")[0].args == (BRANCH,)
    forge.merge(1)
    assert forge.called("merge") and [c.name for c in forge.writes()][-1] == "merge"


def test_pipeline_jobs_are_scripted(tmp_path):
    """`l4 simulate` and the tests script the project's own CI: no network, the same port."""
    forge = LocalForge(tmp_path)
    assert forge.list_pipeline_jobs("a" * 40) == []
    forge.script_jobs("a" * 40, [("test", "failed"), ("lint", "success", {"allow_failure": True})],
                      tails={"test": "E assert 1 == 2"})  # fmt: skip
    jobs = {j.name: j for j in forge.list_pipeline_jobs("a" * 40)}
    assert (jobs["test"].status, jobs["lint"].allow_failure) == ("failed", True)
    assert forge.job_log_tail(jobs["test"].job_id, 40) == "E assert 1 == 2" and forge.job_log_tail(12345, 40) == ""
    assert forge.writes() == [] and forge.list_pipeline_jobs("b" * 40) == []
    assert LocalForge(tmp_path).list_pipeline_jobs("a" * 40) == list(jobs.values())  # shared through the directory


def test_settled_scripted_jobs_keep_the_newest_finished_attempt(tmp_path):
    forge = LocalForge(tmp_path)
    forge.script_jobs("a" * 40, [("test", "failed")])
    forge.script_jobs("a" * 40, [("test", "running"), ("build", "pending")])  # scripted later: newer
    assert {j.name: j.status for j in forge.list_pipeline_jobs("a" * 40, settled=True)} == {
        "test": "failed", "build": "pending",
    }  # fmt: skip
