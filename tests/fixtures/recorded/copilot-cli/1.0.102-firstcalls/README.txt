First GitHub-routed calls of Copilot CLI 1.0.102 (2026-10-23), made by the orchestrator before the adapter existed, to
settle facts the design needs before the parser is written. Not the contract recording of task 8.1: the folder name is
not a bare version, so l4.recordedversions ignores it.

- judge-auto.jsonl, judge-auto.usage.json: one tool-less judge prompt ("Reply with exactly: L4-OK") with the judge argv
  of design §5.2 and `--model auto`, prompt on stdin, macOS arm64, a private COPILOT_HOME, a Copilot Free account and a
  fine-grained token with the "Copilot Requests" permission in COPILOT_GITHUB_TOKEN. Exit 0. `auto` resolved to
  gpt-6-luna (`session.auto_mode_resolved`, the only model the Free plan offered). Edited only to replace the
  server's request identifiers (`apiCallId`, `model_call_id`, `request_id`, `github_request_id`) with REDACTED: they
  are opaque ids GitHub can tie to the account, and no parser reads them. The stream holds no login, e-mail or token
  (checked by grep).
- bad-token.stderr.txt, bad-token.exit.txt: the same argv with a well-formed but random `github_pat_` token built at
  run time. Exit 1, empty stdout, this standard error.
