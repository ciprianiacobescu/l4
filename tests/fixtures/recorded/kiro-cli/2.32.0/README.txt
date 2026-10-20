kiro-cli 2.32.0 shapes for the kiro-judge change (L4-KJD-010). No model answered and no login was used, except for
list-models.json and judge-pass.stream.jsonl (below), which task 11.1 recorded in CI on the owner's dummy repository.
The others were made in an isolated HOME / XDG_* / KIRO_HOME under a sandbox profile that denied the owner's kiro-cli stores and the
browser launcher, with KIRO_API_KEY set to a fake value (design section 2.1, 2.2).
list-models.json: RECORDED, the raw stdout of `kiro-cli chat --list-models --format json` with a real KIRO_API_KEY on
  kiro-cli 2.32.0, GitHub-hosted ubuntu-24.04, 2026-10-20, GitHub Actions job 118446825773 (run 39367262021), from a
  private KIRO_HOME that held only the judge's settings/cli.json (design D1). Exit 0. The object has `default_model`
  ("auto") besides `models`; every entry has exactly model_name, description, model_id, context_window_tokens,
  rate_multiplier and rate_unit: no status field. 21 entries, the same ids and descriptions as R18.
auth-invalid-key.stream.jsonl, .exit.txt: chat --no-interactive with the fake key (R7): a runError at stage prompt, exit 1.
input-missing.stream.jsonl, .exit.txt: chat --no-interactive with no argument and stdin from /dev/null (R8), exit 1.
no-login.stdout.txt, .stderr.txt, .exit.txt: chat with no login and no key (R4); the stdout spinner is shown without its ANSI codes.
usage-invalid-key.stdout.txt: /usage with the fake key (R12), exit 0.
whoami-api-key.stdout.txt: whoami --format json with the fake key (R3), exit 0 (presence of the key, not its validity).
version.stdout.txt: kiro-cli --version.
judge-agent.json: the judge agent file of design D1 for claude-sonnet-4.5; `agent validate` accepted it (R5). The name
  is an example; the adapter draws a new one for each call.
judge-pass.stream.jsonl: RECORDED, the judge stream of GitHub Actions job 118448154776 (run 39367684984, kiro-cli
  2.32.0, profile kiro-auto with no model, so the agent file and --model named `auto`): one call that judged the
  dummy's change add-days-of-stock (3 criteria, all pass), from the harness's published copy (secrets masked; none
  were found). Only the sessionId is replaced, by 00000000-0000-4000-8000-000000000000. The reply is the bare
  l4/judge-verdict@1 object (no sentence before it): runStarted (engine v2), 3 metadata events (one meteringUsage of
  0.20670165854063016 credits), 245 agent_message_chunk events whose texts join to finalText, runFinished with status
  success, stopReason end_turn and finalTextTruncated false. No tool_call and no event names a model.
