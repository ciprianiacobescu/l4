---
name: l4
description: Use when working in a repository run by the L4 agentic harness (a .l4/config.yaml, unit branches named l4/<framework>/<name>, feedback.md or questions.md in a spec folder) - asking for changes on a unit's pull request, answering the harness's questions, reading a unit's state, resuming an escalated or halted unit, making or updating a delivery plan (`.l4/plans/`), writing a spec for L4, or adopting L4 in a new repository.
---

# Working with the L4 harness

L4 implements spec units (OpenSpec changes or Kiro specs) test-first and opens one pull request per unit. People
steer it through **files on the unit branch and a push**; the harness acts on its next run. Your job is to write the
right file with the right command, never to do the harness's work by hand.

## Rules

- **Ask for changes with `l4 feedback add`**, then run the `git add`/`git commit`/`git push` lines it prints. Do not
  edit the code on a unit branch to fulfil a request.
- **Never write what the harness owns.** That covers:
  - the Status values `taken` and `addressed`;
  - *Outcome* blocks and index tables;
  - anything under `.l4/`;
  - `verification.md`.

  "The work is done, mark it addressed" is still a request to refuse: a person's push after the hand-off sends the unit
  back to work and makes the PR later, not sooner.
- **Restart or continue a unit with `l4 retry` / `l4 yolo resume` from a base-branch clone**; never by checking out or
  pushing its unit branch (see `references/control-loop.md`).
- **A person merges.** Never merge an L4 pull request unless the person tells you to.
- **Never print, paste or commit a secret.** Agent keys go into the GitHub environment `l4` with
  `l4 setup github --secret NAME=ENVVAR`, the value only in that environment variable.
- **Check before acting.** Run `l4 status`, `l4 feedback list` and read the PR's note: the request may already be
  done, waiting or invalid.
- **Deliver a plan by the runbook.** Run `scripts/yolo_preflight.py <plan>` and do the one `Next:` line it prints.
  Activating a plan and `--force` are a person's: print the command and stop.

## Choose the feedback kind (the most common mistake)

| The request | Kind | Needs |
|---|---|---|
| Restructure; behaviour and existing tests unchanged | `refactor` | `--at FILE:L-L` |
| The same logic in several places | `duplication` | one `--at` per copy |
| Missing or weak tests | `tests` | — |
| A hard-coded value should come from the environment | `config` | `--at` the value, `--env NAME` |
| Anything else that changes behaviour, **a rename, or anything the existing tests would have to follow** | `behaviour` | `--when` and `--then` |

A `refactor` runs with every test file frozen. If the existing tests call the old name, the attempt fails, so a
rename is `behaviour`. No kind may delete, rename, skip or weaken an existing test: ask for the old name to stay as an
alias that the existing tests keep calling.

```sh
git switch l4/<framework>/<name>            # feedback on an open unit is given on its own branch
l4 feedback add --kind config --at src/x.py:12 --env BASE_URL --text "read the URL from BASE_URL, default today's"
# then the three git lines it prints
```

## Where to look next

- `references/feedback.md`: every kind and option, what happens after the push, the note's states, limits, and
  feedback on a merged unit.
- `references/operate.md`: delivering a plan (the runbook from push to activation, the error table, the preflight script); answering `questions.md` with `l4 questions` (the agent rule; verdict questions included),
  reading state, resuming an escalated or halted unit, and the `--reason` of `l4 retry` as the implementer's note.
- A delegate (a model, `delegate.enabled` on the base branch) can answer a unit's questions: `references/operate.md`
  says how to read its answers and how a person turns it on (the `Hint:` line names it).
- `references/control-loop.md`: the one control loop, what to run for each state of a unit or plan, what a stop keeps
  and loses, and the MCP tools.
- `references/adopt.md`: adopting L4 in a repository (private or public), the GitHub setup, a cheap-first implementer chain, a Kiro judge, and upgrades.
- `references/plan.md`: making and updating a delivery plan: `l4 yolo draft`, evidence for each dependency, the
  validator, `l4 yolo check`, and what to hand to a person.
- `references/spec.md`: writing a spec for L4 so that it passes the readiness review on the first try.
- `references/kiro.md`: what a Kiro unit's prompt carries (criteria text, task block, steering) and how to see and fix a cut, and Kiro as a judge or clarifier.
