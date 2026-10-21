"""SPIKE (question D, in the sandbox): one real OpenCode call with a free model through the harness's own sandbox.

`l4 probe` runs its hello outside the sandbox, so it cannot show that an agent works inside bwrap on a hosted runner.
This picks the sandbox the way `l4 run` does (`select_sandbox` with the target's config), builds an agent
`SandboxSpec` for the opencode adapter (its credential paths bound, every other adapter's hidden, an empty
XDG_CONFIG_HOME as the adapter uses) and runs `opencode run -m MODEL` inside it. Run from the target repository with
the vendored harness: `uv run --frozen --no-dev --project .l4/vendor python sandboxed-hello.py MODEL`.
Exit 0 when the answer contains OK.
"""

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

model = sys.argv[1]
target = Path.cwd()
cfg = L4Config.model_validate(yaml.safe_load((target / ".l4/config.yaml").read_text()) or {})
env = dict(os.environ)
env["PATH"] = f"{Path.home()}/.local/bin:{env.get('PATH', '')}"
sandbox = select_sandbox(cfg.sandbox, env, repo=target)
exe = resolve_tool("opencode", env, forbid=(target,))
if exe is None:
    sys.exit("opencode is not on PATH")
tmp = Path(tempfile.mkdtemp(dir=os.environ.get("RUNNER_TEMP") or None))
(tmp / "xdg").mkdir()
credentials = {k: tuple(Path(os.path.expanduser(p)) for p in v) for k, v in cfg.sandbox.credential_paths.items()}
spec = SandboxSpec(
    kind="agent", worktree=target, git_common_dir=target / ".git", tmp_dir=tmp, home=Path.home(),
    credential_paths=credentials, adapter="opencode",
)  # fmt: skip
child_env = {"PATH": env["PATH"], "HOME": str(Path.home()), "TMPDIR": str(tmp), "XDG_CONFIG_HOME": str(tmp / "xdg")}
wrapped = sandbox.wrap([exe, "run", "-m", model, "Reply with the single word OK and nothing else."], spec, child_env)
start = time.monotonic()
done = subprocess.run(wrapped.argv, env=wrapped.env, capture_output=True, text=True, timeout=240)
print(f"sandbox={sandbox.name} exe={exe} rc={done.returncode} seconds={time.monotonic() - start:.1f}")
print("stdout:", done.stdout.strip()[-400:])
print("stderr:", done.stderr.strip()[-400:])
sys.exit(0 if done.returncode == 0 and "OK" in done.stdout.upper() else 1)
