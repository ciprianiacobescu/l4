from .conftest import FakeGitLab

BRANCH = "l4/openspec/add-discount-codes"


def test_create_pr_is_draft_and_idempotent(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    first = forge.create_pr(BRANCH, "main", "[l4] add-discount-codes: Discounts", "body text")
    assert gitlab.mrs[1]["title"] == "Draft: [l4] add-discount-codes: Discounts"
    assert first.draft and first.title == "[l4] add-discount-codes: Discounts" and first.number == 1
    assert gitlab.mrs[1]["target_branch"] == "main" and gitlab.mrs[1]["description"] == "body text"
    again = forge.create_pr(BRANCH, "main", "other title", "other body")
    assert again == first
    assert [m for m, p in gitlab.writes()] == ["POST"]  # the second call wrote nothing


def test_create_pr_does_not_double_the_draft_prefix(gitlab: FakeGitLab, make_forge_client):
    make_forge_client().create_pr(BRANCH, "main", "Draft: already", "b")
    assert gitlab.mrs[1]["title"] == "Draft: already"


def test_create_pr_ready_when_asked(gitlab: FakeGitLab, make_forge_client):
    pr = make_forge_client().create_pr(BRANCH, "main", "t", "b", draft=False)
    assert not pr.draft and gitlab.mrs[1]["title"] == "t"


def test_find_pr_ignores_other_branches_and_closed_mrs(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr("l4/openspec/other", "main", "t", "b")
    assert forge.find_pr(BRANCH) is None
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.mrs[2]["state"] = "closed"
    assert forge.find_pr(BRANCH) is None


def test_update_pr_marks_ready(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "the title", "b")
    ready = forge.update_pr(1, draft=False)
    assert gitlab.mrs[1]["title"] == "the title" and not ready.draft
    gitlab.requests.clear()
    assert forge.update_pr(1, draft=False) == ready
    assert gitlab.writes() == []  # already ready: nothing is written


def test_update_pr_can_set_the_body_and_keeps_the_draft_state(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "the title", "old")
    forge.update_pr(1, body="new")
    assert gitlab.mrs[1]["description"] == "new" and gitlab.mrs[1]["title"].startswith("Draft: ")


def test_update_pr_can_make_a_ready_mr_a_draft_again(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b", draft=False)
    assert forge.update_pr(1, draft=True).draft and gitlab.mrs[1]["title"] == "Draft: t"


SHA = "a" * 40


def test_list_prs_maps_states_and_merge_commit(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    forge.create_pr("l4/openspec/b", "main", "[l4] b", "b", draft=False)
    forge.create_pr("l4/openspec/c", "main", "[l4] c", "b", draft=False)
    forge.create_pr("feature/other", "main", "other", "b", draft=False)
    gitlab.merge(2, SHA)
    gitlab.mrs[3]["state"] = "closed"
    everything = {pr.head_branch: pr for pr in forge.list_prs("l4/", "all")}
    assert set(everything) == {"l4/openspec/a", "l4/openspec/b", "l4/openspec/c"}  # a prefix, not every MR
    assert [everything[b].state for b in sorted(everything)] == ["open", "merged", "closed"]
    assert everything["l4/openspec/b"].merge_commit_sha == SHA
    assert everything["l4/openspec/a"].merge_commit_sha is None
    assert [pr.head_branch for pr in forge.list_prs("l4/", "merged")] == ["l4/openspec/b"]
    assert [pr.head_branch for pr in forge.list_prs("l4/", "open")] == ["l4/openspec/a"]


def test_get_pr_of_a_merged_mr_carries_the_merge_commit(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b", draft=False)
    gitlab.merge(1, SHA)
    pr = forge.get_pr(1)
    assert pr.state == "merged" and pr.merge_commit_sha == SHA


def test_a_fast_forward_merge_has_no_merge_commit_sha(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b", draft=False)
    gitlab.merge(1, None)
    assert forge.get_pr(1).merge_commit_sha is None


def test_list_prs_pages_through_every_mr(gitlab: FakeGitLab, make_forge_client, monkeypatch):
    from l4.forge import gitlab as module

    monkeypatch.setattr(module, "PER_PAGE", 3)
    forge = make_forge_client()
    for n in range(7):
        forge.create_pr(f"l4/openspec/u{n}", "main", "t", "b")
    assert len(forge.list_prs("l4/", "open")) == 7


def test_a_fork_mr_with_a_harness_branch_name_is_not_ours(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr("l4/archive/openspec/x", "main", "t", "b")
    forge.create_pr(BRANCH, "main", "t", "b")
    for mr in gitlab.mrs.values():
        mr["source_project_id"] = 999  # opened from a fork: anyone can pick any source branch name
    assert forge.find_pr(BRANCH) is None
    assert forge.list_prs("l4/", "open") == []


def test_list_prs_is_newest_first(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "first", "b")
    gitlab.merge(1, "a" * 40)
    forge.create_pr(BRANCH, "main", "second", "b")
    gitlab.merge(2, "b" * 40)
    assert [pr.number for pr in forge.list_prs("l4/", "merged")] == [2, 1]
    gitlab.merge(1, "c" * 40)  # touched last: now the newest
    assert [pr.number for pr in forge.list_prs("l4/", "merged")] == [1, 2]


def test_a_locked_mr_is_open_because_it_is_being_merged(gitlab: FakeGitLab, make_forge_client):
    """Review L1: GitLab's `locked` is a merge in progress; reading it as closed would make the sweep treat the unit as
    abandoned."""
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b", draft=False)
    gitlab.mrs[1]["state"] = "locked"
    assert forge.get_pr(1).state == "open"
