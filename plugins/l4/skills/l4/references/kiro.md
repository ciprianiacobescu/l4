# Kiro specs: what reaches the implementer

For a Kiro unit (`.kiro/specs/<name>/`) the implementer's prompt is built by the harness from your files.

- **Criteria and tasks.** Each criterion of `requirements.md` that a task's `_Requirements:_` line names arrives with its
  full text, and the task arrives with every line of its block in `tasks.md` (detail bullets, parent task lines,
  headings). Neither is ever cut. A red step must write a new test for each criterion that line names, unless an earlier
  task already proved it.
- **Steering.** `.kiro/steering/*.md` is used by its inclusion mode: no front matter or `always` (always),
  `fileMatch` (when a pattern matches a path of the task or of the unit branch), `manual` (when the task, the
  requirements or the design says `#<file name>`) and `auto` (last, when the budget has room). `AGENTS.md` joins only
  with `implementer.include_agents_md: true`; `CLAUDE.md` and `~/.kiro` never do.
- **Long files.** The prompt has a budget (`implementer.context_budget_tokens`, 32000). Requirements come first, then the
  design sections the task names, then the rest. Whatever is cut is listed under `# Not shown in full`.
- **Check before a run.** `l4 run --dry-run` prints the budget, each steering decision and each cut for the next
  task; `l4 status --unit <name>` shows the last `Prompt cut:`. Fix a cut by shortening the file or by raising
  `implementer.context_budget_tokens` (a profile may set its own).
