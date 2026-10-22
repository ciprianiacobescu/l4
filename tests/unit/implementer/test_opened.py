import pytest

from l4.config.schema import L4Config
from l4.implementer.opened import check_filled_helper, check_opened, unit_modules

CFG = L4Config()
MODS = frozenset({"app.otel"})

BEFORE = (
    "import os\n\nimport pytest\n\nos.environ['A'] = '1'\nVALUE = 2\n\n\n"
    "@pytest.fixture\ndef client():\n    return object()\n"
)


def run(after: str, *, before: str = BEFORE, named: bool = True, mods: frozenset[str] = MODS) -> str | None:
    return check_opened(before, after, named_by_task=named, unit_modules=mods)


def test_live_case_setdefault_between_old_statements_and_autouse_fixtures_pass() -> None:
    after = BEFORE.replace(
        "VALUE = 2\n",
        "os.environ.setdefault('APP_OTEL_ENABLED', 'false')\nVALUE = 2\n",
    ) + (
        "\n\n@pytest.fixture(autouse=True)\ndef _no_otel(monkeypatch):\n"
        "    monkeypatch.setenv('APP_OTEL_ENABLED', 'false')\n"
        "\n\n@pytest.fixture(autouse=True)\ndef _reset():\n"
        "    from app import telemetry\n\n    telemetry.reset_telemetry()\n"
    )
    assert run(after) is None


def test_unchanged_file_passes() -> None:
    assert run(BEFORE) is None


def test_changed_fixture_body_fails() -> None:
    why = run(BEFORE.replace("return object()", "return None"))
    assert why == "changes an existing statement"


def test_second_def_client_fails() -> None:
    assert run(BEFORE + "\n\ndef client():\n    return 1\n") == "rebinds client"


def test_removed_statement_fails() -> None:
    assert run(BEFORE.replace("VALUE = 2\n", "")) == "changes an existing statement"


def test_new_pytestmark_fails() -> None:
    assert run(BEFORE + "\npytestmark = pytest.mark.skip\n") == "rebinds pytestmark"


def test_new_module_hook_fails() -> None:
    assert run(BEFORE + "\n\ndef pytest_generate_tests(metafunc):\n    pass\n") == "rebinds pytest_generate_tests"


def test_does_not_parse() -> None:
    assert run("def (:\n") == "does not parse"
    assert run(BEFORE, before="def (:\n") == "does not parse"


def test_rules_one_and_two_apply_only_to_an_open_by_task_text() -> None:
    assert run(BEFORE.replace("return object()", "return None"), named=False) is None


FIX = "\n\ndef _f(monkeypatch, mocker):\n    {}\n"


@pytest.mark.parametrize(
    ("code", "target"),
    [
        ("monkeypatch.setattr('app.otel.enabled', lambda: False)", "app.otel.enabled"),
        ("monkeypatch.delattr('app.otel.enabled')", "app.otel.enabled"),
        ("mock.patch('app.otel.enabled')", "app.otel.enabled"),
        ("patch('app.otel.enabled')", "app.otel.enabled"),
        ("mocker.patch('app.otel.enabled')", "app.otel.enabled"),
        ("mocker.patch.object(o, 'enabled')", "app.otel.enabled"),
        ("patch.object(o, 'enabled', False)", "app.otel.enabled"),
        ("mock.patch.object(o, 'enabled')", "app.otel.enabled"),
        ("monkeypatch.setattr(o, 'enabled', False)", "app.otel.enabled"),
        ("setattr(o, 'enabled', False)", "app.otel.enabled"),
        ("o.enabled = False", "app.otel.enabled"),
        ("o.enabled += 1", "app.otel.enabled"),
        ("monkeypatch.setattr('app.otel.sub.fn', None)", "app.otel.sub.fn"),
    ],
)
def test_patch_forms_of_a_unit_module_fail(code: str, target: str) -> None:
    after = BEFORE + "\nimport app.otel as o\nfrom unittest import mock\nfrom unittest.mock import patch\n"
    after += FIX.format(code)
    assert run(after) == f"patches {target}, which the unit changed"


def test_import_forms_resolve_to_the_unit_module() -> None:
    for imp, code in [
        ("from app import otel", "otel.enabled = False"),
        ("import app.otel", "app.otel.enabled = False"),
        ("from app import otel as q", "monkeypatch.setattr(q, 'enabled', 1)"),
    ]:
        after = BEFORE + f"\n{imp}\n" + FIX.format(code)
        assert run(after, named=False) == "patches app.otel.enabled, which the unit changed", imp


def test_environment_clock_and_unchanged_modules_pass() -> None:
    body = (
        "monkeypatch.setenv('APP_OTEL_ENABLED', 'false')\n    os.environ['X'] = '1'\n"
        "    monkeypatch.setattr('time.time', lambda: 0)\n    monkeypatch.setattr('app.other.fn', None)\n"
        "    mocker.patch('app.otelx.fn')\n    o.read()\n    obj.enabled = 1\n"
    )
    after = BEFORE + "\nimport app.otel as o\n" + FIX.format(body)
    assert run(after) is None


def test_old_patch_is_not_new_code() -> None:
    before = BEFORE + "\n\ndef _old(monkeypatch):\n    monkeypatch.setattr('app.otel.enabled', None)\n"
    assert run(before + "\nW = 3\n", before=before, named=False) is None


def test_no_unit_modules_means_no_rule_three() -> None:
    after = BEFORE + FIX.format("monkeypatch.setattr('app.otel.enabled', None)")
    assert run(after, mods=frozenset()) is None


def test_unit_modules_dotted_names_under_roots_and_plain_packages() -> None:
    paths = [
        "src/app/otel.py",
        "src/app/__init__.py",
        "pkg/mod.py",
        "src/solo.py",
        "tests/test_x.py",
        "conftest.py",
        "README.md",
        "../evil.py",
    ]
    assert unit_modules(paths, CFG) == frozenset({"app.otel", "app", "pkg.mod", "solo"})


def test_environment_subscript_assignment_is_no_rebinding() -> None:
    assert run(BEFORE.replace("VALUE = 2\n", "VALUE = 2\nos.environ['APP_X'] = '1'\n")) is None
    assert run(BEFORE + "\nos.environ['APP_X'] = '1'\nos.environ.update(B='2')\n") is None


def test_attribute_assignment_does_not_bind_its_base() -> None:
    assert run(BEFORE + "\nclient.flag = True\nVALUE2 = 1\nos.sep = '/'\n") is None


def test_plain_name_target_still_rebinds() -> None:
    assert run(BEFORE + "\nos = None\n") == "rebinds os"
    assert run(BEFORE + "\nVALUE = 3\n") == "rebinds VALUE"
    assert run(BEFORE + "\n(a, os) = (1, 2)\n") == "rebinds os"
    assert run(BEFORE + "\nfor os in []:\n    pass\n") == "rebinds os"
    assert run(BEFORE + "\nwith open('x') as os:\n    pass\n") == "rebinds os"
    assert run(BEFORE + "\n(os := 1)\n") == "rebinds os"
    assert run(BEFORE + "\n_ = [os := 1 for _ in []]\n") == "rebinds os"
    assert run(BEFORE + "\n_ = [os for os in []]\n") is None  # a comprehension variable is local


def test_unit_module_assignment_still_refused() -> None:
    after = BEFORE + "\nimport app.otel\napp.otel.enabled = False\n"
    assert run(after) == "patches app.otel.enabled, which the unit changed"


PKG_BEFORE = "import app.a\n\nVALUE = 1\n"


def test_two_new_imports_of_one_package_are_no_rebinding() -> None:
    assert run(BEFORE + "\nimport app.a\nimport app.b\n") is None


def test_new_import_of_a_package_the_file_already_imports_passes() -> None:
    assert run(PKG_BEFORE + "import app.b\n", before=PKG_BEFORE) is None
    assert run(PKG_BEFORE.replace("VALUE", "import app.b\nVALUE"), before=PKG_BEFORE) is None


@pytest.mark.parametrize(
    "extra",
    [
        "import other as app\n",
        "app = 1\n",
        "def app():\n    pass\n",
        "from x import app\n",
        "import app.b as app\n",
        "import app as app\n",
    ],
)
def test_real_rebinding_of_an_imported_package_stays_refused(extra: str) -> None:
    assert run(PKG_BEFORE + extra, before=PKG_BEFORE) == "rebinds app"


@pytest.mark.parametrize(
    "first", ["import other as app\n", "app = 1\n", "from x import app\n", "def app():\n    pass\n"]
)
def test_import_after_a_non_import_binding_stays_refused(first: str) -> None:
    before = first + "VALUE = 1\n"
    assert run(before + "import app.b\n", before=before) == "rebinds app"


def test_new_import_after_a_new_non_import_binding_is_refused() -> None:
    assert run(BEFORE + "\napp = 1\nimport app.b\n") == "rebinds app"
    assert run(BEFORE + "\nimport app.a\napp = 1\n") == "rebinds app"


# --- named-tests 2.2: a helper red added is filled in (L4-IMP-083) ---

STUB = (
    "from dataclasses import dataclass\n\n\n"
    "class Store:\n    def get(self, key, default=None):\n        raise NotImplementedError\n\n\n"
    "def make_store(size: int = 3, *, name=None, **extra):\n    raise NotImplementedError\n\n\n"
    "async def load(path):\n    raise NotImplementedError\n"
)


def fill(after: str, *, mods: frozenset[str] = MODS) -> str | None:
    return check_filled_helper(STUB, after, unit_modules=mods)


def test_a_helper_may_have_its_bodies_filled_in_and_gain_helpers_and_new_statements() -> None:
    after = (
        STUB.replace("raise NotImplementedError\n\n\ndef make", "return default\n\n\ndef make", 1)
        .replace("size: int = 3", "size: str = 'x'")
        .replace("raise NotImplementedError\n\n\nasync", "return {}\n\n\nasync", 1)
        + "\n\nDEFAULT = 1\n\n\ndef extra_helper():\n    return DEFAULT\n"
    )
    assert fill(after) is None
    assert fill(STUB) is None


def test_a_dropped_function_class_or_coroutine_is_named() -> None:
    assert fill(STUB.replace("def make_store", "def build_store")) == "drops make_store"
    assert fill(STUB.replace("class Store", "class Shop")) == "drops Store"
    assert fill(STUB.replace("async def load", "def load")) == "changes the signature of load"
    assert fill(STUB.replace("class Store:", "def Store():\n    return 1\n\n\nclass Other:")) == (
        "changes the signature of Store"
    )


def test_a_changed_parameter_list_is_a_changed_signature() -> None:
    assert fill(STUB.replace("size: int = 3", "size: int")) == "changes the signature of make_store"
    assert fill(STUB.replace("size: int = 3", "count: int = 3")) == "changes the signature of make_store"
    assert fill(STUB.replace("*, name=None", "*, name=None, other=1")) == "changes the signature of make_store"
    assert fill(STUB.replace(", **extra", "")) == "changes the signature of make_store"


def test_a_test_added_to_a_helper_is_named() -> None:
    assert fill(STUB + "\n\ndef test_fake():\n    assert 1\n") == "adds a test test_fake"
    assert fill(STUB + "\n\nclass TestX:\n    def test_a(self):\n        assert 1\n") == "adds a test TestX.test_a"


def test_a_helper_that_patches_the_units_module_or_does_not_parse_is_refused() -> None:
    patching = STUB + "\n\nimport app.otel\n\napp.otel.enabled = True\n"
    assert fill(patching) == "patches app.otel.enabled, which the unit changed"
    assert fill("def broken(:\n") == "does not parse"
