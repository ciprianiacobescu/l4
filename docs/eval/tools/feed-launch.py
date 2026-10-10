#!/usr/bin/env python3
"""feed-launch.py OUT [l4 eval args...]: start launch.sh on the runner with the magnitude key on its stdin.

The key is read from Mintkey in this process (secret `magnetude-api-key`) and written only to the SSH channel's stdin;
it is never printed, logged or put on a command line. Output is scrubbed of it all the same."""

import shlex
import subprocess
import sys

sys.path.insert(0, "/Users/USER/src/l4/scripts/dev")
from mintkey_secret import secret_value  # noqa: E402

MK = "/Users/USER/src/l4/scripts/runner/mk-ssh.sh"
W = "/home/gitlab-runner/l4-eval-20261008"
try:
    key = secret_value("magnetude-api-key")
except Exception as exc:  # noqa: BLE001
    key = ""
    print(f"feed-launch: no magnitude key ({type(exc).__name__}); magnitude cells will be invalid", file=sys.stderr)
remote = f"sudo -n -u gitlab-runner -H bash -l {W}/launch.sh " + " ".join(shlex.quote(a) for a in sys.argv[1:])
done = subprocess.run([MK, "--", remote], input=key + "\n", text=True, capture_output=True, timeout=300, check=False)


def scrub(text: str) -> str:
    return text.replace(key, "[MAGNITUDE_KEY]") if key else text


print(scrub(done.stdout), end="")
print(scrub(done.stderr), end="", file=sys.stderr)
print(f"feed-launch: key {'sent' if key else 'absent'} ({len(key) > 0}), exit {done.returncode}")
sys.exit(done.returncode)
