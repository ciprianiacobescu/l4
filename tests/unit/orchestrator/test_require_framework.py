"""L4-DET-003: `l4 run` alone refuses a repository with no spec framework under `sdd.enforce` (exit 14)."""

from l4.cli import main


def without_framework(run_l4, tdd_repo, raw, **config):
    raw(tdd_repo.repo, "rm", "-rq", "openspec")
    raw(tdd_repo.repo, "commit", "-q", "-m", "no framework")
    return run_l4([], unit=False, **config)


def test_no_framework_is_exit_14_before_any_lease_or_agent(run_l4, tdd_repo, raw):
    run = without_framework(run_l4, tdd_repo, raw)
    assert run.code == 14 and run.adapter.requests == []
    assert not (tdd_repo.cache / "worktrees").exists() and not (tdd_repo.cache / "locks").exists()


def test_plan_and_status_list_nothing_instead_of_failing(run_l4, tdd_repo, raw, capsys):
    without_framework(run_l4, tdd_repo, raw)
    capsys.readouterr()
    for command in ("plan", "status"):
        assert main([command, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
        assert "no units" in capsys.readouterr().out


def test_with_sdd_enforce_off_a_repository_without_units_is_nothing_to_do(run_l4, tdd_repo, raw):
    raw(tdd_repo.repo, "rm", "-rq", "openspec")
    raw(tdd_repo.repo, "commit", "-q", "-m", "no framework")
    tdd_repo.write_config()
    (tdd_repo.repo / ".l4" / "config.yaml").write_text(
        (tdd_repo.repo / ".l4" / "config.yaml").read_text() + "sdd: {enforce: false}\n"
    )
    assert main(["run", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
