## Purpose

Any coding agent that has `l4` installed gets the `l4` skill with one command, matching the installed version.

## ADDED Requirements

### Requirement: L4-SKL-003 One command installs the l4 skill for every coding agent
The wheel and the sdist SHALL carry the `l4` skill folder byte-equal to `plugins/l4/skills/l4`. `l4 skills install`
SHALL copy it, without network, to `~/.claude/skills/l4`, `~/.agents/skills/l4` (and `~/.codex/skills/l4` when
`~/.codex/skills` exists), `~/.config/opencode/skills/l4` and `~/.kiro/skills/l4`, or with `--project` to
`.claude/skills/l4`, `.agents/skills/l4`, `.opencode/skills/l4` and `.kiro/skills/l4` in the repository root.
`--agent auto` (the default) SHALL pick the agents whose home folder or CLI is present, `all` every one. Each target SHALL
get `.l4-skill.json` with the version and the file hashes; a rerun SHALL replace a copy whose files still match its
manifest, and SHALL refuse a copy with edited files unless `--force`. A target that is a symbolic link or resolves
outside its agent folder SHALL be refused. `l4 skills status` SHALL list each target with its version, `current` or
`old`, and `edited`. Doctor row SKL-003 SHALL warn when an installed copy is older than the running `l4`.

#### Scenario: SCN-SKL-04 (+) One command installs the skill for the agents that are present
- **GIVEN** a home folder with `~/.claude` and `~/.kiro`, and no Codex or OpenCode folder or CLI
- **WHEN** `l4 skills install` runs
- **THEN** `~/.claude/skills/l4/SKILL.md` and `~/.kiro/skills/l4/SKILL.md` equal the package's copy, each folder has
  `.l4-skill.json` with the running version, nothing else is written, and the output names the two targets

#### Scenario: SCN-SKL-05 (+) A rerun after an upgrade updates the skill in place
- **GIVEN** the install of SCN-SKL-04 made by an older `l4`, its files unchanged
- **WHEN** the newer `l4 skills install` runs
- **THEN** both copies hold the new files and the new version, and `l4 skills status` says `current`

#### Scenario: SCN-SKL-06 (−) An edited copy is not overwritten
- **GIVEN** an installed copy whose `references/plan.md` a person edited
- **WHEN** `l4 skills install` runs without `--force`
- **THEN** that target is refused with the edited path named, the others are installed, the exit code is 2, and
  `--force` replaces it

#### Scenario: SCN-SKL-07 (+) A team installs the skill into the repository
- **GIVEN** a repository checkout
- **WHEN** `l4 skills install --project --agent all` runs
- **THEN** the four project folders hold the skill, ready to commit

#### Scenario: SCN-SKL-08 (−) An old installed skill is named by doctor
- **GIVEN** `~/.claude/skills/l4/.l4-skill.json` with a version older than the running `l4`
- **WHEN** `l4 doctor` runs
- **THEN** SKL-003 warns with the fix `l4 skills install`
