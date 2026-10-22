GitHub Copilot CLI 1.0.102, recorded on 2026-10-22 with no GitHub token and no credential of any kind.
This is not a contract recording of the GitHub-routed CLI (task 8.1 records that). The directory name is not a plain
version, so it adds no entry to recorded_versions.json.

How each file was made. Every run was `env -i` with only PATH, HOME set to an empty directory and XDG_CACHE_HOME set
to a directory (Linux) in an ubuntu:24.04 container on linux-arm64 (glibc 2.39), with the release tarball
copilot-linux-arm64.tar.gz of v1.0.102 (sha256 checked) unpacked and mounted read-only. The linux-x64 build, run under
emulation, gave byte-identical files.
  version.stdout.txt      `copilot --version`, standard output
  help-config.txt         `copilot help config`, standard output
  help-environment.txt    `copilot help environment`, standard output
  help-permissions.txt    `copilot help permissions`, standard output
  no-auth.stderr.txt      `copilot -p hi`, standard error (standard output was empty)
  no-auth.exit.txt        `copilot -p hi`, exit code
`copilot -p hi --output-format json` gave the same empty standard output, the same standard error and the same exit
code.

Scrubbing: the texts were checked for local paths, user names and host names. None occurred, so none was replaced.
(Any such path in a future recording is replaced by a placeholder such as <scratch>.)
