"""A world for the `l4 questions` tests (unfreeze-and-answer 4.2): the `openspec-basic` simulation repository (a bare
origin and a clone, forge `local`), two units `a` and `b` that are on the base branch, their branches
`l4/openspec/<name>` on the origin with a `questions.md` and a ledger of the test's choosing, and a fix unit folder
beside a unit's own. No network, no model."""

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import yaml

from l4.redact import Redactor
from l4.sim.builtin.manifest import scenario_text
from l4.sim.fakes import fake_openspec_cli
from l4.sim.remote import HUMAN, SimRepo
from l4.sim.runner import CONFIG_FILE, sim_app, sim_config
from l4.sim.scenarios import load_scenario
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions
from l4.vcs.git import Git

A, B = "openspec:a", "openspec:b"
RUN = "r-20261016T1000Z-aaaa"
ASKED = "2026-10-16T10:00:00Z by implementer `codex`, run r-20261016T1000Z-aaaa, task 3.1"
FOLDER = "openspec/changes"


def unit_files(name: str, tasks: str = "1.1") -> dict[str, str]:
    purpose = (
        "## Purpose\nThe counter capability: it counts, and the count is the observable result the plan delivers.\n\n"
    )
    return {
        f"{FOLDER}/{name}/tasks.md": f"## 1. T\n\n- [ ] {tasks} Add `count()`\n",
        f"{FOLDER}/{name}/proposal.md": f"# {name}\n",
        f"{FOLDER}/{name}/specs/{name}/spec.md": purpose
        + "## ADDED Requirements\n\n### Requirement: It counts\nThe `count()` function SHALL return 1.\n\n"
        "#### Scenario: Counting\n- **WHEN** `count()` is called\n- **THEN** it returns 1\n",
    }


def questions_md(unit: str, *specs: Mapping[str, object], eol: str = "\n") -> str:
    """A `questions.md` written by the harness's own writer. Each spec: title, kind, tasks, and optionally status,
    suggestion, answer (text under the Answer comment)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        batch = [
            NewQuestion(
                title=str(s.get("title", "A question?")),
                kind=QuestionKind(str(s.get("kind", "technical"))),
                blocking_tasks=tuple(s.get("tasks", ("1.1",))),  # type: ignore[arg-type]
                context=str(s.get("context", "Some context.")),
                options=tuple(s.get("options", ())),  # type: ignore[arg-type]
                asked=ASKED,
            )
            for s in specs
        ]
        raise_questions(folder, unit, batch, redactor=Redactor({}))
        file = QuestionsFile.load(folder / "questions.md")
        assert file is not None
        for number, s in enumerate(specs, 1):
            qid = f"Q-{number:03d}"
            if s.get("suggestion"):
                file = file.set_suggestion(qid, str(s["suggestion"]), redactor=Redactor({}))
            if s.get("answer"):
                file = file.set_answer(qid, str(s["answer"]))
            if s.get("status", "open") != "open":
                file = file.set_status(qid, QuestionStatus(str(s["status"])))
        text = file.data.decode()
    return text.replace("\n", eol) if eol != "\n" else text


def ledger_line(unit: str, seq: int, type_: str, **data: object) -> str:
    stamp = f"2026-10-16T10:{seq:02d}:00.000000Z"
    return json.dumps({"ts": stamp, "run_id": RUN, "unit": unit, "seq": seq, "type": type_, **data})


def ledger_file(unit: str, *events: tuple[str, dict[str, object]]) -> str:
    return "".join(ledger_line(unit, n, t, **d) + "\n" for n, (t, d) in enumerate(events, 1))


class QWorld:
    def __init__(self, tmp_path: Path) -> None:
        self.sim = SimRepo.create("openspec-basic", root=tmp_path / "world")
        root = self.sim.root.resolve()
        config = sim_config(load_scenario(scenario_text("happy-openspec"), source="happy-openspec.yaml"))
        (root / CONFIG_FILE).write_text(yaml.safe_dump(config), encoding="utf-8")
        self.root, self.app = root, sim_app(root)
        self.clone = Git(self.app.repo, environ=self.app.environ)
        self.clone.run("config", "user.name", "alex")
        self.clone.run("config", "user.email", "alex@example.com")
        self.remote = Git(self.sim.remote, environ=self.app.environ)
        for name in ("a", "b"):
            self.sim.human_commit(unit_files(name), f"unit {name}")
        self.clone.run("pull", "--quiet", "--ff-only", "origin", "main")

    def branch(self, name: str, files: Mapping[str, str], message: str = "work") -> str:
        """Commit `files` to the unit branch `l4/openspec/<name>` on the origin (a person's push)."""
        return self.sim.human_commit(dict(files), message, branch=f"l4/openspec/{name}")

    def unit_branch(
        self, name: str, questions: str | None = None, *, ledger: str | None = None, extra: Mapping[str, str] = {}
    ) -> str:
        files: dict[str, str] = dict(extra)
        if questions is not None:
            files[f"{FOLDER}/{name}/questions.md"] = questions
        if ledger is not None:
            files[f"{FOLDER}/{name}/.l4/ledger/{RUN}.jsonl"] = ledger
        return self.branch(name, files, f"branch of {name}")

    def symlinked_questions(self, name: str, folder: str | None = None) -> str:
        """`questions.md` of the unit branch becomes a symlink."""
        self.branch(name, {f"{FOLDER}/{name}/.keep": "x\n"})
        human = self.sim._human
        assert human is not None
        link = human.repo / (folder or f"{FOLDER}/{name}") / "questions.md"
        link.unlink(missing_ok=True)
        os.symlink("proposal.md", link)
        self.sim._commit(human, HUMAN, "symlink")
        human.run("push", "--quiet", "origin", f"l4/openspec/{name}")
        return human.run("rev-parse", "HEAD").stdout.strip()

    def tracking(self, name: str) -> str | None:
        return self.clone.rev_parse(f"refs/remotes/origin/l4/openspec/{name}")

    def origin_head(self, name: str) -> str | None:
        return self.remote.rev_parse(f"refs/heads/l4/openspec/{name}")

    def break_origin(self) -> None:
        self.clone.run("remote", "set-url", "origin", str(self.root / "nowhere.git"))


@pytest.fixture
def qworld(tmp_path: Path):
    with fake_openspec_cli():
        yield QWorld(tmp_path)


def lines(text: str) -> Sequence[str]:
    return [line for line in text.splitlines() if line.strip()]
