Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.

## 1. Protocol (L4-MCP-001)

- [ ] 1.1 Tests: SCN-MCP-01, SCN-MCP-02 (framing, initialize, ping, tools/list, errors) in `tests/unit/mcp/`; an interop
  test with the official `mcp` client (dev dependency) that skips when the package is absent.
- [ ] 1.2 `src/l4/mcp/protocol.py` and `server.py`; `l4 mcp serve`.

## 2. Tools (L4-MCP-002, L4-MCP-003)

- [ ] 2.1 Tests: SCN-MCP-03..07 and SCN-MCP-10..12 (L4-MCP-005: `--repo`, several repositories, refusals, no guess); every tool's argv, cwd, env (`AI_AGENT=l4-mcp`, stdin closed), timeout, truncation,
  JSON parsing; the `repo` argument must be inside a git repository.
- [ ] 2.2 `src/l4/mcp/tools.py`; the smallest read-only command `l4_unit_events` needs, if `l4 status` has no JSON of
  the events.

## 3. Install (L4-MCP-004)

- [ ] 3.1 Verify each client's MCP configuration path and format from its vendor's documentation (keep the URL in the
  code); tests SCN-MCP-08 (one entry per repository, `--repo` and `--name`), SCN-MCP-09 and one per supported client.
- [ ] 3.2 `src/l4/mcp/install.py`; `l4 mcp install`.

## 4. Docs

- [ ] 4.1 `docs/SPEC.md` (a new section for MCP, L4-MCP-001..005, SCN-MCP-01..12, the CLI table, the change row),
  README and `docs/quickstart.md` ("Use L4 from your IDE": `l4 mcp install --client …`), the skill's `operate.md`,
  `CHANGELOG.md` under `## 0.4.15 (unreleased)`.
