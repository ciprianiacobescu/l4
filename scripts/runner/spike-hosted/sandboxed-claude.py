"""SPIKE (question D', in the sandbox): one Claude Code call authenticated by CLAUDE_CODE_OAUTH_TOKEN alone, through the
harness's own sandbox, the way `l4 run` would start an agent (`select_sandbox`, an agent `SandboxSpec` for the
claude-code adapter, the real HOME with only claude's credential paths bound).

The token never rides in bwrap's argv (`--setenv NAME VALUE` is readable by any local user through /proc, see
`l4.sandbox.env`): it goes into a new 0600 file in the step's private directory, and a /bin/sh loader inside the sandbox
reads it, deletes the file, exports the variable and execs claude. Run from the target repository with the vendored
harness: `uv run --frozen --no-dev --project .l4/vendor python sandboxed-claude.py`. Prints no value. Exit 0 when claude
answers OK.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

from l4.config.schema import L4Config
from l4.safepath import resolve_tool
from l4.sandbox.base import SandboxSpec
from l4.sandbox.select import select_sandbox

NAME = "CLAUDE_CODE_OAUTH_TOKEN"
LOADER = f'v=$(cat -- "$1") || exit 97; rm -f -- "$1"; export {NAME}="$v"; shift; exec "$@"'

token = os.environ.get(NAME, "").strip()
if not token:
    sys.exit(f"{NAME} is not set")
target = Path.cwd()
cfg = L4Config.model_validate(yaml.safe_load((target / ".l4/config.yaml").read_text()) or {})
env = dict(os.environ)
env["PATH"] = f"{Path.home()}/.local/bin:{env.get('PATH', '')}"
sandbox = select_sandbox(cfg.sandbox, env, repo=target)
exe = resolve_tool("claude", env, forbid=(target,))
if exe is None:
    sys.exit("claude is not on PATH")
tmp = Path(tempfile.mkdtemp(dir=os.environ.get("RUNNER_TEMP") or None))
value_file = tmp / "credential"
fd = os.open(value_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    handle.write(token)
credentials = {k: tuple(Path(os.path.expanduser(p)) for p in v) for k, v in cfg.sandbox.credential_paths.items()}
spec = SandboxSpec(
    kind="agent", worktree=target, git_common_dir=target / ".git", tmp_dir=tmp, home=Path.home(),
    credential_paths=credentials, adapter="claude-code",
)  # fmt: skip
child_env = {"PATH": env["PATH"], "HOME": str(Path.home()), "TMPDIR": str(tmp)}
argv = [
    "/bin/sh", "-c", LOADER, "l4-credential", str(value_file),
    exe, "-p", "--no-session-persistence", "--max-turns", "1", "--output-format", "json",
    "Reply with the single word OK and nothing else.",
]  # fmt: skip
wrapped = sandbox.wrap(argv, spec, child_env)
in_argv = any(token in part for part in wrapped.argv)
in_env = any(token in value for value in wrapped.env.values())
start = time.monotonic()
try:
    done = subprocess.run(wrapped.argv, env=wrapped.env, capture_output=True, text=True, timeout=240)
finally:
    removed = not value_file.exists()
    value_file.unlink(missing_ok=True)
seconds = time.monotonic() - start


def clean(text: str) -> str:
    return text.replace(token, "<redacted>").strip()


try:
    answer = json.loads(done.stdout)
except ValueError:
    answer = {}
result = answer.get("result") if isinstance(answer.get("result"), str) else ""
print(
    f"sandbox={sandbox.name} rc={done.returncode} seconds={seconds:.1f} token_in_bwrap_argv={in_argv} "
    f"token_in_bwrap_env={in_env} value_file_removed_by_loader={removed}"
)
status = answer.get("api_error_status")
print(f"is_error={answer.get('is_error')} api_error_status={status} result={clean(result)[:80]!r}")
if done.returncode != 0 or not answer:
    print("stdout:", clean(done.stdout)[-300:])
    print("stderr:", clean(done.stderr)[-300:])
ok = done.returncode == 0 and not answer.get("is_error") and "OK" in result.upper() and not in_argv and not in_env
sys.exit(0 if ok else 1)
