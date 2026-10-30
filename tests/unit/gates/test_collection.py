from l4.gates.collection import (
    called_names,
    deepest_location,
    deepest_repo_frame,
    error_lines,
    first_error_line,
    ledger_excerpt,
)

TRACE = (
    "src/pytdd/store.py:12: in <module>\n    class Store:\n"
    'src/pytdd/store.py:14: in Store\n    @telemetry.traced("store.add")\n     ^^^^^^^^^^^^^^^^^^^^^^^^^^^\n'
    "E   TypeError: 'NoneType' object is not callable\n"
)


def test_first_error_line_is_the_first_e_line():
    assert first_error_line(TRACE) == "E   TypeError: 'NoneType' object is not callable"
    assert first_error_line("no error here") == ""


def test_called_names_are_the_called_and_decorated_names():
    assert called_names(TRACE) == {"traced"}
    assert called_names(">       assert telemetry.init(out) is True\n") == {"init"}
    assert called_names('    RATE = load()["rate"]\n') == {"load"}
    assert called_names("    @a.b\n") == {"b"}
    assert called_names("src/a.py:3: in f\n  ^^^^ ~~\nE   KeyError: 'x'\n") == frozenset()


def test_the_deepest_location_is_a_repository_file():
    assert deepest_location(TRACE) == ("src/pytdd/store.py", 14)
    more = TRACE + "/usr/lib/python3.12/site-packages/x.py:3: in f\n.venv/lib/y.py:4: in g\n"
    assert deepest_location(more) == ("src/pytdd/store.py", 14)
    assert deepest_location("nothing") is None


def test_error_lines_are_bounded():
    text = "\n".join(f"E   Error number {i}" for i in range(100))
    assert 0 < len(error_lines(text)) <= 600


def test_ledger_excerpt_holds_the_e_lines_and_one_location():
    assert ledger_excerpt(TRACE) == "E   TypeError: 'NoneType' object is not callable\nsrc/pytdd/store.py:14"
    text = "\n".join(f"E   Error number {i}" for i in range(100)) + "\nsrc/a.py:1: in f\n"
    assert len(ledger_excerpt(text)) <= 600


LIBRARY = (
    "e2e/test_a.py:10: in test_x\n    expect(page).to_have_url(lambda u: True)\n"
    ".venv/lib/python3.12/site-packages/playwright/sync_api/_gen.py:20: in to_have_url\n    return self._sync(x)\n"
    ".venv/lib/python3.12/site-packages/playwright/_impl/_assertions.py:55: Error\nE   Error: value must be a string\n"
)


def test_the_deepest_repo_frame_of_a_library_error_is_the_tests_own_line():
    assert deepest_repo_frame(LIBRARY) == "e2e/test_a.py"


def test_a_frame_in_a_production_module_is_the_deepest_one_when_it_comes_last():
    text = "tests/test_a.py:5: in test_x\n    run()\nsrc/app/x.py:12: KeyError\nE   KeyError: 'k'\n"
    assert deepest_repo_frame(text) == "src/app/x.py"
    after_library = text + ".venv/lib/python3.12/site-packages/y.py:3: in g\n"
    assert deepest_repo_frame(after_library) == "src/app/x.py"


def test_an_absolute_frame_that_is_no_library_cannot_be_told_and_gives_none():
    text = "tests/test_a.py:5: in test_x\n    run()\n/opt/app/src/x.py:12: KeyError\nE   KeyError: 'k'\n"
    assert deepest_repo_frame(text) is None
    assert deepest_repo_frame("/usr/lib/python3.12/x.py:3: in f\n<frozen importlib>:5: in g\n") is None  # no repo frame
    assert deepest_repo_frame("") is None and deepest_repo_frame("E   Error: x\n") is None
    library = "tests/test_a.py:5: in test_x\n/usr/lib/python3.12/site-packages/x.py:3: in f\n"
    assert deepest_repo_frame(library) == "tests/test_a.py"  # an absolute library frame is known
