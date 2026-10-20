"""The adapters that can answer a judge's tool-less call, and the roles that hold judges (L4-CFG-006).

A leaf module: it imports nothing from `l4`, so the schema (which `l4.llm.agent_judge` imports) can read it.
"""

# codex as a judge: SPEC 8.1 [U]; opencode: gap G18; kiro-cli: kiro-judge L4-KJD-008, in every judge role
JUDGE_ADAPTERS = ("claude-code", "codex", "opencode", "kiro-cli", "fake")
JUDGE_ROLES = ("judges", "verifier_agent", "clarifier", "s1_judge")
# every adapter the factory builds; a test holds this equal to `l4.agents.factory.ADAPTERS`
HARNESS_ADAPTERS = ("claude-code", "codex", "opencode", "kiro-cli", "command", "fake")
