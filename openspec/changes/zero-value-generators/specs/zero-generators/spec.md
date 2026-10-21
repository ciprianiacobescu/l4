## Purpose

A test of a generator or a context manager can fail by assertion against the zero-value variant.

## ADDED Requirements

### Requirement: L4-IMP-026 The zero-value variant of a generator or a context manager still behaves as one
A function decorated with `contextmanager` or `asynccontextmanager` SHALL get the zero-value body
`yield <the zero value of T>` for its `Iterator[T]` or `Generator[T, …]` annotation (`yield None` without one). Any
other function whose own body has a `yield` SHALL get an empty generator. A function annotated to return a context
manager SHALL return `contextlib.nullcontext()`, and one annotated `Iterator`, `Iterable` or `Generator` an empty
iterator. A red stub SHALL be judged by its decorator and annotation. The `vacuous` message SHALL tell how to test a
context manager.

#### Scenario: SCN-IMP-216 (+) A context manager's zero value enters and yields the zero value
- **GIVEN** a red stub `@contextmanager def search_phase(name) -> Iterator[Phase]: raise NotImplementedError`
- **WHEN** the zero-value variant runs a test `with search_phase("fts") as phase: assert phase is not None`
- **THEN** the block is entered and the test fails by assertion, not with a `TypeError`

#### Scenario: SCN-IMP-217 (+) An exception of the block still reaches the caller
- **GIVEN** the zero-value variant of a context manager
- **WHEN** its block raises `ValueError`
- **THEN** the caller sees the `ValueError`

#### Scenario: SCN-IMP-218 (+) A generator's zero value yields nothing
- **GIVEN** `def numbers() -> Iterator[int]` with a `yield` body, and a red stub of the same signature
- **WHEN** a test runs `list(numbers())` against the zero-value variant
- **THEN** both give `[]`
