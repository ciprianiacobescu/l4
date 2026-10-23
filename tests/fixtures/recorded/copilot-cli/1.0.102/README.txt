The GitHub-routed contract recording of Copilot CLI 1.0.102 (task 8.1 of the copilot-cli change), 2026-10-23. Made with
the real adapter (l4.agents.copilot_cli, harness snapshot b2485c74) by the workflow copilot-record on the owner's
dummy repository, on a GitHub-hosted ubuntu-24.04 runner (x64, image 20261012.334.1). Copilot 1.0.102 was installed by
`l4 doctor --ci --fix` from the pinned linux-x64 tarball against the harness's sha256. Account: a Copilot Free plan,
with a fine-grained token (the "Copilot Requests" permission) that the job's environment holds as COPILOT_GITHUB_TOKEN
and the adapter's credential loader hands over; a private COPILOT_HOME on every run. Every leg used the argv of design
§5.2, with the prompt on stdin. Two jobs:
- job 120205659984 (run 39889521526): bad-token, judge-auto, judge-pinned-refused;
- job 120207726232 (run 39890159553): delegate-read, implement-serena.

- judge-auto.jsonl, judge-auto.usage.json: a tool-less judge (`--available-tools=l4_no_tools`) on `--model auto`.
  Exit 0. auto resolved to gpt-6-luna (`session.auto_mode_resolved`, `availableModels: ["gpt-6-luna"]`); the reply
  is {"verdict":"PASS","reason":"2 plus 2 equals 4."}; no tool ran.
- judge-pinned-refused.stderr.txt, .exit.txt, .usage.json: the same judge with `--model gpt-6-luna`. Exit 1, an empty
  stdout (no events file is kept), this standard error. The usage file counts 0 user requests: nothing was billed.
  The same account served gpt-6-luna under auto in the same job (design F42).
- bad-token.stderr.txt, .exit.txt, .usage.json: the auto judge with a well-formed but random `github_pat_` token built
  at run time. Exit 1, empty stdout, this standard error (the 401 shape of F38).
- delegate-read.jsonl, delegate-read.usage.json: a delegate (`--available-tools=view,grep,glob`) on auto that reads
  NOTES.md in a small temporary tree. One `view` call; the reply is {"answer":"L4 recording note 8.1"}.
- implement-serena.jsonl, .usage.json, .result.json, .mcp.json: an implementer on auto (served gpt-6-luna) in a fresh
  git repository, with `--allow-tool=write`, `--allow-tool=shell(python3:*)` (the gate `python3 -m pytest`),
  `--add-dir <step dir>` and Serena 1.7.0 through `--additional-mcp-config @<file>` (.mcp.json is that file) and
  `--allow-tool=serena`. Serena connected; the calls were serena-initial_instructions, apply_patch (hello.py),
  bash `python3 -m pytest -q` (1 passed) and bash writing the result file (.result.json). No call was denied.
- runs.json: what the adapter returned on the runner for each leg (status, detail, served model, structured reply,
  usage, argv after the executable). judge-luna is the leg of the judge-pinned-refused files; its detail is the
  mapping of the snapshot (`copilot-cli exited with code 1`), before D6 rule 4 named the refusal.

Edited only to replace, with REDACTED, the server's request and response identifiers (`apiCallId`, `model_call_id`,
`request_id`, `github_request_id`, `previousResponseId`, `reasoningId`, the `id` of `reasoningBlocks.blocks[]` and of
`serverTools.items[]`) and the server-encrypted reasoning (`encryptedContent`, `encrypted_content`,
`reasoningOpaque`): they are opaque values that GitHub can tie to the account, and no parser reads them. Session ids
are kept. The job logs and every kept file hold no login, e-mail or token (checked by grep); the artifact was
encrypted on the runner to a key held outside the repository.
