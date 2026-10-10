## Purpose

Make adopting the L4 harness a one-command job and make a shell-executor runner self-sufficient: install missing tools user-locally
without root, never authenticate on anyone's behalf, report adapter readiness, and document the runner failure that blocks every job.

## ADDED Requirements

### Requirement: L4-PRV-001 One-command bootstrap
The harness SHALL ship an `install.sh` at its repository root. Run as `curl -fsSL <raw-url>/<sha>/install.sh | bash -s -- <l4 args>`, it MUST install uv into `~/.local/bin` when uv is absent (no sudo) and then execute `uvx --from git+<repo-url>@<sha> l4 <l4 args>`; when uv is present it MUST skip the uv installation.

#### Scenario: SCN-PRV-01 (+) Bootstrap on a machine without uv
- **GIVEN** a Linux user account with git and curl, no uv, and a target git repository
- **WHEN** `install.sh` runs with `L4_REF=<40-hex sha>`, `L4_REPO_URL=<url>` and the arguments `init --ci gitlab`
- **THEN** `~/.local/bin/uv` exists, `l4 init --ci gitlab` has run through `uvx --from git+<url>@<sha>`, and the exit code is 0

#### Scenario: SCN-PRV-02 (+) Bootstrap with uv already present
- **GIVEN** uv is already on the PATH
- **WHEN** `install.sh` runs with a valid ref and `--version`
- **THEN** no uv installer is downloaded, `l4 --version` prints the harness version and the exit code is 0

#### Scenario: SCN-PRV-03 (−) Bootstrap without git stops with the manual command
- **GIVEN** a machine where `git` is not installed
- **WHEN** `install.sh` runs with a valid ref
- **THEN** it installs nothing, names `git` as missing, prints `sudo apt-get install -y git` (or the distro equivalent) without running it, and exits 3

### Requirement: L4-PRV-002 Pinned ref required
`install.sh` MUST require the harness version as a full 40-hex commit SHA (argument `--ref` or variable `L4_REF`) and the repository URL (`--repo` or `L4_REPO_URL`). It MUST refuse a branch name, a tag name, a short SHA or an empty value with exit code 2 before downloading anything.

#### Scenario: SCN-PRV-04 (−) A branch name is refused
- **GIVEN** `L4_REF=main`
- **WHEN** `install.sh` runs
- **THEN** it exits 2 with a message that a full commit SHA is required, and no network request was made

#### Scenario: SCN-PRV-05 (−) A missing repository URL is refused
- **GIVEN** a valid 40-hex `L4_REF` and neither `--repo` nor `L4_REPO_URL`
- **WHEN** `install.sh` runs
- **THEN** it exits 2 naming the missing repository URL and installs nothing

### Requirement: L4-PRV-003 Footprint and shell profiles
After `install.sh ... init`, the target repository MUST contain only the files listed in L4-INS-002 as new or changed. The bootstrap and `l4 doctor --fix` MUST NOT modify any shell profile of the user (`~/.bashrc`, `~/.bash_profile`, `~/.profile`, `~/.zshrc`, `~/.bash_logout`) and MUST place tools only under `~/.local/bin`, `$L4_HOME` (default `~/.local/share/l4`), `$L4_CACHE` or the vendor installer's own user-local directory.

#### Scenario: SCN-PRV-06 (+) Only the init footprint appears in the repository
- **GIVEN** a clean Python repository with OpenSpec
- **WHEN** `install.sh` runs with `init --ci gitlab`
- **THEN** `git status --porcelain` lists exactly the L4-INS-002 paths and nothing else

#### Scenario: SCN-PRV-07 (−) Shell profiles stay byte-identical
- **GIVEN** the checksums of `~/.bashrc`, `~/.profile`, `~/.bash_logout` and `~/.zshrc` before the run
- **WHEN** `install.sh` and then `l4 doctor --fix` install uv, Node and an agent CLI
- **THEN** every profile file has the same checksum afterwards (installers ran with their no-modify-path switch)

### Requirement: L4-PRV-004 Install uv user-locally (part a)
When ENV-001 finds uv missing, `l4 doctor --fix` MUST install uv into `~/.local/bin` with the official installer, without sudo, and MUST then re-run the check in the same run.

#### Scenario: SCN-PRV-08 (+) Missing uv is installed
- **GIVEN** a shell-executor user with no uv anywhere on disk
- **WHEN** `l4 doctor --fix` runs
- **THEN** `~/.local/bin/uv --version` works, ENV-001 is reported fixed in the same run, and no command ran with elevated privileges

#### Scenario: SCN-PRV-09 (−) Installed uv outside PATH is not reinstalled
- **GIVEN** `~/.local/bin/uv` exists but `~/.local/bin` is not on the job PATH
- **WHEN** `l4 doctor --fix` runs
- **THEN** ENV-001 passes through the harness search path and no uv installer runs

### Requirement: L4-PRV-004 Install Node user-locally (part b)
When OpenSpec is an active framework and `node` is missing or older than 20.19, `--fix` MUST download the pinned Node tarball for the host platform from nodejs.org, verify it against the published `SHASUMS256.txt`, and extract it atomically to `$L4_HOME/node`. A system Node MUST NOT be altered or removed.

#### Scenario: SCN-PRV-10 (+) Missing Node is provisioned
- **GIVEN** OpenSpec is active and no `node` exists for the user
- **WHEN** `l4 doctor --fix` runs
- **THEN** `$L4_HOME/node/bin/node --version` reports a version of at least 20.19 and ENV-003 passes

#### Scenario: SCN-PRV-11 (−) Too-old system Node is left alone
- **GIVEN** the system `node` is v18 and OpenSpec is active
- **WHEN** `l4 doctor --fix` runs
- **THEN** `$L4_HOME/node` holds the pinned Node, the system v18 binary is untouched, and harness subprocesses use the pinned Node

#### Scenario: SCN-PRV-12 (−) Node is not installed when OpenSpec is not active
- **GIVEN** a Kiro-only repository and no node on the machine
- **WHEN** `l4 doctor --fix` runs
- **THEN** no Node tarball is downloaded and the report says Node is not required

### Requirement: L4-PRV-004 Install OpenSpec into a harness prefix (part c)
When OpenSpec is active and the pinned CLI is not runnable, `--fix` MUST run `npm install --prefix $L4_CACHE/tools/openspec-<version> @fission-ai/openspec@<version>` (version from `spec.openspec.version`, default 1.14.0) with the harness Node. It MUST NOT use `npx`, a global npm install, or the repository's `node_modules`.

#### Scenario: SCN-PRV-13 (+) OpenSpec 1.14.0 lands in the harness prefix
- **GIVEN** Node is available and no OpenSpec prefix exists
- **WHEN** `l4 doctor --fix` runs
- **THEN** `$L4_CACHE/tools/openspec-1.14.0/node_modules/.bin/openspec --version` prints 1.14.0 and ENV-003 passes

#### Scenario: SCN-PRV-14 (−) No global install and no planted package is used
- **GIVEN** a repository containing a planted `node_modules/@fission-ai/openspec`
- **WHEN** `l4 doctor --fix` runs in that repository
- **THEN** the planted package does not execute, `npm ls -g` is unchanged, and the OpenSpec binary used is the one in the harness prefix

### Requirement: L4-PRV-005 Install agent CLIs user-locally (part a)
For each adapter profile in any role chain whose binary is missing or below `min_version`, `--fix` MUST run that CLI's official user-local installer for claude-code, opencode and kiro-cli, and MUST then verify the installed version.

#### Scenario: SCN-PRV-15 (+) Missing Claude Code and OpenCode are installed
- **GIVEN** profiles `claude-sonnet` and `opencode-or` in the chains and neither binary present
- **WHEN** `l4 doctor --fix` runs
- **THEN** both binaries are present afterwards at a version satisfying `min_version`, found through the harness search path, and ENV-004 passes for them

#### Scenario: SCN-PRV-16 (−) An installer that leaves an older version fails the fix
- **GIVEN** a profile whose `min_version` is higher than the version the installer produces
- **WHEN** `l4 doctor --fix` runs
- **THEN** the action is reported `failed` with both versions, ENV-004 stays failed and the exit code is 3

### Requirement: L4-PRV-005 Install Codex into a harness prefix (part b)
For a codex profile whose binary is missing or too old, `--fix` MUST run `npm install --prefix $L4_CACHE/tools/codex-<version> @openai/codex@<version>`, where version is the highest `min_version` among codex profiles, or 0.160.0 when none is set, and expose the binary through the harness search path.

#### Scenario: SCN-PRV-17 (+) Codex 0.160.0 is installed under the harness prefix
- **GIVEN** a codex profile without `min_version` and no codex binary
- **WHEN** `l4 doctor --fix` runs
- **THEN** `$L4_CACHE/tools/codex-0.160.0/node_modules/.bin/codex --version` prints 0.160.0 and ENV-004 passes

#### Scenario: SCN-PRV-18 (−) A codex profile with a higher floor installs that version only
- **GIVEN** a codex profile with `min_version: 0.161.0`
- **WHEN** `l4 doctor --fix` runs
- **THEN** the prefix directory is `codex-0.161.0`, and no `codex-0.160.0` prefix is created

### Requirement: L4-PRV-005 Install only what the configuration needs (part c)
`--fix` MUST install only tools required by the effective configuration: Node and OpenSpec only when OpenSpec is an active framework, and an agent CLI only when a profile using it appears in some role chain.

#### Scenario: SCN-PRV-19 (−) Unused adapters are not installed
- **GIVEN** a configuration whose chains reference only `claude-sonnet`
- **WHEN** `l4 doctor --fix` runs on a machine with no agent CLI
- **THEN** only Claude Code is installed; codex, opencode and kiro-cli are not downloaded

#### Scenario: SCN-PRV-20 (+) A fallback-only adapter is installed
- **GIVEN** `codex-sol` appears only as a fallback in the implementer chain
- **WHEN** `l4 doctor --fix` runs
- **THEN** Codex is installed as well

### Requirement: L4-PRV-006 Never escalate privileges (part a)
`l4 doctor --fix` and `install.sh` MUST NOT invoke `sudo`, `su`, `doas` or any other privilege escalation, and MUST NOT write outside the invoking user's home directory and temporary directory.

#### Scenario: SCN-PRV-21 (−) A passwordless sudo is never used
- **GIVEN** a `sudo` shim first on the PATH that records every call, and a missing Node
- **WHEN** `l4 doctor --fix` runs
- **THEN** the shim was never called and Node was installed under `$L4_HOME`

### Requirement: L4-PRV-006 Root-only prerequisites are printed, not installed (part b)
For a prerequisite that needs root (bubblewrap `bwrap`, and git when missing), doctor MUST report the action as `manual` and print the exact command for the detected distribution (`sudo apt-get install -y bubblewrap` on Debian-like systems, `sudo dnf install -y bubblewrap` on Fedora-like systems); `--fix` MUST NOT attempt it.

#### Scenario: SCN-PRV-22 (+) Missing bubblewrap prints the sudo command
- **GIVEN** an Ubuntu 24.04 runner user without `bwrap` and `sandbox.mode: bwrap`
- **WHEN** `l4 doctor --fix` runs
- **THEN** the report contains `sudo apt-get install -y bubblewrap` as a `manual` action, SANDBOX-001 stays failed, and the exit code is 3

#### Scenario: SCN-PRV-23 (−) An unknown distribution prints a generic instruction
- **GIVEN** `/etc/os-release` names a distribution the tool does not know
- **WHEN** `l4 doctor --fix` runs
- **THEN** the report says to install `bubblewrap` with the system package manager as root and prints no distro-specific command

### Requirement: L4-PRV-007 Never authenticate (part a)
`l4 doctor --fix` and `install.sh` MUST NOT run any login, token or account command (`claude setup-token`, `claude auth login`, `codex login`, `kiro-cli login`, `opencode auth login`), MUST NOT read from stdin, and MUST NOT create or modify credential files or environment secrets.

#### Scenario: SCN-PRV-24 (−) No login command is ever executed
- **GIVEN** fake agent binaries that record their argv, all logged out
- **WHEN** `l4 doctor --fix` runs
- **THEN** no recorded argv contains `login`, `setup-token` or `auth login`, and no credential file was created

### Requirement: L4-PRV-007 Human authentication steps for Claude and OpenCode (part b)
For every configured claude-code or opencode profile that is not authenticated, doctor MUST print the human steps: Claude subscription auth: run `claude setup-token` where a browser exists and store the result as masked CI variable `CLAUDE_CODE_OAUTH_TOKEN`; Claude api_key auth: masked variable `ANTHROPIC_API_KEY`; OpenCode via OpenRouter: masked variable `OPENROUTER_API_KEY`.

#### Scenario: SCN-PRV-25 (+) Steps for an unauthenticated Claude subscription profile
- **GIVEN** profile `claude-sonnet` with `auth: subscription`, installed, with no `CLAUDE_CODE_OAUTH_TOKEN` and no stored login
- **WHEN** `l4 doctor` runs
- **THEN** the output tells the human to run `claude setup-token` and to create the masked CI variable `CLAUDE_CODE_OAUTH_TOKEN`

#### Scenario: SCN-PRV-26 (−) No steps are printed for an authenticated profile
- **GIVEN** `OPENROUTER_API_KEY` is set and `opencode-or` is installed
- **WHEN** `l4 doctor` runs
- **THEN** no authentication steps are printed for `opencode-or`

### Requirement: L4-PRV-007 Human authentication steps for Codex and Kiro (part c)
For every configured codex or kiro-cli profile that is not authenticated, doctor MUST print the human steps: Codex subscription auth: run `codex login --device-auth` on the runner VM as the runner user; Codex api_key auth: variable `CODEX_API_KEY`; Kiro: `kiro-cli login` on the VM, or the masked variable `KIRO_API_KEY`.

#### Scenario: SCN-PRV-27 (+) Steps for a logged-out Codex profile
- **GIVEN** `codex login status` exits 1 for profile `codex-sol` with `auth: subscription`
- **WHEN** `l4 doctor` runs
- **THEN** the output tells the human to run the Codex device login on the runner VM as the runner user, and nothing was executed to do it

#### Scenario: SCN-PRV-28 (−) Steps name the runner user, not the developer machine
- **GIVEN** a logged-out `kiro-cli` profile
- **WHEN** `l4 doctor` runs
- **THEN** the printed steps say the login must be done on the runner VM as the user that executes jobs, or `KIRO_API_KEY` must be set as a masked variable

### Requirement: L4-PRV-008 Adapter readiness states
Doctor MUST classify every configured adapter profile as `ready`, `installed-not-authenticated` or `missing` and print one line `<profile> <adapter> <state>` per profile (also in `--json`). `ready` requires the binary at or above `min_version` and an authentication signal: a credential variable name present or the CLI's own status command succeeding. Credential validity is left to `--live`.

#### Scenario: SCN-PRV-29 (+) All three states in one run
- **GIVEN** `claude-sonnet` installed and authenticated, `codex-sol` installed and logged out, `kiro` not installed
- **WHEN** `l4 doctor --json` runs
- **THEN** the states are `ready`, `installed-not-authenticated` and `missing` respectively, in the JSON and in the table

#### Scenario: SCN-PRV-30 (−) A present binary below the floor is not ready
- **GIVEN** `codex` 0.150.0 installed and `min_version: 0.160.0`
- **WHEN** `l4 doctor` runs
- **THEN** the profile is reported `missing` (below floor) and never `ready`

### Requirement: L4-PRV-009 No secrets or e-mail addresses in output
Doctor output, `--json` output and logs MUST NOT contain account e-mail addresses, tokens or credential values. The output of a CLI status command (for example `claude auth status`) MUST be reduced to `logged_in`, `auth_method` and `plan` before it is printed or logged.

#### Scenario: SCN-PRV-31 (−) A status command that prints an e-mail and a token is sanitised
- **GIVEN** a fake `claude auth status` that prints an e-mail address and a token string
- **WHEN** `l4 doctor --json -v` runs
- **THEN** neither string appears in stdout, stderr, the JSON, or `.l4-out/logs`

### Requirement: L4-PRV-010 Generated CI runs the self-provisioning doctor (part a)
When `ci.self_provision` is `true`, or `auto` with `ci.platform: gitlab`, the generated CI file MUST call `l4 doctor --ci --fix` as the first `l4` command of the first job, on a single line; otherwise it MUST call `l4 doctor --ci` without `--fix`. The key defaults to `auto`.

#### Scenario: SCN-PRV-32 (+) GitLab default renders the provisioning doctor
- **GIVEN** `ci.platform: gitlab` and `ci.self_provision` unset
- **WHEN** `l4 ci render --platform gitlab` runs
- **THEN** the first `l4` command in the `detect` job is `l4 doctor --ci --fix` on one line

#### Scenario: SCN-PRV-33 (−) Disabled provisioning renders no --fix
- **GIVEN** `ci.self_provision: false`
- **WHEN** `l4 ci render --platform gitlab` runs
- **THEN** the rendered file contains `l4 doctor --ci` and no `--fix`

#### Scenario: SCN-PRV-34 (−) GitHub auto renders no --fix
- **GIVEN** `ci.platform: github` and `ci.self_provision: auto`
- **WHEN** `l4 ci render --platform github` runs
- **THEN** the doctor step has no `--fix`

### Requirement: L4-PRV-010 Self-provisioning is resolved at run time (part b)
At run time `ci.self_provision: auto` MUST resolve to true unless the platform reports a disposable environment (GitLab `CI_DISPOSABLE_ENVIRONMENT=true`, GitHub `RUNNER_ENVIRONMENT=github-hosted`). When it resolves to false, `--fix` MUST apply no provisioning action and report each as `skipped`.

#### Scenario: SCN-PRV-35 (+) A shell executor provisions
- **GIVEN** `GITLAB_CI=true`, `CI_DISPOSABLE_ENVIRONMENT` unset and a missing Node
- **WHEN** `l4 doctor --ci --fix` runs with `ci.self_provision: auto`
- **THEN** Node is installed and the action is `applied`

#### Scenario: SCN-PRV-36 (−) A disposable environment skips provisioning
- **GIVEN** `CI_DISPOSABLE_ENVIRONMENT=true` and a missing Node
- **WHEN** `l4 doctor --ci --fix` runs with `ci.self_provision: auto`
- **THEN** no download happens, the action is `skipped` with the reason, and ENV-003 fails with exit 3

### Requirement: L4-PRV-010 Scope of --fix inside CI (part c)
With `--ci`, `l4 doctor --fix` MUST apply only provisioning fixes and MUST NOT apply repository-mutating fixes (CI-001 re-render, FORGE-003 label creation, GIT-001/002/003 cleanups); those run only when `--fix` is used without `--ci`.

#### Scenario: SCN-PRV-37 (−) CI file is never re-rendered by a CI doctor
- **GIVEN** CI-001 fails because `harness.version` differs from the CI file
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** the CI file is byte-identical afterwards, CI-001 still fails and the exit code is 3

### Requirement: L4-PRV-011 Runner profile failure is documented (part a)
The user documentation (`docs/runner-setup.md`, linked from the README) MUST describe the failure signature `ERROR: Job failed: prepare environment: exit status 1` appearing right after `Running on <host>`, its cause (the runner user's `~/.bash_logout` running `clear_console`), the fix `sudo mv /home/gitlab-runner/.bash_logout{,.disabled}`, and that doctor cannot detect it from inside a job.

#### Scenario: SCN-PRV-38 (+) The documentation contains the signature and the fix
- **GIVEN** the repository documentation
- **WHEN** the docs test greps `docs/runner-setup.md`
- **THEN** it finds the exact signature line, `clear_console`, `~/.bash_logout` and the exact `sudo mv` command

#### Scenario: SCN-PRV-54 (−) Ordinary script failures do not trigger the profile advice
- **GIVEN** a job log where script lines (`$ ...`) appear between `Running on <host>` and `ERROR: Job failed: exit code 1`
- **WHEN** a reader applies the troubleshooting section of `docs/runner-setup.md`
- **THEN** the section states the signature holds only when no script output precedes the error, so the `.bash_logout` fix is not recommended for ordinary script failures

### Requirement: L4-PRV-011 Init prints the runner notice for GitLab (part b)
`l4 init` for a GitLab target MUST print once a notice that names the failure signature and the fix command and links `docs/runner-setup.md`. The harness MUST NOT edit `~/.bash_logout` or any runner profile itself.

#### Scenario: SCN-PRV-39 (+) GitLab init prints the notice
- **GIVEN** a repository without `.l4/`
- **WHEN** `l4 init --ci gitlab` runs
- **THEN** the output contains the signature `prepare environment: exit status 1` and the `sudo mv` fix, and the profile files are unchanged

#### Scenario: SCN-PRV-40 (−) GitHub init prints no GitLab runner notice
- **GIVEN** a repository without `.l4/`
- **WHEN** `l4 init --ci github` runs
- **THEN** the output does not contain `bash_logout`

### Requirement: L4-PRV-012 Idempotence and atomic installs
A second `l4 doctor --fix` run with unchanged configuration MUST perform no download and no install, report each tool as `already present` and return the same exit code as the first run's final state. Installs MUST be atomic: an interrupted run leaves no partial tool directory that a later run could mistake for a complete one.

#### Scenario: SCN-PRV-41 (+) The second run changes nothing
- **GIVEN** a successful first `l4 doctor --fix`
- **WHEN** it runs again with network access blocked
- **THEN** every action is `already present`, the file tree under `~/.local` and `$L4_CACHE` is unchanged, and the exit code is 0

#### Scenario: SCN-PRV-42 (−) An interrupted install is recovered
- **GIVEN** a Node extraction killed halfway, leaving a temporary directory
- **WHEN** `l4 doctor --fix` runs again
- **THEN** the stale temporary directory is removed, Node is installed completely, and `$L4_HOME/node` is never a partial tree

### Requirement: L4-PRV-013 Offline behaviour
When a download needed by `--fix` cannot be reached, the harness MUST print the tool, the unreachable host and the manual command, install nothing for that tool, and exit 3. When nothing is missing, `--fix` MUST NOT need the network.

#### Scenario: SCN-PRV-43 (−) Offline with Node missing exits 3
- **GIVEN** no network and Node missing with OpenSpec active
- **WHEN** `l4 doctor --fix` runs
- **THEN** the message names Node and `nodejs.org`, prints the manual install command, no directory is created, and the exit code is 3

#### Scenario: SCN-PRV-44 (+) Offline with everything present exits 0
- **GIVEN** no network and every required tool present
- **WHEN** `l4 doctor --fix` runs
- **THEN** no network request is attempted and the exit code is 0

### Requirement: L4-PRV-014 Download integrity
Downloaded archives MUST be verified against the publisher's checksum before extraction. Vendor installer scripts MUST be saved to a file, have their SHA-256 logged and be executed from that file, never piped into a shell. A mismatch MUST abort that tool's install, remove partial files and exit 3.

#### Scenario: SCN-PRV-45 (−) A corrupted Node tarball is rejected
- **GIVEN** a tarball whose SHA-256 differs from `SHASUMS256.txt`
- **WHEN** `l4 doctor --fix` runs
- **THEN** nothing is extracted, partial files are removed, the message shows expected and actual digests, and the exit code is 3

#### Scenario: SCN-PRV-46 (+) Installer script digest is logged
- **GIVEN** a missing uv
- **WHEN** `l4 doctor --fix -v` runs
- **THEN** the log contains the SHA-256 of the saved installer script before it executed

### Requirement: L4-PRV-015 Installers run with a clean environment
Installers and npm MUST run with an allow-listed environment (`HOME`, `PATH`, locale, `TMPDIR`, proxy variables and the installer's own switches). Forge, trigger and App tokens and every credential variable of any profile MUST NOT reach them.

#### Scenario: SCN-PRV-47 (−) An installer cannot see forge or agent secrets
- **GIVEN** `L4_FORGE_TOKEN` and `OPENROUTER_API_KEY` set, and a fake installer that dumps its environment
- **WHEN** `l4 doctor --fix` runs it
- **THEN** the dump contains neither variable

### Requirement: L4-PRV-016 One search path for harness tools
Doctor checks and every harness subprocess MUST resolve tools through one search path: `~/.local/bin`, `$L4_HOME/node/bin`, `$L4_CACHE/tools/*/node_modules/.bin`, `~/.opencode/bin`, then the inherited `PATH`. A tool installed by `--fix` MUST be reported present in the same run even when it is not on the job's `PATH`.

#### Scenario: SCN-PRV-48 (+) A freshly installed tool is found in the same run
- **GIVEN** the job `PATH` does not contain `~/.local/bin` and uv is missing
- **WHEN** `l4 doctor --fix` runs
- **THEN** ENV-001 is reported fixed in that run

#### Scenario: SCN-PRV-49 (−) A binary outside the search path is not found
- **GIVEN** a `node` binary in `/opt/other/bin`, not on `PATH`
- **WHEN** `l4 doctor` runs
- **THEN** ENV-003 does not count it

### Requirement: L4-PRV-017 Concurrent provisioning is serialised
Concurrent `--fix` runs on one runner MUST serialise on an exclusive lock at `$L4_CACHE/locks/provision.lock`. A waiting run MUST re-check after acquiring the lock and report `already present` instead of installing again; after 10 minutes without the lock it MUST exit 3 naming the lock path.

#### Scenario: SCN-PRV-50 (+) Two jobs install Node once
- **GIVEN** two `l4 doctor --fix` processes started together with Node missing
- **WHEN** both finish
- **THEN** exactly one downloaded Node, the other reported `already present`, and both exited 0

#### Scenario: SCN-PRV-51 (−) A stuck lock is reported, not broken
- **GIVEN** another process holds the lock for longer than the wait limit
- **WHEN** `l4 doctor --fix` runs
- **THEN** it exits 3 naming `provision.lock` and does not delete the lock file

### Requirement: L4-PRV-018 Dry-run of provisioning
`l4 doctor --fix --dry-run` MUST print every planned action (tool, reason, target path, command) and every manual command, perform no download, install or file write, and return the exit code the checks would produce without `--fix`.

#### Scenario: SCN-PRV-52 (+) Dry-run lists the plan
- **GIVEN** Node and OpenSpec missing
- **WHEN** `l4 doctor --fix --dry-run` runs
- **THEN** the output lists the Node tarball and the OpenSpec `npm install --prefix` command as `planned` and exits 3

#### Scenario: SCN-PRV-53 (−) Dry-run changes nothing
- **GIVEN** the file tree under the user's home before the run
- **WHEN** `l4 doctor --fix --dry-run` runs
- **THEN** the tree is identical afterwards and no network request was made
