"""Smoke-test the TypeSafe System-One API (Jev) with the key stored in Mintkey. Prints status, latency, served model
and the answer; never the key.

    python3 scripts/dev/jev_smoke.py [--secret typesafe-jev-api-key] [--model jev-latest]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mintkey_secret import secret_value  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret", default="typesafe-jev-api-key")
    ap.add_argument("--model", default="jev-latest")
    ap.add_argument("--url", default="https://api.typesafe.ai/v1/systemone")
    a = ap.parse_args()
    body = {
        "state": {"question": "Should Cart.is_empty() be a method or a property?",
                  "answer": "A method, like Cart.subtotal() and Cart.total().",
                  "cited_code": "def subtotal(self) -> Decimal:\n    return sum(...)"},
        "model": a.model,
        "questions": {
            "is_product_decision": {"type": "noul", "instructions": "Is `question` a product or business decision "
                                    "rather than a technical one the repository can answer?"},
            "citation_supports": {"type": "noul", "instructions": "Does `cited_code` by itself support `answer`?"},
        },
    }
    req = urllib.request.Request(a.url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {secret_value(a.secret)}",
                                          "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.load(resp)
            status = resp.status
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        return 1
    ms = int((time.monotonic() - t0) * 1000)
    print(f"HTTP {status} in {ms} ms; response keys: {sorted(out)}")
    print(json.dumps({k: v for k, v in out.items() if k != "usage"}, indent=1)[:1500])
    if "usage" in out:
        print("usage:", json.dumps(out["usage"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
