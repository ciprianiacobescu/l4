"""Live wave D, W-D2: cheap static checks on an audit test before it reaches the judge or a question. The fixtures are
the shape of the real failures of a weak verifier agent (a module attribute that does not exist, `python -m` on a
module with no `__main__` guard, a forgotten import), with synthetic content."""

import pytest

from l4.agents.base import Usage
from l4.llm.agent_judge import StructuredResult
from l4.verifier.testwriter import TEMPLATE_VERSION, build_writer_prompt, request_test

from .test_testwriter import ID, Scripted

DEMO = "def build_demo(path):\n    return path\n\n\nSIZE = 3\n"
CLI = "import sys\n\n\ndef run(argv):\n    return 0\n"
CLI_GUARDED = CLI + '\n\nif __name__ == "__main__":\n    sys.exit(run(sys.argv[1:]))\n'
PKG_MAIN = "from widgetry.cli import run\n\nrun([])\n"


def blocks(cli: str = CLI, *extra: tuple[str, str]):
    return [("src/widgetry/demo.py", DEMO), ("src/widgetry/cli.py", cli), ("src/widgetry/__init__.py", ""), *extra]


def ask(code: str, sources=None):
    result = StructuredResult(
        "ok", parsed={"criterion": ID, "code": code}, usage=Usage(cost_usd=0.0), model_resolved="m"
    )
    return request_test(
        Scripted(result), kind="audit", criterion_id=ID, criterion_text="c",
        data_blocks=sources if sources is not None else blocks(),
    )  # fmt: skip


# --- (a) names called as module attributes ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "header, call",
    [
        ("from widgetry import demo", "demo.make_widget"),
        ("import widgetry.demo as demo", "demo.make_widget"),
        ("import widgetry.demo", "widgetry.demo.make_widget"),
        ("import widgetry\nimport widgetry.demo", "widgetry.demo.make_widget"),
        ("from widgetry import demo as d", "d.make_widget"),
    ],
)
def test_a_call_of_a_module_attribute_the_shown_source_does_not_bind_is_invalid(header, call):
    reply = ask(f"{header}\n\n\ndef test_x():\n    assert {call}(3)\n")
    assert reply.status == "invalid" and "`make_widget` is not defined in `src/widgetry/demo.py`" in reply.detail
    assert "build_demo" in reply.detail  # what the file does define


def test_a_plain_import_of_a_top_level_shown_module_is_checked_too():
    sources = [("demo.py", DEMO)]
    bad = ask("import demo\n\n\ndef test_x():\n    assert demo.make_widget()\n", sources)
    assert bad.status == "invalid" and "`make_widget` is not defined in `demo.py`" in bad.detail
    assert ask("import demo\n\n\ndef test_x():\n    assert demo.build_demo(1) and demo.SIZE\n", sources).status == "ok"


def test_defined_attributes_a_dunder_a_submodule_and_a_shadowing_local_are_not_flagged():
    assert ask("import widgetry.demo\n\n\ndef test_x():\n    assert widgetry.demo.build_demo(1)\n").status == "ok"
    assert ask("from widgetry import demo\n\n\ndef test_x():\n    assert demo.__name__\n").status == "ok"
    shadow = "from widgetry import demo\n\n\ndef test_x():\n    demo = object()\n    assert demo.anything\n"
    assert ask(shadow).status == "ok"


# --- (b) python -m <module> --------------------------------------------------------------------------------------


def test_python_dash_m_of_a_shown_module_without_a_main_guard_is_invalid():
    code = (
        "import subprocess\nimport sys\n\n\ndef test_x(tmp_path):\n"
        "    done = subprocess.run([sys.executable, '-m', 'widgetry.cli', str(tmp_path)], capture_output=True)\n"
        "    assert done.stdout\n"
    )
    reply = ask(code)
    assert reply.status == "invalid" and "python -m widgetry.cli" in reply.detail and "__main__" in reply.detail


def test_python_dash_m_in_a_command_string_is_checked_too():
    code = (
        "import subprocess\n\n\ndef test_x():\n"
        "    done = subprocess.run('python -m widgetry.cli --list', shell=True, capture_output=True)\n"
        "    assert done.stdout\n"
    )
    assert ask(code).status == "invalid"


def test_python_dash_m_is_allowed_with_a_guard_a_package_main_or_an_unshown_module():
    code = (
        "import subprocess\nimport sys\n\n\ndef test_x():\n"
        "    done = subprocess.run([sys.executable, '-m', '{mod}'], capture_output=True)\n    assert done.stdout\n"
    )
    assert ask(code.format(mod="widgetry.cli"), blocks(CLI_GUARDED)).status == "ok"
    assert ask(code.format(mod="widgetry"), blocks(CLI, ("src/widgetry/__main__.py", PKG_MAIN))).status == "ok"
    assert ask(code.format(mod="pytest")).status == "ok"  # not a shown source: nothing is known, nothing is checked
    assert ask(code.format(mod="widgetry.other")).status == "ok"


def test_python_dash_m_of_a_module_whose_package_has_a_main_but_not_the_module_itself_is_invalid():
    code = "import subprocess\n\n\ndef test_x():\n    subprocess.run(['python3', '-m', 'widgetry.cli'])\n"
    assert ask(code, blocks(CLI, ("src/widgetry/__main__.py", PKG_MAIN))).status == "invalid"


# --- (c) names the file never imports or defines -----------------------------------------------------------------


def test_a_name_the_test_never_imports_or_defines_is_invalid():
    code = (
        "from widgetry.demo import build_demo\n\n\ndef test_x():\n"
        "    t = threading.Thread(target=build_demo, args=(1,))\n    t.start()\n"
    )
    reply = ask(code)
    assert reply.status == "invalid" and "`threading`" in reply.detail and "import" in reply.detail


def test_bound_names_of_every_kind_and_the_builtins_are_not_undefined():
    code = (
        "import os.path\nfrom widgetry.demo import build_demo as bd\n\n\nclass Box:\n    size = 1\n\n\n"
        "def helper(a, *rest, key=None, **kw):\n    return [x for x in rest if (y := x)] + [a, key, kw, y]\n\n\n"
        "def test_x(tmp_path, monkeypatch):\n    try:\n        raise ValueError\n    except ValueError as err:\n"
        "        assert str(err) == '' and len(helper(1)) and bd(1) and os.path.sep and Box.size\n"
        "    with open(tmp_path / 'a', 'w') as fh:\n        fh.write('x')\n    for i in range(2):\n        print(i)\n"
    )
    assert ask(code).status == "ok"


def test_a_star_import_makes_the_names_unknowable_so_nothing_is_flagged():
    assert ask("from widgetry.demo import *\n\n\ndef test_x():\n    assert build_demo(1)\n").status == "ok"


def test_the_e2e_kind_is_not_bound_by_these_rules():
    result = StructuredResult(
        "ok", parsed={"criterion": ID, "code": "def test_x():\n    assert nothing_defined\n"}, usage=Usage(cost_usd=0.0)
    )
    reply = request_test(Scripted(result), kind="e2e", criterion_id=ID, criterion_text="c", data_blocks=blocks())
    assert reply.status == "ok"


def test_the_audit_rules_v5_state_the_three_rules():
    system, _ = build_writer_prompt("audit", ID, "c", [])
    assert TEMPLATE_VERSION == 5
    assert "python -m" in system and "__main__" in system and "Import every module" in system


def test_an_attribute_of_a_package_whose_init_is_shown_is_not_flagged_it_may_be_a_submodule():
    sources = [("src/widgetry/__init__.py", "VERSION = 1\n"), *blocks()[:2]]
    code = "import widgetry\nimport widgetry.unchanged\n\n\ndef test_x():\n    assert widgetry.unchanged.go()\n"
    assert ask(code, sources).status == "ok"


# --- adversarial review of the v5 checks: a constant name reached by reflection, names bound at run time, -----------
# --- annotations, a module that runs at its top level, the collection error of one file ----------------------------


@pytest.mark.parametrize(
    "header, call",
    [
        ("from widgetry import demo", "getattr(demo, 'make_widget')"),
        ("import widgetry.demo", "getattr(widgetry.demo, 'make_widget')"),
        ("import importlib", "importlib.import_module('widgetry.demo').make_widget"),
        ("import importlib as il", "il.import_module('widgetry.demo').make_widget"),
        ("from importlib import import_module", "import_module('widgetry.demo').make_widget"),
        ("import importlib\n\nmod = importlib.import_module('widgetry.demo')", "mod.make_widget"),
        ("import importlib", "getattr(importlib.import_module('widgetry.demo'), 'make_widget')"),
    ],
)
def test_a_missing_name_reached_through_getattr_or_import_module_with_a_constant_is_invalid(header, call):
    reply = ask(f"{header}\n\n\ndef test_x():\n    assert {call}(3)\n")
    assert reply.status == "invalid" and "`make_widget` is not defined in `src/widgetry/demo.py`" in reply.detail


@pytest.mark.parametrize(
    "code",
    [
        "from widgetry import demo\n\n\ndef test_x():\n    assert getattr(demo, 'make_widget', None) is None\n",
        "from widgetry import demo\n\n\ndef test_x():\n    assert getattr(demo, 'build_demo')(1)\n",
        "import importlib\n\n\ndef test_x():\n    assert importlib.import_module('widgetry.demo').build_demo(1)\n",
        "import importlib\n\nmod = importlib.import_module('widgetry.demo')\n\n\n"
        "def test_x(mod):\n    assert mod.other\n",
        "import importlib\n\n\ndef test_x():\n    assert importlib.import_module('widgetry.unshown').anything\n",
    ],
)
def test_getattr_with_a_default_a_defined_name_a_rebound_or_an_unshown_module_is_not_flagged(code):
    assert ask(code).status == "ok"


@pytest.mark.parametrize(
    "source",
    [
        "def init():\n    global CACHE\n    CACHE = {}\n",
        "for _n in ('a', 'b'):\n    globals()['CACHE'] = {}\n",
        "import sys\n\nsetattr(sys.modules[__name__], 'CACHE', {})\n",
        "import sys\n\nsys.modules[__name__].CACHE = {}\n",
        "for CACHE in [{}]:\n    pass\n",
        "with open(__file__) as CACHE:\n    pass\n",
    ],
)
@pytest.mark.parametrize("header", ["from widgetry import state", "import widgetry.state as state"])
def test_a_module_name_bound_at_run_time_is_not_flagged(source, header):
    sources = [("src/widgetry/state.py", source), *blocks()]
    code = f"{header}\n\n\ndef test_x():\n    assert state.CACHE is not None\n"
    assert ask(code, sources).status == "ok"
    plain = [("src/widgetry/state.py", "OTHER = 1\n"), *blocks()]
    assert ask(code, plain).status == "invalid"  # the same test against a module that binds no CACHE


DASH_M_CLI = (
    "import subprocess\nimport sys\n\n\ndef test_x():\n    subprocess.run([sys.executable, '-m', 'widgetry.cli'])\n"
)


@pytest.mark.parametrize(
    "cli",
    [
        CLI + "\n\nraise SystemExit(run(sys.argv[1:]))\n",
        CLI + "\n\nrun(sys.argv[1:])\n",
        CLI + '\n\nif __name__ == "__main__" and len(sys.argv) > 0:\n    sys.exit(run(sys.argv[1:]))\n',
        CLI + '\n\nif "__main__" == __name__:\n    sys.exit(run(sys.argv[1:]))\n',
    ],
)
def test_python_dash_m_of_a_module_that_runs_at_its_top_level_or_has_a_compound_guard_is_allowed(cli):
    code = DASH_M_CLI
    assert ask(code, blocks(cli)).status == "ok"


def test_the_dash_m_reason_says_the_module_calls_nothing_at_its_top_level():
    code = DASH_M_CLI
    reply = ask(code)
    assert reply.status == "invalid" and "calls nothing at its top level" in reply.detail


@pytest.mark.parametrize(
    "code",
    [
        "from __future__ import annotations\n\n\ndef test_x(tmp_path: Path) -> None:\n    assert tmp_path\n",
        "def test_x(tmp_path):\n    found: Path = tmp_path\n    assert found\n",
    ],
)
def test_a_name_used_only_in_an_annotation_is_not_flagged(code):
    """An annotation is often never evaluated (a local one, or any under `from __future__ import annotations`); one
    that is evaluated fails at import, which the collection retry already catches."""
    assert ask(code).status == "ok"


def test_a_name_in_an_annotation_and_in_the_body_is_still_flagged():
    reply = ask("def test_x(tmp_path: Path):\n    assert Path(tmp_path)\n")
    assert reply.status == "invalid" and "`Path`" in reply.detail


def test_a_name_imported_from_a_package_whose_init_is_shown_may_be_an_unshown_submodule_and_is_not_flagged():
    """Only the unit's changed files are shown: `from pkg import mod` of a package is not knowable (a missing one fails
    at import, which the collection retry catches)."""
    assert ask("from widgetry import unchanged\n\n\ndef test_x():\n    assert unchanged.go()\n").status == "ok"
    missing = "from widgetry.demo import make_widget\n\n\ndef test_x():\n    assert make_widget()\n"
    assert ask(missing).status == "invalid"
