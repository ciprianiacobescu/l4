# L4 Harness

A portable, CI-native harness that adds **level-4 agentic development** to any repository: it detects the spec
framework (OpenSpec or Kiro), implements unfinished spec tasks **test-first** with a configurable coding agent
(Claude Code, Codex CLI, OpenCode, Kiro CLI, …) after checking which agents are actually available, asks
clarifying questions in `questions.md` next to the spec, verifies the result adversarially and deterministically,
turns findings into new specs, archives verified specs and hands a merge-ready PR/MR with an evidence package to a
human.

Status: the harness runs end to end on GitLab with a self-hosted shell runner; GitHub Actions support is written by
`l4 init --ci github`, but its forge setup (secret, runner) is manual.

## Getting started

```bash
git clone https://github.com/ciprianiacobescu/agent-supervisor.git ~/l4
cd /path/to/your-project
~/l4/scripts/adopt.sh
```

`adopt.sh` installs what is missing (`uv`), adopts the project (`.l4/`, the CI file), checks it with a dry run of your
gates, and prints the exact remaining steps. A second run is safe. The runner and forge steps are in the
[quickstart](docs/quickstart.md).

* [Quickstart](docs/quickstart.md)
* [Architecture](docs/architecture.md)
* [Specification](docs/SPEC.md)
* [Research evidence](docs/research/README.md)
