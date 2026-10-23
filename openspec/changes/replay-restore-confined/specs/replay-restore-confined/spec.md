## Purpose

The replay guard of a held step puts every path back without ever following a link: a path that must return to the step
base is written through its folder's file descriptor like the paths of the saved patch.

## ADDED Requirements

### Requirement: L4-IMP-086 The replay guard puts a base path back through the folder's descriptor
When the replay guard puts back a path that is not part of the saved patch and that existed at the step base, it SHALL
write the base entry through the folder's file descriptor, as it writes the patch's paths: a regular file streamed from
the base blob with its executable bit, a link with the target the base blob holds. It SHALL set the index entry with an
index-only command (`git update-index --add --cacheinfo`). The guard MUST NOT run a git command that writes the work
tree by path name (`checkout`, `restore`, `reset --hard`, `stash`, `clean`). A base entry that is neither a regular file
nor a link SHALL fail the step as an attempt with `the replayed step could not be put back to its saved patch (<where>):
<path> is a <kind> at the base`.

#### Scenario: SCN-IMP-411 A folder swapped for a link during the restore gets nothing written outside
- **GIVEN** a replayed step whose base holds `tests/fixtures/old.txt`, a gate that changed files under `tests/fixtures`,
  and a process that keeps swapping `tests/fixtures` for a link to a folder outside the work tree
- **WHEN** the guard restores after the gate, 60 times
- **THEN** the outside folder is never changed

#### Scenario: SCN-IMP-412 The restore of a base path runs no path-based git write
- **GIVEN** a replayed step and a gate that changed a tracked file that is not part of the saved patch
- **WHEN** the guard restores
- **THEN** the file holds its base content and mode, `git diff --quiet <base> -- <path>` succeeds, and no git command
  of the restore is `checkout`, `restore`, `reset --hard`, `stash` or `clean`
