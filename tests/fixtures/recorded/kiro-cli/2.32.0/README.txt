kiro-cli 2.32.0 shapes for the kiro-judge change (L4-KJD-010). No model answered and no login was used.
Made in an isolated HOME / XDG_* / KIRO_HOME under a sandbox profile that denied the owner's kiro-cli stores and the
browser launcher, with KIRO_API_KEY set to a fake value (design section 2.1, 2.2).
auth-invalid-key.stream.jsonl, .exit.txt: chat --no-interactive with the fake key (R7): a runError at stage prompt, exit 1.
input-missing.stream.jsonl, .exit.txt: chat --no-interactive with no argument and stdin from /dev/null (R8), exit 1.
no-login.stdout.txt, .stderr.txt, .exit.txt: chat with no login and no key (R4); the stdout spinner is shown without its ANSI codes.
usage-invalid-key.stdout.txt: /usage with the fake key (R12), exit 0.
whoami-api-key.stdout.txt: whoami --format json with the fake key (R3), exit 0 (presence of the key, not its validity).
version.stdout.txt: kiro-cli --version.
judge-agent.json: the judge agent file of design D1 for claude-sonnet-4.5; `agent validate` accepted it (R5). The name
  is an example; the adapter draws a new one for each call.
judge-pass.stream.jsonl: synthetic until task 11.1 replaces it with a recorded stream. It has the shape of
  2.28.0/hello.stream.jsonl: the sentence "Here is my verdict:" and one l4/judge-verdict@1 object for one criterion
  (verdict pass) as the message chunks and as finalText, one meteringUsage of 0.0512 credits, finalTextTruncated false.
