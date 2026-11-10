"""A unit worktree that holds the fixture web app at two commits: the merge base (3 items) and the head (4 items)."""

from pathlib import Path

from ._web_helpers import e2e_config, free_port, stage

SMOKE = (
    "import os, urllib.request\n\n\ndef test_page_is_served():\n"
    "    urllib.request.urlopen(os.environ['L4_E2E_BASE_URL'] + '/')\n"
)


def _write(root: Path, files: dict[str, str] | None) -> None:
    for rel, text in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def stage_base_and_head(
    bench, raw, *, base_files: dict[str, str] | None = None, head_files: dict[str, str] | None = None
) -> str:
    """Commits the app at the base ("3 items"), then the head ("4 items"); returns the base sha. `base_files` and
    `head_files` (path -> text) are committed with the base and with the head as well."""
    wb = bench.wb
    root: Path = wb.worktree
    stage(root)
    (root / "e2e/test_smoke.py").write_text(SMOKE)
    _write(root, base_files)
    (root / ".gitignore").write_text(".venv/\n.l4-out/\n__pycache__/\ntest-results/\n")
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "base: the cart app")
    base = raw(root, "rev-parse", "HEAD").strip()
    app = (root / "app.py").read_text().replace("3 items", "4 items")
    (root / "app.py").write_text(app)
    _write(root, head_files)
    if head_files:
        raw(root, "add", *head_files)
    raw(root, "commit", "-q", "-am", "head: four items")
    return base


def web_bench(make_bench):
    port = free_port()
    return make_bench([], e2e=e2e_config(port))
