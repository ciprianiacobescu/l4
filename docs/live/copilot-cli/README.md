# GitHub Copilot CLI 1.0.102: live evidence

## Evidence without a token

Recorded on 2026-10-22 by task 0.1 of the `copilot-cli` change. No GitHub token, no Copilot login and no credential file
was used or read. Every run was `env -i` with only `PATH`, an empty `HOME` and an `XDG_CACHE_HOME`. The texts are in
`tests/fixtures/recorded/copilot-cli/1.0.102-notoken/` (not a contract recording of the GitHub-routed CLI). The
downloads were kept outside the repository and deleted after the run.

### The release archives

Source: `https://github.com/github/copilot-cli/releases/download/v1.0.102/<asset>`. `SHA256SUMS.txt` itself has sha256
`8753dd200b4d5c6d1989b7ffc2804b5762f9bf5a3ddee5e098aac4d78f89f4d2`, as in the design. Each sha256 below was recomputed
over the downloaded bytes and equals both `SHA256SUMS.txt` and design §5.4. Each archive was listed whole with
`tar -tvzf`: exactly one member, `copilot`, a regular file of mode `-rwxr-xr-x`, and the size of §5.4.

| asset | sha256 (recomputed) | archive bytes | member | member bytes |
|---|---|---|---|---|
| `copilot-linux-x64.tar.gz` | `cabbb04a88a8034ddfa21234cbd52b7676536aec2b292624e6fd6796f891a8ff` | 128,117,626 | `copilot` | 197,462,848 |
| `copilot-linux-arm64.tar.gz` | `634ee7cc4fa4b7447ac41e2c3ce54928d8f5214f418954e3af36f372e849c9c9` | 129,124,281 | `copilot` | 193,334,016 |
| `copilot-linuxmusl-x64.tar.gz` | `7e6d64a86b287105415357d158b459bdaede840de797e03677213d5419a597c9` | 123,390,875 | `copilot` | 196,258,160 |
| `copilot-linuxmusl-arm64.tar.gz` | `995c180500e741688c10e4e2368059ee2751fcc8812bdc58337e4ac920ef2971` | 119,704,585 | `copilot` | 188,238,736 |
| `copilot-darwin-x64.tar.gz` | `7a2af746ce5d11e2be486f06d85ce2fc620d5965413c8088fea8ceb2b1d9cb54` | 125,014,508 | `copilot` | 188,215,792 |
| `copilot-darwin-arm64.tar.gz` | `606f9539b88af1198523f671ffeeb6e58571ab71564252efbc3b2196f1ed3f2b` | 118,403,475 | `copilot` | 180,666,640 |

### Which command extracts the package

In an `ubuntu:24.04` container (glibc 2.39) on linux-arm64, with `HOME` an empty directory and `XDG_CACHE_HOME=/c` (empty):
`copilot --version` answered `GitHub Copilot CLI 1.0.102.` (exit 0) and, by itself, extracted the package. `/c` then
held `copilot/pkg/linux-arm64/1.0.102/` (about 220 MB). `copilot help` and `copilot -p hi` were therefore not needed
to extract it. The same on linux-x64 (`copilot/pkg/linux-x64/1.0.102/`), run under emulation.

### Read-only cache, and the per-run layout of design D14

- `/c` warmed by `copilot --version`, then mounted read-only: `copilot --version` answered (exit 0).
- Per-run layout: `/c` read-only, `XDG_CACHE_HOME=/w` (a writable directory) with `/w/copilot/pkg` a symbolic link to
  `/c/copilot/pkg`: `copilot --version` answered (exit 0). Under `/w` nothing appeared besides the link; nothing can
  have been written under `/c` (read-only mount; a `touch` there failed with `Read-only file system`).
- Both on linux-arm64 and linux-x64.

### Without a token

`copilot -p hi` and `copilot -p hi --output-format json`: exit 1, empty standard output, standard error
`Error: No authentication information found.` followed by the three ways to authenticate. Identical on both
architectures. `copilot help config` names model ids (`claude-sonnet-5.5` ... `gpt-5.4` ...). The help names
`--available-tools`, `--allow-tool`, `--add-dir`, `--disallow-temp-dir`, `--session-id`, `--usage-output-file` and
`--additional-mcp-config`.

### linux-x64

Ran under `--platform linux/amd64` emulation on an Apple Silicon host (version, warm extraction, read-only run,
per-run link, the six recordings): all answered, and every recorded file is byte-identical to the arm64 one. This is
emulation, not a native x64 host.

### macOS

The `darwin-arm64` binary, run once with an empty `HOME` and `XDG_CACHE_HOME` set to an empty scratch directory:
`--version` answered, and the package landed in `$HOME/Library/Caches/copilot/pkg/darwin-arm64/1.0.102/`. The directory
named by `XDG_CACHE_HOME` stayed empty. On macOS, `XDG_CACHE_HOME` does not move the package cache; `HOME` does.

## The GitHub-routed recording (task 8.1)

Recorded on 2026-10-23 with the real adapter (harness snapshot `b2485c74`, branch `live/copilot-cli`) by a
`workflow_dispatch` job on the owner's dummy repository, on a GitHub-hosted `ubuntu-24.04` runner (x64, image
`20261012.334.1`). The token was the owner's fine-grained PAT (Copilot Free, permission **Copilot Requests**), held as
the secret `COPILOT_GITHUB_TOKEN` of the environment `l4` and handed to each run by the credential loader. The job
logs and the kept streams were checked for the token, a login and an e-mail before anything was kept: none. The
artifact was encrypted on the runner to a key held outside the repository. The streams are in
`tests/fixtures/recorded/copilot-cli/1.0.102/` (its `README.txt` lists what was redacted).

| job | run | what |
|---|---|---|
| 120204864652 | 39889280824 | stopped by the recording's own config (`ci.time_budget: 21m`, CFG-012); nothing billed |
| 120205659984 | 39889521526 | install, `doctor --ci --live`, a rejected token, the judge on `auto`, the judge pinned to `gpt-6-luna` |
| 120207726232 | 39890159553 | the delegate and the implementer with Serena, both on `auto` |

Billed: 4 premium requests (one per user request: the LIVE-001 hello of `copilot-auto`, the auto judge, the
delegate, the implementer). The rejected token and the refused pin were billed nothing.

### Install and probes

- `l4 doctor --ci --fix` installed `copilot 1.0.102 from .../v1.0.102/copilot-linux-x64.tar.gz (sha256 cabbb04a…,
  the harness's table)` to `~/.local/bin/copilot` (197,462,848 bytes, 0755) and warmed the package cache at
  `$L4_HOME/copilot-cache/copilot/pkg/linux-x64/1.0.102`; `ENV-015 copilot 1.0.102 at their pins`,
  `PRV-001 copilot-auto copilot-cli ready; copilot-luna copilot-cli ready` (`job-120205659984-doctor-fix.txt`,
  `job-120205659984-install.txt`).
- `l4 doctor --ci --live`: `judges: copilot-luna skipped — hello: copilot-cli exited with code 1`, `judges:
  copilot-auto ok (binary 1.0.102 · auth api_key · quota skipped · hello 1.8s) → selected, fallback #1`, and
  `LIVE-001 pass` (`job-120205659984-doctor-live.txt`). The skipped profile is the refused pin below: with D6 rule 4
  its hello now reads `model_mismatch: copilot-cli could not set gpt-6-luna (the account does not offer it: pin a model
  it offers, or use auto)`.
- `l4 probe copilot-auto --no-cache` with a random `github_pat_` token: `skipped — hello: copilot-cli could not
  authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)` (`job-120205659984-probe-bad-token.txt`).

### Design §2.3, answered

| what needs a real token | recorded |
|---|---|
| A GitHub-routed judge reply | `judge-auto.jsonl`: exit 0, reply `{"verdict":"PASS","reason":"2 plus 2 equals 4."}`, no tool; the adapter's status `ok` |
| A delegate run | `delegate-read.jsonl`: one `view` of `NOTES.md` (`view_range [1, 1]`), reply `{"answer":"L4 recording note 8.1"}`; `ok` |
| An implementer run | `implement-serena.jsonl`: `serena-initial_instructions`, `apply_patch` (adds `hello.py`), `bash python3 -m pytest -q` (1 passed), `bash` writing the result; result `{"status": "done", ...}`; `ok`, no denial |
| `assistant.message.model` under `auto` (F30) | `gpt-6-luna` on every `assistant.message`, equal to `session.auto_mode_resolved.chosenModel` |
| `assistant.message.model` under a pinned model (F30) | **not recordable on this account**: `--model gpt-6-luna` is refused before any call (below), so no pinned stream exists |
| `totalNanoAiu`, `aiCreditsStatus` (F31) | `aiCreditsStatus: "complete"` on every billed run; `totalNanoAiu` 24,147,000 (judge, 2,973 input tokens), 51,832,500 (delegate, two calls, 7,187), 307,273,000 (implementer, five calls, 83,316) while `totalPremiumRequestCost` is 1 for each: the AI units follow the tokens, the premium requests the user requests |
| A rejected token (F32) | as F38: exit 1, empty stdout, stderr `Authentication token found but could not be validated` with `(401): GitHub returned: Bad credentials`; `auth` |
| A 402 or a 429 | none happened (no call was made to provoke one) |
| MCP injection with Serena (F26, F27) | the file `{"mcpServers": {"serena": {"command", "args", "env"}}}` given as `--additional-mcp-config @<file>` loaded: `session.mcp_server_status_changed` `pending`, then `connected` (`configSource: "user"`); the server's tools are named `serena-<tool>`, and `--allow-tool=serena` approved `serena-initial_instructions` |
| `apply_patch` approval on an OpenAI model (F36) | `--allow-tool=write` approved `apply_patch` on the OpenAI-served `gpt-6-luna` (`success: true`, `fileEdits` names `hello.py`) |

### A new shape: a pinned model that the account does not offer (F42)

`--model gpt-6-luna` on this Free account: exit 1, empty stdout, stderr `Error: Model "gpt-6-luna" from --model flag
is not available.`, and a usage file with 0 user requests. In the same job `auto` served `gpt-6-luna`
(`availableModels: ["gpt-6-luna"]`). So on this plan a pinned model is refused even when `auto` reaches it, and only
`auto` runs. The snapshot mapped it to `copilot-cli exited with code 1`. Design D6 rule 4, L4-FAC-017 and SCN-FAC-51
now map it to `error` with `model_mismatch: copilot-cli could not set gpt-6-luna (the account does not offer it: pin a
model it offers, or use auto)`, which the judge ladder treats as a model mismatch (the profile is skipped and cooled,
the next independent judge takes the step) and the delegate escalates as a configuration to fix.

What it means for a Free plan: every Copilot profile must run on `auto`. A judge on `auto` is routed (runbook 10.8),
and a Copilot delegate cannot serve under `delegate.independence: model`, because an `auto` delegate is vetoed there
and a pinned one is refused by the account.

### Design §6, answered

| claim | was | now |
|---|---|---|
| `l4_no_tools` gives no tool (F10) | [I] | [V] GitHub-routed: `session.info` `Unknown tool name in the tool allowlist: "l4_no_tools"` and `Disabled tools: ...`; no tool call in the judge |
| MCP file format (F26), the MCP allow rule (F27) | [G], [I] | [V] both, as in §2.3 above |
| Nested instruction files under `--no-custom-instructions` (F28) | [U] | [U]: the recorded trees had no nested instruction file; the masked tree (D4) and R11 stay the answer |
| Exact model ids of 1.0.102 (F29) | [U] | [V] the list of `copilot help config` (task 0.1); this account offers `gpt-6-luna` under `auto` only and refuses `--model gpt-6-luna` (F42) |
| `assistant.message.model` under GitHub routing (F30) | [I] | [V] under `auto`; [U] under a pinned model, which needs an account that offers one |
| `totalNanoAiu` unit (F31) | [G] | [G]: read as credits × 10^9 (0.024, 0.052 and 0.307 for the three billed runs); it follows tokens, not requests (above) |
| GitHub-routed error shapes (F32) | [G] | [V] the rejected token (F38) and the refused pin (F42); [G] a 402, a 429, a session or weekly limit (none happened) |
| Linux x64 runs; minimum glibc (F34) | [I], [G] | [V] native x64 on `ubuntu-24.04` (glibc 2.39); [G] the minimum glibc |
| `apply_patch` approval by `--allow-tool=write` (F36) | [U] | [V] |
| The GitHub-routed timing of the 429 retry (F7) | [G] | [G]: no 429 happened |
| The macOS keychain login is not isolated by `HOME` | [I] | [I]: not in the scope of a Linux runner (R12) |
| The network hosts the CLI reaches | [G] | [G]: not observed; the streams name `api_endpoint` `/responses` over `http` and `ws:/responses` over `websocket`, no host |
| An org policy that forces Copilot's sandbox | [G] | [G]: a non-goal (R14) |

Where the recording exercised them, the shapes of D3 to D8 and D10 held: the argv of each mode, the reply field, the
stream events the parser reads, the usage file, the auth stderr and `session.auto_mode_resolved`. D7's stops did not
trigger (no 429, no denied call). Events the parser skips were also seen (`assistant.reasoning_delta`,
`assistant.tool_call_delta`, `tool.shell_output`, `tool.execution_partial_result`, `session.background_tasks_changed`,
`session.mcp_server_tools_loaded`). The only differing shape is F42.
