## Why

The owner: "a quick install l4 skills command easily available. L4 should be stupidly easy to use by agents." Today the
`l4` skill (`plugins/l4/skills/l4`: SKILL.md, references, the plan validator) reaches only Claude Code, through the
plugin marketplace (`/plugin marketplace add ciprianiacobescu/l4`, `/plugin install l4@l4-harness`). For Codex the
README says to copy the folder by hand; OpenCode and Kiro are not mentioned. The `uv tool install` wheel does not
contain the skill at all (`packages = ["src/l4"]`), so an agent with `l4` on its PATH still has no skill, and no command
can give it one. L4-SKL-001 still says "Not yet built".

## What Changes

- **The skill ships in the package** (L4-SKL-003): the wheel and the sdist carry `plugins/l4/skills/l4` as package data,
  byte-equal to the repository's copy (a test), so the skill always matches the installed `l4`.
- **`l4 skills install`** (L4-SKL-003): copies the bundled skill into every coding agent's skill folder, no network:
  - user scope (default): `~/.claude/skills/l4` (Claude Code), `~/.agents/skills/l4` (Codex and the open Agent Skills
    path), `~/.config/opencode/skills/l4` (OpenCode), `~/.kiro/skills/l4` (Kiro CLI);
  - `--project`: `.claude/skills/l4`, `.agents/skills/l4`, `.opencode/skills/l4`, `.kiro/skills/l4` in the repository
    root, to commit for a team;
  - `--agent auto|all|claude-code|codex|opencode|kiro` (default `auto`: the agents whose home folder or CLI is present);
  - each target gets a manifest (`.l4-skill.json`: version, file hashes); a rerun updates an untouched copy in place
    and refuses a copy someone edited unless `--force`; `--dry-run` prints the plan. One line per target.
- **`l4 skills status`**: per target the installed version, whether it is current, and whether it was edited.
- **Doctor SKL-003** (warning): an installed skill older than the running `l4`, with the fix `l4 skills install`.
- **The front door**: README, `docs/quickstart.md`, the skill's `adopt.md` and `l4 init`'s notes lead with
  `uv tool install git+https://github.com/ciprianiacobescu/l4@vX.Y.Z && l4 skills install`. The marketplace stays for
  Claude Code users who prefer it.

## Impact

- `pyproject.toml` (hatch force-include of the skill), `src/l4/skills_cli.py` (new), `src/l4/cli.py`, `src/l4/doctor/`,
  `src/l4/init/` (the note), tests under `tests/unit/`.
- `docs/SPEC.md` (L4-SKL-001 status, L4-SKL-003, scenarios, the CLI table, the change row), README, quickstart,
  `adopt.md`, CHANGELOG.
- Paths of Codex are documented two ways (`~/.agents/skills`, `~/.codex/skills`); the install writes `~/.agents/skills`
  (the open standard, and what L4-SKL-001 names) and, when `~/.codex/skills` exists, there too.
