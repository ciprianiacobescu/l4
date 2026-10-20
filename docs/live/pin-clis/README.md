# pin-clis live evidence

## Task 3.1: Codex 0.160.0 and the update switch (2026-10-20)

Setup: `@openai/codex@0.160.0` installed with npm into a scratch prefix; empty scratch `HOME`, empty `CODEX_HOME`,
environment reduced to `PATH`, `HOME` and `CODEX_HOME` (no credential variable of any kind). The scratch install was
deleted afterwards. `codex --version` printed `codex-cli 0.160.0`.

1. `codex exec --skip-git-repo-check --ephemeral -s read-only -c check_for_update_on_startup=false -` with `x` on
   stdin, 60 s timeout: exit 1, stdout empty. stderr shows the session banner (model, sandbox read-only), then only
   `401 Unauthorized ... Missing bearer or basic authentication in header` from `api.openai.com/v1/responses`
   (websocket, then HTTPS, five reconnects each). No configuration error and no mention of the key: accepted.
2. Control, same command with `-c check_for_update_on_startup=notabool`: exit 1, stderr
   `Error loading config.toml: invalid type: string "notabool", expected a boolean in check_for_update_on_startup`.
   So the key is known to 0.160.0 and typed as a boolean; `false` is a valid value.
3. `codex app-server` with stdin closed, 20 s timeout: exit 0 at once, stdout and stderr both empty. No update
   check, and no mention of an update. (`codex app-server --help` lists `daemon`, `proxy`, `generate-*`; no update
   option.) Result: D13 decision 3 holds, `app-server` gets no switch.
