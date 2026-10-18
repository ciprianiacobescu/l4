"""The setup action builds the harness from a copy of the action's repository (`source: action`): the copy and the
cache key must hold every path the build reads, including each `force-include` source of pyproject.toml (the l4 skill
since 0.4.14, L4-SKL-003). A missing one fails the build on the runner: "Forced include not found"."""

import re
import shlex
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ACTION = ROOT / ".github" / "actions" / "l4" / "action.yml"


def _force_include_sources() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    targets = data["tool"]["hatch"]["build"]["targets"]
    return {src for target in targets.values() for src in target.get("force-include", {})}


def _tar_paths() -> list[str]:
    line = next(raw for raw in ACTION.read_text().splitlines() if "tar cf -" in raw and "l4-harness-src" not in raw)
    words = shlex.split(line.split("tar cf -", 1)[1].split("2>/dev/null", 1)[0])
    return [w for w in words if not w.startswith("--")]


def _key_paths() -> list[str]:
    line = next(raw for raw in ACTION.read_text().splitlines() if re.search(r"key=\$\(cd \"\$root\" && find ", raw))
    return shlex.split(line.split("&& find ", 1)[1].split(" -type", 1)[0])


def test_the_build_copy_holds_every_force_included_path():
    copied = _tar_paths()
    missing = [src for src in _force_include_sources() if not any(src == p or src.startswith(p + "/") for p in copied)]
    assert copied and not missing, f"action.yml copies {copied}; the build also reads {missing}"


def test_the_cache_key_covers_every_force_included_path():
    keyed = _key_paths()
    missing = [src for src in _force_include_sources() if not any(src == p or src.startswith(p + "/") for p in keyed)]
    assert keyed and not missing, f"the cache key hashes {keyed}; the build also reads {missing}"


def test_the_copy_the_action_makes_contains_the_skill(tmp_path):
    copy = tmp_path / "l4-harness-src"
    copy.mkdir()
    argv = ["tar", "cf", "-", "--exclude=__pycache__", *_tar_paths()]
    pack = subprocess.run(argv, cwd=ROOT, capture_output=True, check=True)
    subprocess.run(["tar", "xf", "-"], cwd=copy, input=pack.stdout, check=True)
    for src in _force_include_sources():
        assert (copy / src).exists(), f"{src} is not in the action's build copy"
