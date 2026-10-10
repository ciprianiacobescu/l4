"""A stand-in for the pinned OpenSpec CLI that can create a change: `new change` writes `.openspec.yaml` (and, like the
real 1.14.0, `openspec/config.yaml` when the repository has none), `validate` answers from a canned result."""

from pathlib import Path

from l4.specs.openspec import CliResult, OpenSpecCli


class FixCli:
    def __init__(self, repo: Path, *, valid: bool = True, message: str = "") -> None:
        self.repo, self.valid, self.message = repo, valid, message
        self.calls: list[tuple[str, ...]] = []

    def run_json(self, *args: str) -> CliResult:
        self.calls.append(args)
        if args[:2] == ("new", "change"):
            folder = self.repo / "openspec" / "changes" / args[2]
            folder.mkdir(parents=True)
            (folder / ".openspec.yaml").write_text("schema: spec-driven\ncreated: 2026-10-04\n")
            config = self.repo / "openspec" / "config.yaml"
            if not config.exists():
                config.write_text("schema: spec-driven\n")
            change = {"id": args[2], "path": str(folder), "schema": "spec-driven"}
            return CliResult(args, 0, {"change": change, "root": {"path": str(self.repo), "source": "nearest"}})
        issues = [] if self.valid else [{"level": "ERROR", "path": "specs", "message": self.message or "invalid"}]
        return CliResult(args, 0, {"items": [{"id": args[1], "valid": self.valid, "issues": issues}]})


def patch_openspec(monkeypatch, *, valid: bool = True, message: str = "") -> None:
    """Every `OpenSpecCli` of the process answers like `FixCli` (for the tests that run `l4 run` end to end)."""
    monkeypatch.setattr(
        OpenSpecCli, "run_json", lambda self, *args: FixCli(self._repo, valid=valid, message=message).run_json(*args)
    )
