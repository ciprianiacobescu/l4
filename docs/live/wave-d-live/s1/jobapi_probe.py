"""TEMPORARY (wave D live check, step 1): the l4 watchdog's own call, GET $CI_API_V4_URL/job with the job token
(src/l4/cancel.py `_fetch`: urllib, JOB-TOKEN and Accept headers, a 15 s timeout). Prints only the HTTP code and the
job's status field, never the token or the body."""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

url = os.environ["CI_API_V4_URL"].rstrip("/") + "/job"
req = urllib.request.Request(url, headers={"JOB-TOKEN": os.environ["CI_JOB_TOKEN"], "Accept": "application/json"})
who = f"{sys.argv[1]} (python {sys.version.split()[0]}, {ssl.OPENSSL_VERSION})"
try:
    with urllib.request.urlopen(req, timeout=15) as response:
        body = json.loads(response.read() or b"{}")
        print(f"{who}: http_code={response.status} status={body.get('status')}")
except urllib.error.HTTPError as exc:
    print(f"{who}: http_code={exc.code}")
except Exception as exc:  # noqa: BLE001
    print(f"{who}: error {type(exc).__name__}: {str(exc)[:160]}")
