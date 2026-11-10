# Recorded OpenCode 2 outputs (`@opencode/cli` 2.2.6)

Every file was recorded on 2026-11-10 with `@opencode/cli` 2.2.6, by L4 0.4.55's `OpenCodeV2Adapter.run` with the real
binary. "box" means a Linux arm64 container with L4's bubblewrap sandbox and an agent spec built like
`Workbench.agent_spec`. "mac" means macOS arm64 with no sandbox, an isolated HOME and isolated XDG directories. The
models are `opencode-go/deepseek-v4.1-flash` (a paid key through the credential loader) and `opencode/…-free` (no
login). Each `live-<name>.jsonl` is the run's `--format json` stream, and each `live-<name>.export.json` is the
`session export --standalone` of its session. "U<n>" is the [U] row of L4-OCV-013 and
design D9 of `opencode-v2-current`. Scrub rules, applied in this order:

1. a path under the mac runs' directory (with or without the `/private` prefix) became `/tmp/l4-oc2` plus the rest of
   the path;
2. a remaining temporary-directory prefix (private or not, other than `/tmp/l4-oc2`) that a model shortened with `…`
   (or three dots) became `/tmp/l4-oc2/`;
3. the box user's home directory became `/tmp/l4-oc2box`, and a path that starts with `/out/` became
   `/tmp/l4-oc2box/out/`;
4. each `ses_…` id became `ses_l4live<n>`, numbered per run, the same in a stream and its export;
5. the recording user's login became `user`;
6. a `home` directory under a mac run, `/tmp/l4-oc2/<run>/home/`, lost that `home` segment
   (`/tmp/l4-oc2/<run>/repo`), so no path holds a `home` directory.

Message and part ids, project hashes and timestamps stay. No file holds a key.

- `live-version.stdout.txt`: `opencode2 --version`, prints `opencode v2.2.6` on both machines.
- `live-judge.jsonl`, `live-judge.export.json`: box, judge, `opencode-go/deepseek-v4.1-flash`, 0.4.55's configuration;
  one step, the JSON reply, outcome `succeeded` (no [U] row: the core judge path).
- `live-judge-free.jsonl`, `live-judge-free.export.json`: box, judge, `opencode/deepseek-v4.1-flash-free` (no login),
  with the private data home of this change; one step, a cached input, outcome
  `succeeded` (no [U] row).
- `live-implement.jsonl`, `live-implement.export.json`: box, implementer, `opencode-go/deepseek-v4.1-flash`, with the
  allow-list and the private data home of this change; `read`, `edit` and `write` in 4 steps, one assistant message per
  step in the export (U11).
- `live-bounded.jsonl`, `live-bounded.export.json`: mac, judge, `opencode-go/deepseek-v4.1-flash`, 0.4.55's
  configuration with `options.steps.judge: 2`; a `skill` call that found no skill, then the forced summary step; the
  export says `succeeded` (U7, U9 in part).
- `live-tools-permission.jsonl`, `live-tools-permission.export.json`: mac, implementer,
  `opencode-go/deepseek-v4.1-flash`, 0.4.55's configuration with `options.tools: [read, edit]` and a prompt that asks
  for a shell command; the request had no `shell` tool and the model said so (U2).
- `live-cli-denied.jsonl`, `live-cli-denied.export.json`: box, implementer, `opencode-go/deepseek-v4.1-flash`, with the
  allow-list, the CLI denies and the private data home of this change; `opencode2 api GET /api/project` is refused
  with `Permission denied: shell` and the step goes on to a result file (L4-OCV-016).
- `live-cli-disturbed.jsonl`, `live-cli-disturbed.export.json`: box, implementer, `opencode-go/deepseek-v4.1-flash`,
  0.4.55's configuration (no CLI deny); the shell ran `opencode2 api …`, which listed the projects of earlier runs;
  the stream ends with a `step_start` after a `step_finish` of reason `tool-calls`, and the export holds a `synthetic`
  message (U5, U11).
- `live-error-no-route.jsonl`, `live-error-no-route.export.json`: box, judge, `opencode/nemotron-3-ultra-free`,
  0.4.55's configuration; a free model with no route: one `error` event `provider.no-route` with no `status`, exit 1,
  outcome `failed` (U7).

The probe's hello was checked live (paid and free, mac and box), but its raw stream was not kept, so the hello has no
fixture.
