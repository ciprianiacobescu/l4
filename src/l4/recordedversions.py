"""The CLI versions that have recorded contract fixtures (HB-17, SPEC L4-FAC-007).

`recorded_versions.json` (packaged) maps an adapter name to the versions with a directory under
`tests/fixtures/recorded/<adapter>/<version>/`. It is generated, never edited: `uv run python -m l4.recordedversions
--write`; `tests/unit/test_recorded_versions.py` fails when it drifts from the fixture tree. A selected CLI whose
version is not listed still runs (its output may still parse); it is reported, not refused.
"""

import json
import re
import sys
from importlib import resources
from pathlib import Path

NAME = "recorded_versions.json"
_VERSION_DIR = re.compile(r"^\d+(\.\d+)+$")


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def generate(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for tool in sorted(p for p in root.iterdir() if p.is_dir()):
        versions = sorted((v.name for v in tool.iterdir() if v.is_dir() and _VERSION_DIR.match(v.name)), key=_key)
        if versions:
            found[tool.name] = versions
    return found


def load() -> dict[str, list[str]]:
    return json.loads(resources.files("l4").joinpath(NAME).read_text(encoding="utf-8"))


def unrecorded(adapter: str, version: str, recorded: dict[str, list[str]] | None = None) -> list[str] | None:
    """The recorded versions of the adapter when `version` is not among them; None when it is recorded or when the
    adapter has no recordings at all (a `command` profile or the fake adapter has nothing to compare with)."""
    table = load() if recorded is None else recorded
    known = table.get(adapter)
    if not known or version in known:
        return None
    return list(known)


def main(argv: list[str]) -> int:
    if argv != ["--write"]:
        print("usage: python -m l4.recordedversions --write", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "recorded"
    Path(__file__).with_name(NAME).write_text(
        json.dumps(generate(root), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
