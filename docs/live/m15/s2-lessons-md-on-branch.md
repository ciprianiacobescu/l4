<!-- l4:lessons v1 — harness-owned; propose changes via .serena/memories/inbox/ -->

## L-09421538 · UI criteria need an end-to-end test
- **Scope:** `src/pricing/web/**`
- **Source:** verifier round 1
- **Dedupe key:** ui-criterion-without-e2e-test
- **Reinforced:** 1 · 2026-10-05
A criterion about what a user sees or does needs a browser test that traces it by id (`C-<hex>` in the test name). A unit test does not cover it. Write the end-to-end test with the change, not after the verifier asks.
