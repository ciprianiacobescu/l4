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
