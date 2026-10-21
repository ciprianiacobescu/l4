"""The kiro-cli 2.32.0 shapes recorded for the kiro-judge change (L4-KJD-010, task 0.1)."""

import json
from pathlib import Path

import pytest

from l4.schemacheck import validate

DIR = Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli" / "2.32.0"
SCHEMA = json.loads((Path(__file__).parents[3] / "src/l4/verifier/judge-verdict.schema.json").read_text())
STREAMS = sorted(DIR.glob("*.stream.jsonl"))


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_every_listed_file_exists():
    names = {p.name for p in DIR.iterdir()}
    assert names == {
        "README.txt",
        "auth-invalid-key.exit.txt",
        "auth-invalid-key.stream.jsonl",
        "input-missing.exit.txt",
        "input-missing.stream.jsonl",
        "judge-agent.json",
        "judge-pass.stream.jsonl",
        "list-models.json",
        "no-login.exit.txt",
        "no-login.stderr.txt",
        "no-login.stdout.txt",
        "usage-invalid-key.stdout.txt",
        "version.stdout.txt",
        "whoami-api-key.stdout.txt",
    }


@pytest.mark.parametrize("path", STREAMS, ids=lambda p: p.name)
def test_every_stream_line_is_an_event_object(path):
    lines = path.read_text().splitlines()
    assert lines
    for line in lines:
        event = json.loads(line)
        assert isinstance(event, dict) and isinstance(event["type"], str) and isinstance(event["data"], dict)


def test_the_judge_agent_is_the_agent_of_design_d1():
    agent = json.loads((DIR / "judge-agent.json").read_text())
    name = agent["name"]
    assert name.startswith("l4-judge-") and len(name) == len("l4-judge-") + 12
    assert agent == {
        "name": name,
        "description": "L4 harness judge: no tools",
        "prompt": None,
        "mcpServers": {},
        "tools": [],
        "toolAliases": {},
        "allowedTools": [],
        "resources": [],
        "hooks": {},
        "toolsSettings": {},
        "includeMcpJson": False,
        "model": "claude-sonnet-4.5",
    }


def test_the_judge_pass_final_text_sliced_to_its_object_validates():
    stream = events(DIR / "judge-pass.stream.jsonl")
    finished = next(e["data"] for e in stream if e["type"] == "runFinished")
    assert finished["status"] == "success" and finished["stopReason"] == "end_turn"
    assert finished["finalTextTruncated"] is False
    text = finished["finalText"]
    assert text.startswith("{")  # recorded (task 11.1): the reply is the bare object, no sentence before it
    parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
    assert validate(parsed, SCHEMA) == []
    assert [c["verdict"] for c in parsed["criteria"]] == ["pass", "pass", "pass"]
    chunks = "".join(
        e["data"]["update"]["content"]["text"]
        for e in stream
        if e["type"] == "sessionUpdate" and e["data"]["update"]["sessionUpdate"] == "agent_message_chunk"
    )
    assert chunks == text


def test_the_judge_pass_meters_its_credits_once_and_reports_engine_v2():
    stream = events(DIR / "judge-pass.stream.jsonl")
    credits = [m["value"] for e in stream for m in e["data"].get("meteringUsage", [])]
    assert credits == [0.20670165854063016]
    assert stream[0]["type"] == "runStarted" and stream[0]["data"]["engine"] == "v2"


def test_the_failure_shapes():
    auth = events(DIR / "auth-invalid-key.stream.jsonl")[-1]
    assert auth["type"] == "runError" and auth["data"]["stage"] == "prompt"
    assert "bearer token included in the request is invalid" in auth["data"]["message"]
    missing = events(DIR / "input-missing.stream.jsonl")
    assert [e["data"]["stage"] for e in missing] == ["input"]
    assert (DIR / "auth-invalid-key.exit.txt").read_text().strip() == "1"
    assert (DIR / "input-missing.exit.txt").read_text().strip() == "1"
    assert (DIR / "no-login.exit.txt").read_text().strip() == "1"
    assert "kiro-cli login --use-device-flow" in (DIR / "no-login.stderr.txt").read_text()
    assert (DIR / "no-login.stdout.txt").read_text().startswith("Opening browser...")


def test_the_text_shapes():
    assert (DIR / "usage-invalid-key.stdout.txt").read_text().strip() == (
        "Failed to retrieve usage information: AccessDeniedError [AccessDeniedException]: Invalid token"
    )
    assert json.loads((DIR / "whoami-api-key.stdout.txt").read_text()) == {"accountType": "ApiKey", "email": None}
    assert (DIR / "version.stdout.txt").read_text().strip() == "kiro-cli 2.32.0"


def test_the_readme_names_the_recorded_job_of_the_judge_stream_and_the_listing():
    readme = (DIR / "README.txt").read_text()
    assert "synthetic" not in readme and "reconstructed" not in readme.lower()
    assert "judge-pass.stream.jsonl: RECORDED" in readme and "118448154776" in readme
    assert "list-models.json: RECORDED" in readme and "118446825773" in readme
