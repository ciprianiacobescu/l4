"""`l4 status --unit` names the delegate while it is off (delegate-answers 26.1; L4-DLG-021; SCN-DLG-71/72/73)."""

import json

from l4.delegate.hint import hint_text
from l4.vcs.git import BOT_IDENTITY

from .test_status_branch import run_cli
from .test_status_delegate import push

HINT = hint_text("main")
UNIT = "openspec:add-x"


def base_config(unit_repo, trailers, text: str) -> None:
    (unit_repo.repo / ".l4").mkdir(exist_ok=True)
    (unit_repo.repo / ".l4" / "config.yaml").write_text(text)
    unit_repo.git.run("add", ".l4/config.yaml")
    unit_repo.git.commit("the base configuration", trailers, BOT_IDENTITY)
    unit_repo.git.push("origin", ["HEAD:refs/heads/main"])
    unit_repo.git.fetch("origin")


def test_the_hint_follows_next(unit_repo, trailers, capsys):  # SCN-DLG-71
    base_config(unit_repo, trailers, "version: 1\ndelegate:\n  scope: all\n")
    push(unit_repo, trailers)
    code, out, err = run_cli(unit_repo, capsys, "status", "--unit", UNIT)
    assert code == 0, err
    lines = out.splitlines()
    assert lines[-1] == HINT and lines[-2].startswith("Next:")
    _, raw, _ = run_cli(unit_repo, capsys, "status", "--unit", UNIT, "--json")
    assert json.loads(raw)["units"][0]["delegate_hint"] == HINT


def test_no_hint_while_on_or_out_of_scope(unit_repo, trailers, capsys):  # SCN-DLG-72, 73
    push(unit_repo, trailers)
    for text in (
        "version: 1\ndelegate:\n  scope: all\n  enabled: true\n",
        "version: 1\n",  # scope: yolo and the unit is in no plan
    ):
        base_config(unit_repo, trailers, text)
        _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", UNIT)
        assert "Hint:" not in out
        _, raw, _ = run_cli(unit_repo, capsys, "status", "--unit", UNIT, "--json")
        assert json.loads(raw)["units"][0]["delegate_hint"] is None


def test_the_listing_is_unchanged(unit_repo, trailers, capsys):
    base_config(unit_repo, trailers, "version: 1\ndelegate:\n  scope: all\n")
    push(unit_repo, trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status")
    assert "Hint:" not in out
    _, raw, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert "delegate_hint" not in json.loads(raw)["units"][0]
