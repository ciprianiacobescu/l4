# `.gitattributes` is a protected path

## Why

Git attributes decide what a diff shows. An agent step that writes `*.py -diff` into a `.gitattributes` makes every
Python change of the unit read as `Binary files a/x.py and b/x.py differ` in the judge's diff (`--no-ext-diff
--no-textconv`) and in step 1's `-U0` scans (suppressions, skip markers), so an added `# noqa` or a weakened check is not
seen [V, 2026-10-31: reproduced with the verifier's own diff arguments in a scratch repository]. A `diff=` driver or a
`working-tree-encoding` changes the bytes they read too. `.gitattributes` was on no protected list.

## What changes

- `**/.gitattributes` joins the contract list of protected paths (matched in any case), and the root `.gitattributes`
  is listed literally among the anchored roots, so an edited `.gitignore` cannot hide it. What a step or a gate writes
  there is put back with `guard.violation`, like the CI files and the agent configuration.
- Not changed: a person's `.gitattributes` (base branch or unit branch) is the owner's and is listed as a protected path
  changed by a human; the prompt's contract text (no template bump); the verifier's diff arguments.

## Impact

- Code: `l4.security.protected` (`CONTRACT_PROTECTED_GLOBS`, `ANCHORED_ROOT_FILES`).
- Spec: L4-SEC-004 amended; SCN-SEC-120, SCN-SEC-121; change-table row 109.
