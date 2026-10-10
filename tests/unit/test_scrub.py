"""scripts/dev/scrub.py with fake rules only."""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "scrub.py"


def run(*args, env=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=e)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.test")
    git(repo, "config", "user.name", "t")
    for rel, data in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def write_rules(tmp_path, rules, untrack=()):
    f = tmp_path / "rules.json"
    f.write_text(json.dumps({"untrack": list(untrack), "rules": rules}))
    return f


def test_order_groups_and_ignore_case(tmp_path):
    repo = make_repo(tmp_path, {"a.txt": "Host SECRET-HOST.invalid and user-17\n"})
    rules = write_rules(
        tmp_path,
        [
            {"lit": "SECRET-HOST.invalid", "to": "mid.invalid"},
            {"re": "MID\\.invalid", "to": "example.test", "i": True},
            {"re": "user-(\\d+)", "to": "person-\\g<1>"},
        ],
    )
    r = run("apply", "--rules", str(rules), "--repo", str(repo))
    assert r.returncode == 0
    assert (repo / "a.txt").read_text() == "Host example.test and person-17\n"
    assert "rule 0: 1 replacements in 1 files" in r.stdout
    assert "secret" not in r.stdout.lower() and "example.test" not in r.stdout


def test_binary_untouched_and_mode_kept(tmp_path):
    blob = b"\x00secret-host.invalid\x00"
    repo = make_repo(tmp_path, {"b.bin": blob, "run.sh": "echo secret-host.invalid\n"})
    (repo / "run.sh").chmod(0o755)
    rules = write_rules(tmp_path, [{"lit": "secret-host.invalid", "to": "example.test"}])
    assert run("apply", "--rules", str(rules), "--repo", str(repo)).returncode == 0
    assert (repo / "b.bin").read_bytes() == blob
    assert (repo / "run.sh").read_text() == "echo example.test\n"
    assert (repo / "run.sh").stat().st_mode & 0o777 == 0o755


def test_untrack_and_gitignore_idempotent(tmp_path):
    repo = make_repo(tmp_path, {"priv/n.md": "x\n", "keep.txt": "y\n", ".gitignore": "a\n"})
    rules = write_rules(tmp_path, [], untrack=["priv/"])
    for _ in range(2):
        assert run("apply", "--rules", str(rules), "--repo", str(repo)).returncode == 0
    assert (repo / "priv/n.md").exists()
    ls = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.split()
    assert "priv/n.md" not in ls and "keep.txt" in ls
    assert (repo / ".gitignore").read_text().splitlines().count("priv/") == 1


def test_check_content_path_and_no_match_text(tmp_path):
    repo = make_repo(tmp_path, {"a.txt": "see secret-host.invalid\n", "dir-zzq/f.txt": "ok\n", "c.txt": "fine\n"})
    rules = write_rules(
        tmp_path,
        [{"lit": "secret-host.invalid", "to": "example.test"}, {"re": "zzq", "to": "q"}],
    )
    r = run("check", "--rules", str(rules), "--repo", str(repo))
    assert r.returncode == 1
    assert "rule 0: a.txt" in r.stdout
    assert "rule 1: dir-zzq/f.txt" in r.stdout
    assert "secret-host" not in r.stdout
    assert "c.txt" not in r.stdout


def test_check_untrack_still_tracked_and_clean(tmp_path):
    repo = make_repo(tmp_path, {"priv/n.md": "x\n"})
    rules = write_rules(tmp_path, [{"lit": "nothing-here", "to": "z"}], untrack=["priv/"])
    assert run("check", "--rules", str(rules), "--repo", str(repo)).returncode == 1
    run("apply", "--rules", str(rules), "--repo", str(repo))
    r = run("check", "--rules", str(rules), "--repo", str(repo))
    assert r.returncode == 0
    assert r.stdout.startswith("scrub check: clean (")
    assert "1 rules)" in r.stdout


def test_rules_env_and_malformed(tmp_path):
    repo = make_repo(tmp_path, {"a.txt": "secret-host.invalid\n"})
    good = json.dumps({"untrack": [], "rules": [{"lit": "secret-host.invalid", "to": "example.test"}]})
    r = run("check", "--rules-env", "FAKE_RULES", "--repo", str(repo), env={"FAKE_RULES": good})
    assert r.returncode == 1 and "rule 0: a.txt" in r.stdout
    bad = run("check", "--rules-env", "FAKE_RULES", "--repo", str(repo), env={"FAKE_RULES": "{nope"})
    assert bad.returncode == 2
    badre = json.dumps({"rules": [{"re": "(", "to": "x"}]})
    assert run("check", "--rules-env", "FAKE_RULES", "--repo", str(repo), env={"FAKE_RULES": badre}).returncode == 2


def test_check_ignores_replacement_that_matches_its_own_pattern(tmp_path):
    repo = make_repo(tmp_path, {"a.txt": "img/avatar/1/x.png\n"})
    rules = write_rules(tmp_path, [{"re": "avatar/\\d+/[\\w.]+", "to": "avatar/1/x.png"}])
    assert run("check", "--rules", str(rules), "--repo", str(repo)).returncode == 0
    (repo / "a.txt").write_text("img/avatar/2/y.png\n")
    git(repo, "commit", "-qam", "edit")
    assert run("check", "--rules", str(rules), "--repo", str(repo)).returncode == 1



def test_untrack_skips_an_entry_a_broader_pattern_already_ignores(tmp_path):
    repo = make_repo(tmp_path, {"docs/priv/n.md": "x\n", ".gitignore": "docs/\n"})
    rules = write_rules(tmp_path, [], untrack=["docs/priv/"])
    assert run("apply", "--rules", str(rules), "--repo", str(repo)).returncode == 0
    assert (repo / ".gitignore").read_text() == "docs/\n"
    ls = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.split()
    assert "docs/priv/n.md" not in ls
