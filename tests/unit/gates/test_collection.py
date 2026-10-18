from l4.gates.collection import called_names, deepest_location, error_lines, first_error_line, ledger_excerpt

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
