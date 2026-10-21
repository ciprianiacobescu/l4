# Proposal: fix 1 for add-shipping-notice

## Why
The verifier found problems in `add-shipping-notice` that this change fixes. The findings are listed below with their ids; each task of this change names the ones it answers.

## What Changes
- F-2aa04fcb (blocker): repository CI failed: test: job `test` (stage test) failed on the hand-off commit 0272e10c23 (<forge>/example-group/dummy-agentic/-/jobs/5612). Log ends: ...ect E501 --line-length 92 src E501 Line too long (108 > 92) --> src/pricing/footer.py:2:93 | 1 | def shipping_notice() -> str: 2 | return "Orders placed before 2 pm on a working day leave our warehouse the same day by tracked courier." | ^^^^^^^^^^^^^^^^ Found 1 error. ERROR: Job failed: exit code 1. Removing .ruff_cache/ Removing .venv/ Removing src/inventory/__pycache__/ Removing src/pricing/__pycache__/ Removing src/pricing/web/__pycache__/ Removing tests/__pycache__...

## Impact
The code and the tests of `add-shipping-notice`.
