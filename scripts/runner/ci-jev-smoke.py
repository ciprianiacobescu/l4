"""Smoke test of the TypeSafe System-One API (Jev) from wherever it runs (CI job or workstation).

Reads the key from $TYPESAFE_API_KEY (CI: masked variable) — never prints it. One request with three typed questions
(noul, choice, score) shaped like the harness's decision points; prints HTTP status, latency, served model, answers and
token usage. Exit 0 = HTTP 200 with an answer for every question.

    TYPESAFE_API_KEY=... python3 scripts/runner/ci-jev-smoke.py [--model jev-latest]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://api.typesafe.ai/v1/systemone"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="jev-latest")
    a = ap.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        print("TYPESAFE_API_KEY is not set")
        return 2
    body = {
        "model": a.model,
        "state": {
            "question": "Should Cart.average_unit_price() return a Decimal or a float?",
            "answer": "Return Decimal: the subtotal is a Decimal and money is quantized with ROUND_HALF_UP.",
            "cited_code": "def subtotal(self) -> Decimal:\n    return sum((item.total for item in self.items), Decimal(0))",
            "finding": "VAT is computed on the subtotal and ignores an applied discount code.",
        },
        "questions": {
            "is_product_decision": {"type": "noul", "instructions": "Is `question` a product or business decision "
                                    "rather than a technical question the repository can answer?"},
            "finding_severity": {"type": "choice", "instructions": "How severe is `finding` for a shop's invoices?",
                                 "criteria": {"blocker": "wrong money charged to every customer",
                                              "major": "wrong amounts in a common case",
                                              "minor": "cosmetic or rare edge case"}},
            "citation_support": {"type": "score", "instructions": "How strongly does `cited_code` support `answer`?",
                                 "criteria": ["unrelated", "weak", "partial", "strong",
                                              "states it directly"]},
        },
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, out = resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"JEV_SMOKE FAIL HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        return 1
    except OSError as e:
        print(f"JEV_SMOKE FAIL network: {type(e).__name__}: {e}")
        return 1
    ms = int((time.monotonic() - t0) * 1000)
    answers = out.get("answers", {})
    ok = status == 200 and set(answers) == set(body["questions"])
    print(f"JEV_SMOKE {'PASS' if ok else 'FAIL'} HTTP {status} in {ms} ms model={out.get('model')} "
          f"usage={json.dumps(out.get('usage'))}")
    print(json.dumps(answers, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
