"""Template lock (HB-11): `templates.lock.json` pins the sha256 of every prompt body to its version.

A body that changes without a version bump, or a bump without a regenerated lock, fails
`tests/unit/test_template_lock.py`. Regenerate after a deliberate change: `uv run python -m l4.templatelock --write`.
A template change that passes the lock is not thereby shown to be no worse: run `l4 eval --compare` (docs/eval.md).
The pinned prompts are the four implementer templates, the system text of the judge and the clarifier, and the
tool-less test writer's system text with the rules of each kind (`testwriter/audit`, `testwriter/e2e`).
"""

import hashlib
import json
import sys
from importlib import resources
from pathlib import Path

LOCK_NAME = "templates.lock.json"
IMPLEMENTER_TEMPLATES = ("contract", "red", "green", "single", "single_tests")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current() -> dict[str, dict[str, object]]:
    from l4.clarifier import context as clarifier
    from l4.implementer.prompt import load_template
    from l4.verifier import judge, testwriter

    out: dict[str, dict[str, object]] = {}
    for name in IMPLEMENTER_TEMPLATES:
        template = load_template(name)
        out[f"implementer/{name}"] = {"version": template.version, "sha256": _sha(template.body)}
    out["judge"] = {"version": judge.PROMPT_VERSION, "sha256": _sha(judge.SYSTEM)}
    out["clarifier"] = {"version": clarifier.PROMPT_VERSION, "sha256": _sha(clarifier.SYSTEM)}
    for kind, rules in testwriter._KIND_RULES.items():
        out[f"testwriter/{kind}"] = {"version": testwriter.TEMPLATE_VERSION, "sha256": _sha(testwriter.SYSTEM + rules)}
    return out


def read_lock(path: Path | None = None) -> dict[str, dict[str, object]]:
    text = path.read_text(encoding="utf-8") if path else resources.files("l4").joinpath(LOCK_NAME).read_text("utf-8")
    return json.loads(text)


def problems(lock: dict[str, dict[str, object]], now: dict[str, dict[str, object]]) -> list[str]:
    found: list[str] = []
    for name in sorted(set(lock) | set(now)):
        if name not in lock:
            found.append(f"{name}: not in the lock; run `python -m l4.templatelock --write`")
        elif name not in now:
            found.append(f"{name}: in the lock but no longer a prompt; run `python -m l4.templatelock --write`")
        elif lock[name]["version"] == now[name]["version"] and lock[name]["sha256"] != now[name]["sha256"]:
            found.append(f"{name}: the body changed but the version is still {now[name]['version']}; bump the version")
        elif lock[name] != now[name]:
            found.append(f"{name}: version or body differs from the lock; regenerate the lock with --write")
    return found


def main(argv: list[str]) -> int:
    if argv != ["--write"]:
        print("usage: python -m l4.templatelock --write", file=sys.stderr)
        return 2
    path = Path(__file__).with_name(LOCK_NAME)
    path.write_text(json.dumps(current(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
