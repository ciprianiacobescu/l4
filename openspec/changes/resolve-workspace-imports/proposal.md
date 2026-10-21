## Why

A plan on a consumer repository (harness 0.4.8) keeps its Python code in a uv workspace: each member has its own
`pyproject.toml` and a `src` layout under a namespace package (`packages/<name>/src/<namespace>/<name>/…`). Four of
its six delivered units lost a red attempt to the same message: `not discriminating: … (no project source module is
imported by those tests)`.

The zero-value run (L4-IMP-002, "Pre-satisfied criteria") confirms a test of behaviour that already exists by
replacing every public function of the modules the test imports with its zero value. It finds those modules by
looking each import up under the repository root and `src/` only. `from <namespace>.mcp import server` names
`packages/mcp/src/<namespace>/mcp/server.py`, which neither lookup finds, so the run had no module to vary. The
same lookup feeds `head_stub_modules` (run (b) of red), the audit sampling of the verifier (step 4a) and the proof of
tests that people or a test chore wrote (step 4). None of these could vary a workspace module either. In 15 runs of
that repository, no criterion was ever confirmed by the zero-value run.

It also made a weak proof look strong. A unit's scenario "SQLite behaviour is unchanged" pins existing behaviour. The
agent's first red wrote tests that pin it, and they were refused by the message above. Its second attempt cited the
scenario on the tests of the new non-SQLite path instead, which do fail at the base. The round passed with those tests
named as the proof of "SQLite behaviour is unchanged".

## What Changes

- **The modules a test imports are found in a workspace layout** (L4-IMP-025). An import is looked up under the
  repository root, `src`, every directory named `src`, and every directory that holds a `pyproject.toml`, `setup.py`
  or `setup.cfg`, together with that directory's `src`. The directories come from git: tracked files and untracked
  files that are not ignored, so an ignored virtual environment is not searched. Every match is varied, because
  Python takes the first one on its path, which the harness cannot know, and varying a copy the test does not import
  changes nothing.
- The zero-value run, run (b)'s head stubs, the audit sampling and the proof of tests people wrote use the same
  lookup, so all four work in a workspace layout.

## Impact

- `src/l4/implementer/discrimination.py`: `import_roots`, `_resolve` returns every match, `imported_modules` looks
  under the import roots.
- `docs/SPEC.md`: L4-IMP-025 and its scenarios, the change row.
- No configuration, template or prompt change. A repository whose modules sit under the root or `src` gets the same
  modules as before.
