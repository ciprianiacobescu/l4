# Recorded OpenCode 2 outputs (`@opencode/cli` 2.0.32)

Every file was recorded in an isolated HOME (empty HOME and XDG directories, minimal PATH, no user config),
2026-10-19, `@opencode/cli` 2.0.32, no key unless the line says so. Local paths were replaced by `/tmp/l4-oc2`
(`/home/user` for a home directory) and the private LAN address in a `baseURL` by `192.0.2.1`. "Row" is the matrix row
of `docs/plan/opencode-v2.md`.

- `version.stdout.txt`: `opencode2 --version`, prints `opencode v2.0.32` (row 3).
- `hello-ok-step-finish.jsonl`: `run --format json`, the hello prompt, a free model; ends with `step_finish` (row 14).
- `hello-ok-no-step-finish.jsonl`: the same run; the stream ends at `text`, exit 0 (row 14).
- `hello-ok-stdin-no-step-finish.jsonl`: the hello prompt on stdin; the stream ends at `text` (rows 7, 14).
- `hello-think-leak.jsonl`: the hello run with `--standalone`; the reply is `...</think>L4-OK`, a closing tag with no
  opening one (row 23).
- `text-no-step-finish.jsonl`: a text-only run, free model; no final `step_finish` (row 14).
- `text-no-step-finish.export.json`: `session export <id> --standalone` of that run; `info.outcome`, `finish`, tokens
  and cost (row 14).
- `error-403-free-tier-denied-tools.jsonl`: a judge-shaped run (every tool denied) on a free model; the `error` event
  is `provider.auth`, status 403 (rows 10, 13).
- `error-403-free-tier-network.jsonl`: a hello with `agents.build.steps` 1 from a network the free tier refuses; 403
  `provider.auth` with a `FreeTierError` body (rows 13, 24).
- `ask-loop-unbounded.jsonl`, `ask-loop-unbounded.stderr.txt`: a read-only prompt with `ask` rules and no step bound;
  every ask is auto-rejected and the run continues until the timeout (rows 10, 11).
- `ask-loop-steps3.jsonl`, `ask-loop-steps3.stderr.txt`: the same run with the v1-form `maxSteps: 3`; stops after
  3 steps, exit 0 (row 10).
- `implement-deny-continues.jsonl`: an implementer-shaped run (write allowed, `git commit` denied); `Permission
  denied: shell` and the run continues (rows 11, 12).
- `auth-list-empty.json`: `auth list --standalone --format json` without a key; `[]` (row 17).
- `auth-list-env-key.json`: the same with `OPENCODE_API_KEY` set to a dummy value; two `env` connections (row 17).
- `config-normalised-implement.json`, `config-normalised-judge-paid.json`, `config-normalised-judge-free.json`,
  `config-normalised-read-only.json`, `config-normalised-implement-tools.json`: `debug config` output of the v1-form
  `OPENCODE_CONFIG_CONTENT` of each L4 shape (implementer, paid judge, free judge, read-only, implementer with a
  `tools` map and a provider block), showing the in-memory normalisation (row 9).
- `config-steps-native.json`, `config-steps-v1-form.json`: `debug config` of `agents.build.steps: 3` and of the
  v1-form `maxSteps: 3`; both resolve to the same step bound (row 10).
