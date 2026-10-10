# Proposal: fix 1 for add-pickup-notice

## Why
The verifier found problems in `add-pickup-notice` that this change fixes. The findings are listed below with their ids; each task of this change names the ones it answers.

## What Changes
- F-2aa04fcb (blocker): repository CI failed: test: failing step: `uv run ruff check --select E501 --line-length 92 src` (job `test` at 222e60b307). job `test` (stage test) failed on the hand-off commit 222e60b307 (<forge>/example-group/dummy-agentic/-/jobs/5647). Log ends: ... --select E501 --line-length 92 src E501 Line too long (106 > 92) --> src/pricing/pickup.py:2:93 | 1 | def pickup_notice() -> str: 2 | return "Pickup orders wait at the shop counter for seven days; bring the order number and a photo ID." | ^^^^^^^^^^^^^^ Found 1 error. ERROR: Job failed: exit code 1. Removing .ruff_cache/ Removing .venv/ Removing src/inventory/__pycache__/ R...

## Impact
The code and the tests of `add-pickup-notice`.
# Tasks

## 1. Fix

- [ ] 1.1 repository CI failed: test (F-2aa04fcb)
