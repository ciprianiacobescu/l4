## Purpose

`l4 yolo go` answers "where is this plan, and what is the one next command" the same way every time: one stop code per
kind of stop, exactly one next command, an optional JSON document with nothing else on stdout, and runs that are safe to
repeat, to interrupt and to run at the same time.

## ADDED Requirements

### Requirement: L4-YOLO-087 Each stop has its own exit code and exactly one next command
`l4 yolo go` SHALL end with one of: 0 `active` (the plan is active, waiting or completed, now or before), 20
`preflight`, 21 `push`, 22 `not_admitted`, 23 `plan_state`, 24 `review_pending`, 25 `review_failed`, 26 `findings`,
27 `person` (the next step is a person's), 28 `refused` (a called command or an activation check refused, or the plan
lease was lost three times), 29 `not_confirmed`; 1, 2 and 16 keep the meaning of L4-CLI-001. These stop codes MUST NOT
be members of the harness's `ExitCode` and MUST NOT change `SEVERITY_ORDER`, `CI_ALLOWED` or `l4 ci map-exit`. In text
mode it SHALL print one line per step reached, `<step>: <status>: <detail>`, with the output of a command it ran
indented under it and without that command's own `Next:` lines, and SHALL print exactly one `Next:` line, last:
`Next: <command>`, or `Next: a person runs: <command>` for exit 27. The next command of a refusal SHALL be the command
of the refusal's `Fix:` line when it has one, else the go command again. A reason in a next command MUST be quoted for
the shell.

#### Scenario: SCN-YOLO-230 (+) Each stop has its own code and one next command
- **GIVEN** one world per stop of the table (a dirty tree, `--no-push` with a commit ahead, a cycle, a cancelled plan,
  a CI that records nothing with `--wait 0`, a `--local` judge that cannot run, a subject NEEDS_REVISION, an agent at the
  activation, another plan active for an agent, a person who types `yes`) and one active plan
- **WHEN** `l4 yolo go p1 --reason "a b"` runs in each
- **THEN** the exit codes are 20, 21, 22, 23, 24, 25, 26, 27, 28, 29 and 0, each output has exactly one line starting
  with `Next:` and it is the last line, the reason appears as `'a b'` in every go command named, and
  `l4.exitcodes.ExitCode` has no member 20 to 29

### Requirement: L4-YOLO-088 --json prints one document and nothing else
With `--json`, stdout SHALL hold exactly one JSON document, printed when the run ends:
`{schema: "l4/yolo-go@1", plan, step_reached, steps, next_command, exit}`, where `steps` lists the seven steps
`preflight`, `push`, `check`, `review`, `findings`, `accept`, `activate` in that order, each
`{name, status, detail}` with `status` one of `ok`, `done`, `skipped`, `pending`, `stopped`, `person`, `not_reached`,
`step_reached` is the last step whose status is not `not_reached`, `next_command` is the command alone, and `exit`
equals the process's exit code. What a person must read before a prompt, the prompt and the wait's progress line MUST
go to stderr. Exits 1, 2 and 16 print no document.

#### Scenario: SCN-YOLO-231 (+) The JSON document is the only thing on stdout
- **GIVEN** plan `p1` reviewed with B NEEDS_REVISION, and in a second run a person who accepts B with `--accept-findings`
  and types `p1`
- **WHEN** `l4 yolo go p1 --reason R --json` runs, then `l4 yolo go p1 --reason R --json --accept-findings`
- **THEN** each stdout parses as one JSON object with exactly the keys `schema`, `plan`, `step_reached`, `steps`,
  `next_command`, `exit`; the first has `step_reached: findings`, `exit: 26`, `findings.status: stopped`, `accept` and
  `activate` `not_reached`; the second has every step's status set, `exit: 0`; B's findings and the prompt were written
  to stderr

### Requirement: L4-YOLO-089 Safe to run again, to interrupt and to run at the same time
A run SHALL decide each step from the ledger and the repository as they are when it reaches the step. A second run with
nothing changed MUST record nothing, push nothing and start no judge; it SHALL ask the forge for a run only when the
review is still missing. A run interrupted at any point SHALL leave the ledger as the commands it ran left it, and the
next run SHALL go on from there. Concurrent runs SHALL be serialised by the plan ledger's lease (L4-YOLO-006): when a
command `go` runs loses the lease, `go` SHALL read the plan again and decide again, at most three times, and MUST NOT
record a write twice; the fourth lost lease SHALL stop the run with exit 28 and the go command as the next command.

#### Scenario: SCN-YOLO-232 (+) A second run with nothing changed does nothing
- **GIVEN** a run of `l4 yolo go p1 --reason R` that stopped at findings (exit 26) with the review current
- **WHEN** the same command runs again
- **THEN** it exits 26 with the same next command, the plan ref's head is unchanged, nothing is pushed, the forge's
  `start_run` is not called and no judge is built

#### Scenario: SCN-YOLO-233 (+) An interrupted run goes on from where it stopped
- **GIVEN** a run interrupted after `l4 yolo accept` recorded the acceptance of A and before B's (a signal raised in the
  second call), and a run interrupted during the CI wait
- **WHEN** `l4 yolo go p1 --reason R --accept-findings --yes` runs again in each
- **THEN** the first goes on with A's acceptance `ok` (not recorded again), records B's and activates; the second finds
  the review CI recorded meanwhile, reuses it and activates; each exits 0 with one `plan.accepted` per subject and one
  `plan.activated`

#### Scenario: SCN-YOLO-234 (+) A lost lease reads again and records nothing twice
- **GIVEN** a person's `l4 yolo go p1 --reason R --accept-findings --yes` whose first append loses the lease because
  another run recorded the same acceptance of B first
- **WHEN** the run goes on
- **THEN** it reads the plan again, finds B's acceptance holding (`ok`), activates once, exits 0, and the ledger has one
  `plan.accepted` of B and one `plan.activated`

#### Scenario: SCN-YOLO-235 (−) A lease lost again and again stops the run
- **GIVEN** a plan ref whose every append loses the lease
- **WHEN** a person's `l4 yolo go p1 --reason R` reaches the activation
- **THEN** after three re-reads it exits 28 with `the plan moved` and `Next: l4 yolo go p1 --reason R`, and nothing is
  recorded
