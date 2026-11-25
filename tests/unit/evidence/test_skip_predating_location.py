# ruff: noqa: E501, E731, B023, F841  # the review cases below are kept verbatim, with their long lines and lambdas
"""Condition (e) of the skip rule (skipped-test-hold D1 (e), rework 9): WHERE the unit may change the file. (b) and
(d) enumerate what decides a skip (a blacklist), and three review rounds found in-file ways to change WHY an already
skipped test skips that they miss. (e) is a whitelist: every changed line of the file is a blank or comment line, a line
inside the body of a collected test (the skip-relevant part of a candidate, its decorators, signature and the
statements up to its last skip, excepted), or a whole added `import` of names the base does not bind. Pure rule:
`SkipRule`, as `skip_predating` uses it."""

import itertools
from collections.abc import Callable

import pytest

from l4.config.schema import L4Config
from l4.evidence.collect import skip_predating
from l4.evidence.skippred import STEP1_SOURCE, BaseSkips, SkipRule

CFG = L4Config.model_validate({})
CASES: list[tuple[str, str, str, str]] = []


def case(name: str, base: str, head: str, q: str = "test_x") -> None:
    CASES.append((name, base, head, q))


def holds(base: str, head: str, q: str = "test_x", changed: tuple[str, ...] = ()) -> bool:
    """`no_skip_added`, which is (b), (c), (d) and (e) together."""
    return SkipRule(base, head, list(changed), CFG).no_skip_added(q)


# The cases of the third review round (review-h t1, t2, t3), verbatim. Each is a change of WHY a skipped test skips
# that (b) and (d) do not see. Before (e), 38 of the 86 were `True`.


def _t1() -> None:
    H = "import os, sys\nimport pytest\n\n"
    T = "@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
    # control
    case("control flag changed", H + "FLAG = True\n" + T, H + "FLAG = False\n" + T)
    # rebound later: two assignments, second changed
    case("rebound: second assign changed", H + "FLAG = True\nFLAG = True\n" + T, H + "FLAG = True\nFLAG = False\n" + T)
    case(
        "rebound after test def", H + "FLAG = True\n" + T + "FLAG = True\n", H + "FLAG = True\n" + T + "FLAG = False\n"
    )
    # global write in function
    case(
        "global write in helper",
        H + "FLAG = True\ndef setup():\n    global FLAG\n    FLAG = True\nsetup()\n" + T,
        H + "FLAG = True\ndef setup():\n    global FLAG\n    FLAG = False\nsetup()\n" + T,
    )
    case(
        "global write in uncalled-by-name fixture autouse",
        H + "FLAG = True\n@pytest.fixture(autouse=True)\ndef f():\n    global FLAG\n    FLAG = True\n" + T,
        H + "FLAG = True\n@pytest.fixture(autouse=True)\ndef f():\n    global FLAG\n    FLAG = False\n" + T,
    )
    # star import
    case("star import changed", H + "from x import *\n" + T, H + "from y import *\n" + T)
    case("star import module dependencies (names)", H + "from x import *\n" + T, H + "from x import *\nimport z\n" + T)
    # decorator factory
    case(
        "decorator factory body changed",
        H + "def req(c):\n    return pytest.mark.skipif(c, reason='r')\n@req(True)\ndef test_x():\n    assert 1\n",
        H + "def req(c):\n    return pytest.mark.skipif(False, reason='r')\n@req(True)\ndef test_x():\n    assert 1\n",
    )
    case(
        "decorator factory non-skip-looking changed",
        H + "def req(c):\n    return lambda f: f\n@req(True)\ndef test_x():\n    assert 1\n",
        H + "def req(c):\n    return pytest.mark.skip('x')\n@req(True)\ndef test_x():\n    assert 1\n",
    )
    # string condition referencing module globals
    S1 = "@pytest.mark.skipif('FLAG', reason='r')\ndef test_x():\n    assert 1\n"
    case("string cond global FLAG changed", H + "FLAG = True\n" + S1, H + "FLAG = False\n" + S1)
    S2 = "@pytest.mark.skipif('sys.platform == \"darwin\" and FLAG', reason='r')\ndef test_x():\n    assert 1\n"
    case("string cond 2 global FLAG changed", H + "FLAG = True\n" + S2, H + "FLAG = False\n" + S2)
    case(
        "string cond imports changed (sys)",
        H + "FLAG = True\n" + S2,
        H.replace("import os, sys", "import os") + "import sys as other\nFLAG = True\n" + S2,
    )
    case(
        "string cond helper function changed",
        H + "def h():\n    return True\n" + "@pytest.mark.skipif('h()', reason='r')\ndef test_x():\n    assert 1\n",
        H + "def h():\n    return False\n" + "@pytest.mark.skipif('h()', reason='r')\ndef test_x():\n    assert 1\n",
    )
    # class attr via self in body guard
    C = lambda v: (
        H
        + f"class TestK:\n    FLAG = {v}\n    def test_x(self):\n        if self.FLAG:\n            pytest.skip('r')\n        assert 1\n"
    )
    case("class attr via self changed", C("True"), C("False"), "TestK.test_x")
    C2 = lambda v: (
        H
        + f"class Base:\n    FLAG = {v}\nclass TestK(Base):\n    def test_x(self):\n        if self.FLAG:\n            pytest.skip('r')\n        assert 1\n"
    )
    case("base class attr changed", C2("True"), C2("False"), "TestK.test_x")
    C3 = lambda v: (
        H
        + f"class Base:\n    def need(self):\n        return {v}\nclass TestK(Base):\n    def test_x(self):\n        if self.need():\n            pytest.skip('r')\n        assert 1\n"
    )
    case("base class method changed", C3("True"), C3("False"), "TestK.test_x")
    C4 = lambda v: (
        H
        + f"class TestK:\n    FLAG = True\n    def test_x(self):\n        if self.FLAG:\n            pytest.skip('r')\n        assert 1\n    def setup_method(self):\n        self.FLAG = {v}\n"
    )
    case("setup_method rebinding self.FLAG", C4("True"), C4("False"), "TestK.test_x")
    C5 = lambda v: (
        H
        + f"class TestK:\n    FLAG = True\n    @pytest.fixture(autouse=True)\n    def f(self):\n        self.FLAG = {v}\n    @pytest.mark.skipif(FLAG, reason='r')\n    def test_x(self):\n        assert 1\n"
    )
    case("autouse fixture method self.FLAG", C5("True"), C5("False"), "TestK.test_x")
    # fixture overridden later in file
    F = lambda extra: (
        H + "@pytest.fixture\ndef res():\n    pytest.skip('r')\n" + extra + "def test_x(res):\n    assert 1\n"
    )
    case("fixture overridden later same name", F(""), F("@pytest.fixture\ndef res():\n    return 1\n"))
    case("fixture overridden via name=", F(""), F("@pytest.fixture(name='res')\ndef other():\n    return 1\n"))
    # getfixturevalue
    G = lambda body: (
        H
        + "@pytest.fixture\ndef res():\n"
        + body
        + "\ndef test_x(request):\n    request.getfixturevalue('res')\n    assert 1\n"
    )
    case("getfixturevalue fixture changed", G("    pytest.skip('r')\n"), G("    return 1\n"))
    G2 = lambda body: (
        H
        + "@pytest.fixture\ndef res():\n"
        + body
        + "\ndef test_x(request):\n    request.getfixturevalue('res')\n    assert 1\n"
    )
    case(
        "getfixturevalue fixture skip cond changed",
        G2("    if os.environ.get('A'):\n        pytest.skip('r')\n"),
        G2("    if os.environ.get('B'):\n        pytest.skip('r')\n"),
    )
    # parametrize marks
    P = lambda c: (
        H
        + f"@pytest.mark.parametrize('a', [pytest.param(1, marks=pytest.mark.skipif({c}, reason='r')), 2])\ndef test_x(a):\n    assert a\n"
    )
    case("param marks cond changed", P("True"), P("False"))
    P2 = lambda c: (
        H
        + f"FLAG={c}\n@pytest.mark.parametrize('a', [pytest.param(1, marks=pytest.mark.skipif(FLAG, reason='r')), 2])\ndef test_x(a):\n    assert a\n"
    )
    case("param marks flag changed", P2("True"), P2("False"))
    # __getattr__
    M = lambda v: (
        H
        + f"def __getattr__(name):\n    return {v}\n"
        + "@pytest.mark.skipif(FLAGX, reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("module __getattr__", M("True"), M("False"))

    # depth
    def chain(n, last, flag_dec=True):
        s = H
        s += f"V0 = {last}\n"
        for i in range(1, n):
            s += f"V{i} = V{i - 1}\n"
        s += f"@pytest.mark.skipif(V{n - 1}, reason='r')\ndef test_x():\n    assert 1\n"
        return s

    for n in (5, 19, 20, 21, 25):
        case(f"chain {n} last changed", chain(n, "True"), chain(n, "False"))
        case(f"chain {n} unchanged", chain(n, "True"), chain(n, "True"))
    # name both global and local
    L = lambda v: (
        H
        + f"FLAG = {v}\ndef helper():\n    FLAG = True\n    return FLAG\n@pytest.mark.skipif(helper(), reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("local shadow: global FLAG changed but helper uses local", L("True"), L("False"))
    L2 = lambda v: (
        H
        + f"def helper(FLAG={v}):\n    return FLAG\n@pytest.mark.skipif(helper(), reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("default arg changed", L2("True"), L2("False"))


def _t2() -> None:
    H = "import os, sys, unittest\nimport pytest\n\n"
    # fixture via getfixturevalue, fixture doesn't skip directly but calls helper
    G = lambda c: (
        H
        + "def need(c):\n    if c:\n        pytest.skip('r')\n@pytest.fixture\ndef res():\n    need("
        + c
        + ")\ndef test_x(request):\n    request.getfixturevalue('res')\n    assert 1\n"
    )
    case("getfixturevalue; fixture calls need(c), c changed", G("True"), G("False"))
    # module pytestmark usefixtures
    U = lambda c: (
        H
        + "def need(c):\n    if c:\n        pytest.skip('r')\n@pytest.fixture\ndef res():\n    need("
        + c
        + ")\npytestmark = pytest.mark.usefixtures('res')\ndef test_x():\n    assert 1\n"
    )
    case("module pytestmark usefixtures; fixture calls need(c)", U("True"), U("False"))
    U2 = lambda c: (
        H
        + "def need(c):\n    if c:\n        pytest.skip('r')\n@pytest.fixture\ndef res():\n    need("
        + c
        + ")\n@pytest.mark.usefixtures('res')\ndef test_x():\n    assert 1\n"
    )
    case("decorator usefixtures; fixture calls need(c)", U2("True"), U2("False"))
    U3 = lambda c: (
        H
        + "def need(c):\n    if c:\n        pytest.skip('r')\n@pytest.fixture\ndef res():\n    need("
        + c
        + ")\ndef test_x(res):\n    assert 1\n"
    )
    case("param fixture calls need(c)", U3("True"), U3("False"))
    # class using usefixtures via pytestmark inside class
    U4 = lambda c: (
        H
        + "def need(c):\n    if c:\n        pytest.skip('r')\n@pytest.fixture\ndef res():\n    need("
        + c
        + ")\nclass TestK:\n    pytestmark = pytest.mark.usefixtures('res')\n    def test_x(self):\n        assert 1\n"
    )
    case("class pytestmark usefixtures", U4("True"), U4("False"), "TestK.test_x")
    # method a calls self.b (skips) ; a changed
    M = lambda body: (
        H
        + "class TestK:\n    def b(self):\n        pytest.skip('r')\n    def a(self):\n        "
        + body
        + "\n    def test_x(self):\n        self.a()\n        assert 1\n"
    )
    case(
        "method a (non-skip-looking) calls self.b; a changed",
        M("self.b()"),
        M("if os.environ.get('Q'): self.b()"),
        "TestK.test_x",
    )
    M2 = lambda body: (
        H
        + "def b():\n    pytest.skip('r')\nclass TestK:\n    def a(self):\n        "
        + body
        + "\n    def test_x(self):\n        self.a()\n        assert 1\n"
    )
    case("method a calls module b(); a changed", M2("b()"), M2("if os.environ.get('Q'): b()"), "TestK.test_x")
    # skip spellings
    for nm, stmt in [
        ("self.skipTest", "self.skipTest('r')"),
        ("raise unittest.SkipTest(call)", "raise unittest.SkipTest('r')"),
        ("pytest.importorskip", "pytest.importorskip('zzz')"),
        ("request.applymarker", "request.applymarker(pytest.mark.skip)"),
    ]:
        K = lambda c: (
            H
            + "class TestK(unittest.TestCase):\n    def test_x(self, request=None):\n        if "
            + c
            + ":\n            "
            + stmt
            + "\n        assert 1\n"
        )
        case(nm + " guard cond changed", K("os.environ.get('A')"), K("os.environ.get('B')"), "TestK.test_x")
    # unittest setUp with skipTest conditional on flag
    SU = lambda v: (
        H
        + "FLAG = "
        + v
        + "\nclass TestK(unittest.TestCase):\n    def setUp(self):\n        if FLAG:\n            self.skipTest('r')\n    def test_x(self):\n        assert 1\n"
    )
    case("setUp skipTest FLAG changed", SU("True"), SU("False"), "TestK.test_x")
    # unittest.skipIf decorator string? flag
    UI = lambda v: (
        H
        + "FLAG = "
        + v
        + "\nclass TestK(unittest.TestCase):\n    @unittest.skipIf(FLAG, 'r')\n    def test_x(self):\n        assert 1\n"
    )
    case("unittest.skipIf FLAG changed", UI("True"), UI("False"), "TestK.test_x")
    # module-level conditional def
    CD = lambda v: (
        H
        + "FLAG = "
        + v
        + "\nif FLAG:\n    def test_x():\n        pytest.skip('r')\nelse:\n    def test_x():\n        assert 1\n"
    )
    case("conditionally defined test", CD("True"), CD("False"))
    # try/except ImportError guard
    TI = lambda mod: (
        H
        + "try:\n    import "
        + mod
        + "\n    HAVE = True\nexcept ImportError:\n    HAVE = False\n@pytest.mark.skipif(not HAVE, reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("try import module changed", TI("foo"), TI("bar"))
    # walrus / comprehension / lambda
    W = lambda v: (
        H + "FLAG = " + v + "\n@pytest.mark.skipif((lambda: FLAG)(), reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("lambda FLAG", W("True"), W("False"))
    # del / augassign
    A = lambda v: H + "FLAG = True\n" + v + "\n@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
    case("FLAG &= later", A(""), A("FLAG &= False"))
    case("del FLAG? via globals().update", A(""), A("globals().update(FLAG=False)"))
    case("setattr(sys.modules[__name__])", A(""), A("setattr(sys.modules[__name__], 'FLAG', False)"))
    case("FLAG from loop var", A("for FLAG in [False]: pass"), A("for FLAG in [True]: pass"))
    case("FLAG via with-as", A("with open('x') as FLAG: pass"), A("with open('y') as FLAG: pass"))
    case("FLAG via walrus top-level", A("(FLAG := False)"), A("(FLAG := True)"))
    case(
        "FLAG via except-as",
        A("try:\n    pass\nexcept Exception as FLAG:\n    pass"),
        A("try:\n    pass\nexcept ValueError as FLAG:\n    pass"),
    )
    case("FLAG tuple unpack", A("FLAG, _x = (False, 1)"), A("FLAG, _x = (True, 1)"))
    case("FLAG via match", A("match 1:\n    case FLAG:\n        pass"), A("match 2:\n    case FLAG:\n        pass"))
    case("FLAG via import-in-func-global", A(""), A("def _f():\n    global FLAG\n    FLAG = False\n_f()"))
    case("FLAG via class def of same name later", A(""), A("class FLAG:\n    pass"))
    case(
        "FLAG assigned in nested if inside for",
        A("for _i in [1]:\n    if _i:\n        FLAG = False"),
        A("for _i in [1]:\n    if _i:\n        FLAG = True"),
    )
    case("exec dynamic", A(""), A("exec('FLAG = False')"))
    # decorator order / functools.wraps sensitive
    D = lambda v: (
        H
        + "def deco(f):\n    return pytest.mark.skipif("
        + v
        + ", reason='r')(f)\n@deco\ndef test_x():\n    assert 1\n"
    )
    case("plain decorator deco changed", D("True"), D("False"))


def _t3() -> None:
    H = "import os, sys, unittest\nimport pytest\n\n"
    # class attr of same name hides module binding
    CS = lambda v: (
        H
        + f"FLAG = {v}\nclass TestK:\n    FLAG = True\n    def test_x(self):\n        if FLAG:\n            pytest.skip('r')\n        assert 1\n"
    )
    case("class attr FLAG shadows module FLAG used in method body", CS("True"), CS("False"), "TestK.test_x")
    CS2 = lambda v: (
        H
        + f"FLAG = {v}\nclass TestK:\n    FLAG = True\n    @pytest.mark.skipif(FLAG, reason='r')\n    def test_x(self):\n        assert 1\n"
    )
    case(
        "(control) class-level decorator reads class FLAG; module FLAG changed",
        CS2("True"),
        CS2("False"),
        "TestK.test_x",
    )
    # module mutation statements
    MM = lambda s: (
        H
        + "class Cfg:\n    enabled = True\ncfg = Cfg()\n"
        + s
        + "\n@pytest.mark.skipif(cfg.enabled, reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("module-level cfg.enabled = False added", MM(""), MM("cfg.enabled = True"))
    MM2 = lambda s: (
        H + s + "\n@pytest.mark.skipif(os.environ.get('MODE') != 'full', reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("module-level os.environ['MODE']='lite' added", MM2(""), MM2("os.environ['MODE'] = 'lite'"))
    case("module-level os.environ.setdefault added", MM2(""), MM2("os.environ.setdefault('MODE', 'lite')"))
    case("module-level sys.platform monkeypatch", MM2(""), MM2("sys.platform = 'linux'"))
    MM3 = lambda s: (
        H + "ITEMS = []\n" + s + "\n@pytest.mark.skipif(not ITEMS, reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("ITEMS.append added at module level", MM3(""), MM3("ITEMS.append(1)"))
    MM4 = lambda s: H + "FLAG = True\n" + s + "\n@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
    case("del FLAG", MM4(""), MM4("del FLAG"))
    case("import star after", MM4(""), MM4("from other import *"))
    case("explicit import of FLAG after", MM4(""), MM4("from other import FLAG"))
    # mutate via function call at module level: setup() mutates FLAG in dict
    DD = lambda v: (
        H
        + f"CONF = {{'skip': True}}\ndef setup():\n    CONF['skip'] = {v}\nsetup()\n"
        + "@pytest.mark.skipif(CONF['skip'], reason='r')\ndef test_x():\n    assert 1\n"
    )
    case("function mutates dict; called at module level", DD("True"), DD("False"))
    # test body helper with mutation
    # conftest-ish: pytest_collection_modifyitems in file
    PC = lambda c: (
        H
        + "def pytest_collection_modifyitems(items):\n    for i in items:\n        if "
        + c
        + ":\n            i.add_marker(pytest.mark.skip)\ndef test_x():\n    assert 1\n"
    )
    case("hook pytest_collection_modifyitems cond changed", PC("'x' in i.name"), PC("'y' in i.name"))
    # nonlocal: inner function def in test body skip
    IN = lambda c: (
        H
        + "def test_x():\n    def inner():\n        if "
        + c
        + ":\n            pytest.skip('r')\n    inner()\n    assert 1\n"
    )
    case("nested def skips", IN("True"), IN("False"))
    IN2 = lambda c: (
        H
        + "def test_x():\n    def check():\n        return "
        + c
        + "\n    if check():\n        pytest.skip('r')\n    assert 1\n"
    )
    case("nested def check changed", IN2("True"), IN2("False"))
    # parametrize ids/values that determine skip
    PP = lambda v: (
        H
        + "def test_x(a):\n    if a == 1:\n        pytest.skip('r')\nparam = pytest.mark.parametrize('a', ["
        + v
        + "])\n"
    )
    PP2 = lambda v: (
        H + "@pytest.mark.parametrize('a', [" + v + "])\ndef test_x(a):\n    if a == 1:\n        pytest.skip('r')\n"
    )
    case("parametrize values changed (skip when a==1)", PP2("1, 2"), PP2("1, 3"))
    # test_x skip depends on another test via order/state
    ST = lambda v: (
        H
        + "STATE = {'n': "
        + v
        + "}\ndef test_a():\n    STATE['n'] = 0\ndef test_x():\n    if STATE['n'] == 0:\n        pytest.skip('r')\n"
    )
    case("depends on state set by other test changed", ST("1"), ST("1").replace("STATE['n'] = 0", "STATE['n'] = 5"))
    # test_x in class; class-level decorator on class from enclosing
    CL = lambda c: H + f"@pytest.mark.skipif({c}, reason='r')\nclass TestK:\n    def test_x(self):\n        assert 1\n"
    case("class decorator cond changed", CL("True"), CL("False"), "TestK.test_x")
    # metaclass / base using mixin skip
    MX = lambda c: (
        H
        + f"class Mixin:\n    def setup_method(self):\n        if {c}:\n            pytest.skip('r')\nclass TestK(Mixin):\n    def test_x(self):\n        assert 1\n"
    )
    case("mixin setup_method cond changed", MX("True"), MX("False"), "TestK.test_x")
    # class defined in head with second base added
    BB = lambda b: (
        H
        + "class A:\n    pass\nclass B:\n    def setup_method(self):\n        pytest.skip('r')\nclass TestK("
        + b
        + "):\n    def test_x(self):\n        assert 1\n"
    )
    case("bases changed A -> B", BB("A, B"), BB("B"), "TestK.test_x")


_t1()
_t2()
_t3()

# The cases that still hold, and why. The first three are controls: the base and the head are the same text. The last
# one is the residual the design states (run-time state another test sets): a test BODY after the skip changed, which is
# a place the unit may change by (e), and only run-time state links it to the skip of another test.
STILL_HOLD = {
    "chain 5 unchanged",
    "chain 19 unchanged",
    "chain 20 unchanged",
    "depends on state set by other test changed",
}


@pytest.mark.parametrize(("name", "base", "head", "q"), CASES, ids=[c[0] for c in CASES])
def test_every_review_case_that_changes_why_a_test_skips_is_not_a_hold(name, base, head, q):
    assert holds(base, head, q) is (name in STILL_HOLD)


def test_the_review_cases_are_all_there():
    assert len(CASES) == len({c[0] for c in CASES}) == 86  # a name twice would hide a case behind another


# --- what stays a hold: the shape of the real case and the other places the unit may change -------------------------

REAL = """\
import os

import pytest

INTEGRATION = pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason="needs the stack")


class _Reply:
    def json(self):
        return {"ok": 1}


@INTEGRATION
def test_a():
    result = 1 + 1
    assert result == 2


@INTEGRATION
def test_b():
    reply = _Reply()
    assert reply.json()


@INTEGRATION
def test_c():
    assert os.sep


def test_plain():
    assert True
"""


def real_head() -> str:
    head = REAL.replace("import os\n\nimport pytest", "import json\nimport os\n\nimport pytest")
    head = head.replace("    assert result == 2\n", "    assert result == 2, 'sum'\n    # checked twice\n")
    head = head.replace("    reply = _Reply()\n", "    reply = _Reply()\n    # the reply is a stub\n")
    return head + "\n\ndef test_new():\n    assert json.dumps(1) == '1'\n"


@pytest.mark.parametrize("q", ["test_a", "test_b", "test_c"])
def test_the_real_case_stays_a_hold(q):
    # a changed assertion, a comment inside two bodies, `import json` (a new name; `reply.json()` is an attribute and
    # `_Reply.json` a method, neither binds it in the module) and a new test at the end
    assert holds(REAL, real_head(), q)


def test_the_real_case_stays_a_hold_through_the_evidence_path(make_repo, raw, git_for):
    repo = make_repo("real")
    (repo / "tests").mkdir()
    (repo / "tests/test_live.py").write_text(REAL)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / "tests/test_live.py").write_text(real_head())
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "head")
    head = raw(repo, "rev-parse", "HEAD").strip()
    ids = tuple(f"tests.test_live::test_{n}" for n in "abc")
    asked = []

    def lookup() -> BaseSkips:
        asked.append(1)
        return BaseSkips(frozenset(ids), STEP1_SOURCE)

    found = skip_predating(git_for(repo), base, head, ["tests/test_live.py"], ids, CFG, ["tests/test_live.py"], lookup)
    assert found.ids == frozenset(ids) and asked == [1]


def edited(old: str, new: str, source: str = REAL) -> str:
    assert old in source
    return source.replace(old, new, 1)


STAY = {
    "a comment-only change at module level": edited("import pytest\n", "import pytest\n\n# the stack tests\n"),
    "a comment above a decorator": edited("@INTEGRATION\ndef test_c", "# c\n@INTEGRATION\ndef test_c"),
    "a blank line added between functions": edited("\n\n@INTEGRATION\ndef test_c", "\n\n\n@INTEGRATION\ndef test_c"),
    "a blank line removed between functions": edited("\n\n\ndef test_plain", "\n\ndef test_plain"),
    "a trailing comment on a line": edited("    assert os.sep\n", "    assert os.sep  # the separator\n"),
    "a changed body of a test that is not skipped": edited("    assert True\n", "    assert 1 + 1 == 2\n"),
    "a changed body of another skipped test": edited("    assert reply.json()\n", "    assert reply.json() == {}\n"),
    "a changed decorator of another test": edited("@INTEGRATION\ndef test_b", "@pytest.mark.slow\ndef test_b"),
    "another test removed whole": edited("\n\ndef test_plain():\n    assert True\n", ""),
    "a test of the base renamed": edited("def test_plain", "def test_renamed"),
    "a statement after the body's last skip": edited("    assert result == 2\n", "    assert result == 3\n    x = 1\n"),
    "a new import of two new names": edited("import os\n", "import os\nfrom json import dumps, loads\n"),
    "a new plain import": edited("import os\n", "import os\nimport json\n"),
    "a new import with an alias": edited("import os\n", "import os\nimport json as jsn\n"),
    "a new dotted import": edited("import os\n", "import os\nimport xml.dom\n"),
    "a new relative import": edited("import os\n", "import os\nfrom . import helpers\n"),
}


@pytest.mark.parametrize("head", STAY.values(), ids=list(STAY))
def test_these_changes_stay_a_hold(head):
    assert holds(REAL, head, "test_a")


CLS = """\
import os

import pytest


class TestK:
    FLAG = 1

    def helper(self):
        return 1

    @pytest.mark.skipif(os.getenv("S") != "1", reason="r")
    def test_x(self):
        assert self.FLAG

    def test_other(self):
        assert self.helper()
"""


def test_a_whole_new_test_method_in_a_test_class_stays_a_hold():
    assert holds(CLS, CLS + "\n    def test_y(self):\n        assert 1\n", "TestK.test_x")


def test_a_changed_body_of_another_method_stays_a_hold():
    assert holds(CLS, edited("assert self.helper()", "assert self.helper() == 2", CLS), "TestK.test_x")


def test_the_body_of_the_candidate_after_its_last_skip_may_change():
    base = "import os\nimport pytest\n\n\ndef test_x():\n    if not os.environ.get('S'):\n        pytest.skip('r')\n    assert 1\n"
    assert holds(base, edited("assert 1", "assert 2\n    assert 3", base))
    assert holds(base, edited("    if not", "    # first, the stack\n    if not", base))  # a comment is no statement


GUARD = "import os\nimport pytest\n\n\ndef test_x(tmp_path):\n    x = 1\n    if not os.environ.get('S'):\n        pytest.skip('r')\n    assert 1\n"
MARK = "import os\nimport pytest\n\n\n@pytest.mark.skipif(os.getenv('S') != '1', reason='r')\ndef test_x(tmp_path):\n    assert 1\n"

# --- what stops being a hold ------------------------------------------------------------------------------------------

NEGATIVE = {
    "an import that rebinds a name of the base": (REAL, edited("import os\n", "import os\nimport os.path as os\n")),
    "an import that binds a name the base loads": (REAL, edited("import os\n", "import os\nimport _Reply\n")),
    "an import of a builtin name": (REAL, edited("import os\n", "import os\nfrom x import len\n")),
    "an import of a name pytest gives a condition": (REAL, edited("import os\n", "import os\nimport platform\n")),
    "a star import added": (REAL, edited("import os\n", "import os\nfrom x import *\n")),
    "a future import added": (REAL, edited("import os\n", "import os\nfrom __future__ import annotations\n")),
    "an import removed": (REAL, edited("import os\n", "")),
    "an import changed": (REAL, edited("import os\n", "import os as o\n")),
    "an import and a statement on one line": (REAL, edited("import os\n", "import os\nimport json; X = 1\n")),
    "an import inside a block": (REAL, edited("import os\n", "import os\nif True:\n    import json\n")),
    "an import of a name twice": (REAL, edited("import os\n", "import os\nimport json\nimport json\n")),
    "a module-level statement added": (REAL, edited("import os\n", "import os\nLIMIT = 3\n")),
    "a module-level statement removed": (
        REAL,
        edited(
            'INTEGRATION = pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason="needs the stack")\n\n\n',
            "",
        ),
    ),
    "a module-level statement changed": (REAL, edited('!= "true"', '== "true"')),
    "a module-level statement only reformatted": (REAL, edited('!= "true"', '!= ("true")')),
    "a module docstring changed": ('"""The stack tests."""\n' + REAL, '"""The stack tests, more."""\n' + REAL),
    "a module docstring added": (REAL, '"""The stack tests."""\n' + REAL),
    "a helper class changed": (REAL, edited('return {"ok": 1}', 'return {"ok": 2}')),
    "a decorator of the candidate changed": (
        REAL,
        edited("@INTEGRATION\ndef test_a", "@pytest.mark.slow\n@INTEGRATION\ndef test_a"),
    ),
    "the candidate's body before its skip": (GUARD, edited("x = 1", "x = 2", GUARD)),
    "the candidate's guard": (GUARD, edited("not os.environ", "os.environ", GUARD)),
    "the candidate's skip call": (GUARD, edited("pytest.skip('r')", "pytest.skip('s')", GUARD)),
    "the candidate's signature": (MARK, edited("(tmp_path)", "()", MARK)),
    "the candidate's signature gained a parameter": (MARK, edited("(tmp_path)", "(tmp_path, monkeypatch)", MARK)),
    "the candidate's default": (MARK, edited("(tmp_path)", "(tmp_path, a=1)", MARK)),
    "the candidate's skip marker": (MARK, edited("!= '1'", "== '1'", MARK)),
    "a module statement added after the candidate": (MARK, MARK + "\nX = 1\n"),
    "a second definition of the candidate": (MARK, MARK + "\n\ndef test_x():\n    assert 2\n"),
    "a test whose name the base binds": (
        REAL + "\ntest_data = [1]\n",
        REAL + "\ntest_data = [1]\n\n\ndef test_data():\n    assert 1\n",
    ),
    "a test that became a fixture": (REAL, edited("def test_plain", "@pytest.fixture\ndef test_plain")),
    "a fixture that became a test": (
        REAL + "\n\n@pytest.fixture\ndef test_data():\n    return 1\n",
        REAL + "\n\ndef test_data():\n    return 1\n",
    ),
}


@pytest.mark.parametrize(("base", "head"), NEGATIVE.values(), ids=list(NEGATIVE))
def test_these_changes_are_not_a_hold(base, head):
    q = "test_x" if base in (GUARD, MARK) else "test_a"
    assert not holds(base, head, q)


def test_a_new_test_named_like_an_attribute_the_base_reads_is_not_a_hold():
    base = edited("    assert os.sep\n", "    assert os.sep\n    assert os.test_flag\n")
    assert not holds(base, base + "\n\ndef test_flag():\n    assert 1\n", "test_a")
    assert holds(base, base + "\n\ndef test_flags():\n    assert 1\n", "test_a")


def test_a_changed_class_level_attribute_is_not_a_hold():
    assert not holds(CLS, edited("FLAG = 1", "FLAG = 0", CLS), "TestK.test_x")


def test_a_changed_setup_method_is_not_a_hold():
    base = edited("    def helper", "    def setup_method(self):\n        self.FLAG = 1\n\n    def helper", CLS)
    assert not holds(base, edited("self.FLAG = 1", "self.FLAG = 0", base), "TestK.test_x")
    assert not holds(CLS, base, "TestK.test_x")  # added


def test_a_changed_helper_method_of_the_class_is_not_a_hold():
    assert not holds(CLS, edited("return 1", "return 2", CLS), "TestK.test_x")


def test_a_changed_fixture_is_not_a_hold():
    base = "import pytest\n\n\n@pytest.fixture\ndef res():\n    return 1\n\n\n@pytest.mark.skip\ndef test_x(res):\n    assert res\n"
    assert not holds(base, edited("return 1", "return 2", base))
    assert holds(base, edited("assert res", "assert res == 1", base))


def test_a_changed_class_decorator_or_base_is_not_a_hold():
    base = edited("class TestK:", "@pytest.mark.slow\nclass TestK:", CLS)
    assert not holds(base, edited("@pytest.mark.slow", "@pytest.mark.fast", base), "TestK.test_x")
    assert not holds(CLS, edited("class TestK:", "class TestK(object):", CLS), "TestK.test_x")


def test_a_new_test_class_is_not_a_hold():
    assert not holds(CLS, CLS + "\n\nclass TestNew:\n    def test_z(self):\n        assert 1\n", "TestK.test_x")


def test_a_blank_line_inside_a_string_is_not_a_blank_line():
    base = 'import pytest\n\nDOC = """a\n\nb"""\n\n\n@pytest.mark.skip\ndef test_x():\n    assert 1\n'
    assert not holds(base, base.replace("a\n\nb", "a\n\n\nb"))
    assert holds(base, base.replace("assert 1", "# note\n    assert 1"))


def test_a_def_line_removed_so_its_body_joins_the_helper_before_it_is_not_a_hold():
    base = (
        "import pytest\n\n\ndef setup_module():\n    pass\n\n\ndef test_y():\n    assert 2\n\n\n"
        "@pytest.mark.skip\ndef test_x():\n    assert 1\n"
    )
    assert not holds(base, base.replace("def test_y():\n", ""))


def test_a_string_opened_in_a_test_body_that_swallows_a_fixture_is_not_a_hold():
    base = (
        "import pytest\n\n\ndef test_y():\n    assert 2\n\n\n@pytest.fixture\ndef res():\n    return 1\n\n\n"
        '@pytest.mark.skip\ndef test_x():\n    assert 1\n\n\nDOC = """"""\n'
    )
    head = base.replace("    assert 2\n", '    x = """\n', 1).replace('DOC = """"""', 'DOC = """"""\n"""')
    assert not holds(base, head)


def test_a_def_inserted_in_the_middle_of_a_helper_is_not_a_hold():
    base = (
        "import pytest\n\n\ndef helper():\n    a = 1\n    b = 2\n\n\n@pytest.mark.skip\ndef test_x():\n    assert 1\n"
    )
    assert not holds(base, base.replace("    b = 2\n", "def test_new():\n    b = 2\n"))


def test_a_source_that_does_not_parse_or_a_test_that_is_gone_is_not_a_hold():
    assert not holds(MARK, MARK + "\ndef (:\n")
    assert not holds(MARK, MARK.replace("test_x", "test_z"))
    assert not holds(MARK + "\ndef (:\n", MARK)


def test_a_changed_coding_cookie_is_not_a_hold():
    base = "# -*- coding: utf-8 -*-\n" + MARK
    assert not holds(base, base.replace("utf-8", "latin-1"))
    assert holds(base, base.replace("assert 1", "assert 2"))


def test_the_line_endings_of_the_unit_do_not_matter():
    assert holds(MARK, MARK.replace("\n", "\r\n").replace("assert 1", "assert 2"))
    assert holds(MARK, MARK.replace("assert 1", "assert 1\x0c"))  # a form feed ends no line for the tokenizer


def test_a_file_of_many_tests_is_decided_in_seconds():
    import time

    def source(k: int) -> str:
        lines = ["import os", "import pytest", "", "STACK = os.getenv('STACK') == 'true'", ""]
        for i in range(600):
            lines.append(
                f"@pytest.mark.skipif(not STACK, reason='stack')\ndef test_t{i}():\n    x = {i}\n"
                f"    assert x == {k + i % 20}\n    assert [y for y in range(10)]\n"
            )
        return "\n".join(lines)

    started = time.monotonic()
    rule = SkipRule(source(0), source(1), [], CFG)
    assert all(rule.no_skip_added(f"test_t{i}") for i in range(600))
    assert time.monotonic() - started < 10


# --- rule (c): the files that change how the tests run, wherever they are ---------------------------------------------

OUTSIDE = [
    "sitecustomize.py", "usercustomize.py", "noxfile.py", "requirements.txt", "requirements-dev.txt",
    "requirements_test.txt", "constraints.txt", "constraints-py311.txt", "Pipfile", "Pipfile.lock", "poetry.lock",
    "uv.lock", "pdm.lock", "setup.py",
]  # fmt: skip


@pytest.mark.parametrize("name", OUTSIDE)
@pytest.mark.parametrize("where", ["", "services/api/", "tests/"])
def test_a_changed_file_that_changes_how_the_tests_run_is_not_a_hold(name, where):
    assert not holds(MARK, MARK.replace("assert 1", "assert 2"), changed=(f"{where}{name}",))


@pytest.mark.parametrize("name", ["README.md", "requirements.md", "notes.txt", "setup_data.py", "docs/uv.lock.md"])
def test_other_files_do_not_matter(name):
    assert holds(MARK, MARK.replace("assert 1", "assert 2"), changed=(name,))


@pytest.fixture
def support_repo(make_repo, raw, git_for) -> Callable[..., set[str]]:
    """`go(other_base, other_head)`: commit the base and the head of `tests/test_live.py` (an edit of the assertion
    under an unchanged skip) with the other files given, ask `skip_predating` about `test_x`; the base report says it
    was skipped. The ids that predate the unit come back."""
    counter = itertools.count()

    def go(other_base: dict[str, str], other_head: dict[str, str]) -> set[str]:
        repo = make_repo(f"support{next(counter)}")
        live = "tests/test_live.py"
        shas = []
        readme = {"README.md": "hello\n"}
        for files in (
            {live: MARK, **readme, **other_base},
            {live: MARK.replace("assert 1", "assert 2"), **readme, **other_head},
        ):
            for old in raw(repo, "ls-files").split():
                if old not in files:
                    (repo / old).unlink()
            for rel, body in files.items():
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(body)
            raw(repo, "add", "-A")
            raw(repo, "commit", "-q", "--allow-empty", "-m", "state")
            shas.append(raw(repo, "rev-parse", "HEAD").strip())
        tree = raw(repo, "ls-tree", "-r", "--name-only", shas[1]).split()
        ids = ("tests.test_live::test_x",)

        def lookup() -> BaseSkips:
            return BaseSkips(frozenset(ids), STEP1_SOURCE)

        return set(skip_predating(git_for(repo), shas[0], shas[1], [live], ids, CFG, tree, lookup).ids)

    return go


def test_a_support_module_of_the_tests_tree_that_changed_is_not_a_hold(support_repo):
    assert support_repo({"tests/util.py": "X = 1\n"}, {"tests/util.py": "X = 2\n"}) == set()
    assert support_repo({}, {"tests/util.py": "X = 2\n"}) == set()  # added
    assert support_repo({"tests/util.py": "X = 1\n"}, {}) == set()  # deleted
    assert support_repo({"tests/__init__.py": ""}, {"tests/__init__.py": "import os\n"}) == set()
    assert support_repo({}, {"tests/pkg/__init__.py": ""}) == set()  # a new package marker


def test_a_support_module_that_was_renamed_away_is_not_a_hold(support_repo):
    assert support_repo({"tests/util.py": "X = 1\n"}, {"tests/util2.py": "X = 1\n"}) == set()


def test_another_test_file_that_changed_is_not_a_support_module(support_repo):
    other = "def test_other():\n    assert 1\n"
    assert support_repo(
        {"tests/test_other.py": other}, {"tests/test_other.py": other + "\n\ndef test_z():\n    pass\n"}
    ) == {"tests.test_live::test_x"}


def test_a_python_file_outside_the_tests_tree_is_no_support_module(support_repo):
    assert support_repo({"src/util.py": "X = 1\n"}, {"src/util.py": "X = 2\n"}) == {"tests.test_live::test_x"}
    assert support_repo({"tools/util.py": "X = 1\n"}, {"tools/util.py": "X = 2\n"}) == {"tests.test_live::test_x"}


def test_the_control_without_another_changed_file_is_a_hold(support_repo):
    assert support_repo({}, {}) == {"tests.test_live::test_x"}


def test_a_candidate_whose_place_among_the_statements_moved_is_not_a_hold():
    base = "import pytest\n\nX = 1\n\n\n@pytest.mark.skip\ndef test_x():\n    assert 1\n"
    head = "import pytest\n\n\n@pytest.mark.skip\ndef test_x():\n    assert 1\n\n\nX = 1\n"
    assert not holds(base, head)


# --- a test that the not-free parts of the file can reach is not free (review of rework 9) -------------------------


def _check(value: str, call: str = "'test_check()'") -> str:
    return (
        f"import os\nimport pytest\n\n\ndef test_check():\n    return {value}\n\n\n"
        f"@pytest.mark.skipif({call}, reason='r')\ndef test_x():\n    assert 1\n"
    )


@pytest.mark.parametrize("call", ["'test_check()'", "test_check()", "'test_check() or False'"])
def test_a_test_that_a_skip_condition_calls_or_names_is_not_free(call):
    """The name of a collected test in a string condition or a decorator is a read of it: its body decides the skip."""
    assert not holds(_check("not os.environ.get('S')", call), _check("True", call))
    assert holds(
        _check("not os.environ.get('S')", call), _check("not os.environ.get('S')", call).replace("assert 1", "assert 2")
    )


def test_a_test_method_that_the_prefix_of_the_test_calls_is_not_free():
    def source(value: str) -> str:
        return (
            "import pytest\n\n\nclass TestK:\n    def test_helper(self):\n        return " + value + "\n\n"
            "    def test_x(self):\n        if self.test_helper():\n            pytest.skip('r')\n        assert 1\n"
        )

    assert not holds(source("True"), source("False"), "TestK.test_x")
    assert holds(source("True"), source("True").replace("assert 1", "assert 2"), "TestK.test_x")


def test_a_test_that_a_helper_of_the_file_calls_is_not_free():
    def source(value: str) -> str:
        return (
            "import pytest\n\n\ndef test_check():\n    return "
            + value
            + "\n\n\ndef need():\n    return test_check()\n\n\n"
            "@pytest.mark.skipif(need(), reason='r')\ndef test_x():\n    assert 1\n"
        )

    assert not holds(source("True"), source("False"))


def _fixtures(name: str) -> str:
    return (
        "import pytest\n\n\n@pytest.fixture\ndef res():\n    pytest.skip('r')\n\n\n@pytest.fixture\ndef other():\n"
        f"    pytest.skip('r')\n\n\ndef test_x(request):\n    request.getfixturevalue('{name}')\n    assert 1\n"
    )


def test_a_fixture_the_body_runs_by_name_is_part_of_what_skips_the_test():
    """`request.getfixturevalue('res')` is a skip the prefix of `skipdeps` does not read (the fixture is named by a
    string): the statement is not free, so naming another fixture keeps the finding. An assertion after it is free."""
    assert not holds(_fixtures("res"), _fixtures("other"))
    assert holds(_fixtures("res"), _fixtures("res").replace("assert 1", "assert 2"))


def test_import_time_code_of_another_tests_decorator_or_default_is_the_residual():
    """Not told apart, by design (RESIDUALS: run-time state that another test sets): the decorators and the defaults of
    a test that is not asked about are free, and they run when the module is imported. A hold, and a person who accepts
    it has been told so in the question."""
    base = (
        "import pytest\n\nITEMS = []\n\n\n@pytest.mark.skipif(not ITEMS, reason='r')\ndef test_x():\n    assert 1\n\n\n"
        "def test_y(a=None):\n    assert a is None\n"
    )
    assert holds(base, base.replace("def test_y(a=None)", "def test_y(a=ITEMS.append(1))"))
    assert holds(base, base.replace("def test_y", "@pytest.mark.parametrize('b', [ITEMS.append(1)])\ndef test_y"))
