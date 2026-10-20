# pin-clis: live and download evidence

## 1.1 The four Kiro CLI 2.32.0 Linux archives (2026-10-20)

Each zip was downloaded once from `https://prod.download.cli.kiro.dev/stable/2.32.0/<file>` into a scratch directory
outside the repository, hashed over its bytes with sha256, opened with `zipfile` (nothing extracted, nothing run) and
deleted. The digests equal the table of design D1 (`KIRO_SHA256["2.32.0"]`).

| file | size (bytes) | sha256 | equals the table |
|---|---|---|---|
| `kirocli-x86_64-linux.zip` (`linux-x64`) | 154980622 | `7cea2c90198edc60ccaee9e0d9c9de26902b3824f54a66aa3639a365f7242fbb` | yes |
| `kirocli-aarch64-linux.zip` (`linux-arm64`) | 149913331 | `f66faaa3fa202e7730979e10ad907c43f83220577609c97fdffbb07fc8ef1848` | yes |
| `kirocli-x86_64-linux-musl.zip` (`linux-x64-musl`) | 159551360 | `f12968c2b154cd17f4d1d68b563f3dfba2135065c5c6552f19cceddd60258485` | yes |
| `kirocli-aarch64-linux-musl.zip` (`linux-arm64-musl`) | 151681117 | `219a047427ca2b43681f4788104df5e784eda030d98abeec1c732aac9090eb8b` | yes |

Members under `kirocli/bin/` (uncompressed size in bytes; every file is a regular file, Unix mode 0755; the directory
entry `kirocli/bin/` is mode 0755 and not a file):

| archive | `kiro-cli-term` | `kiro-cli` | `kiro-cli-chat` | `qchat` | `q` |
|---|---|---|---|---|---|
| `linux-x64` | 34060512 | 43931168 | 207496744 | 70 | 65 |
| `linux-arm64` | 31570352 | 40873568 | 196866944 | 70 | 65 |
| `linux-x64-musl` | 34290000 | 44154376 | 211260552 | 70 | 65 |
| `linux-arm64-musl` | 29956304 | 38808976 | 195715560 | 70 | 65 |

The harness extracts only `kiro-cli-term`, `kiro-cli-chat` and `kiro-cli`; the largest is 211260552 bytes, under the
512 MiB bound of `KIRO_MEMBER_MAX`.

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
