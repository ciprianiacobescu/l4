## Why

On a consumer repository (harness 0.4.10) a unit halted after five red attempts on one task, every one refused as
`vacuous: C-… (its tests pass or error against the zero-value stubs …)`. The task added `search_phase`, a
`@contextmanager` function. Red stubs it as `raise NotImplementedError`, and run (b) rewrites the stub to the zero value
of its annotation `Iterator[Phase]`, which was `return None`. `contextmanager` then calls a function that returns no
generator, so every `with search_phase(...)` raised `TypeError: 'NoneType' object is not an iterator` before the test
body ran. No test of a context manager could fail by assertion, whatever the agent wrote.

## What Changes

- **The zero value of a generator or a context manager keeps its kind** (L4-IMP-026). A `contextmanager` or
  `asynccontextmanager` function yields the zero value of what it yields, once; an exception of the block still reaches
  the caller. Any other generator yields nothing. A function annotated to return a context manager returns
  `contextlib.nullcontext()`, one annotated `Iterator`, `Iterable` or `Generator` an empty iterator. A red stub, which
  has no `yield`, is judged by its decorator and annotation.
- **The `vacuous` message says how to test a context manager**: assert on what it yields
  (`with f() as x: assert x is not None`) or on its effects after the block.

## Impact

- `src/l4/implementer/stubs.py` (`_zero_body`), `src/l4/implementer/discrimination.py` (the message).
- `docs/SPEC.md` (the zero-value paragraph of L4-IMP-002, L4-IMP-026, SCN-IMP-216..218, the change row), `CHANGELOG.md`.
