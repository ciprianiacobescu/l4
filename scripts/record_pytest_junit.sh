#!/usr/bin/env bash
# Re-record tests/fixtures/recorded/pytest/{trace,failure-kinds}-xunit{1,2}.xml with the installed pytest (M13-G1).
# A recording conftest appends ("l4", id) to item.user_properties the way the l4_trace plugin does, so the files show
# whether <properties> reach each testcase in both junit families. Usage: scripts/record_pytest_junit.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/tests/fixtures/recorded/pytest"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/tests"

cat > "$work/conftest.py" <<'PY'
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "l4(*ids): criterion ids")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        for mark in item.iter_markers("l4"):
            for cid in mark.args:
                item.user_properties.append(("l4", cid))
PY

cat > "$work/tests/test_trace.py" <<'PY'
import pytest


@pytest.mark.l4("C-aaaaaaaa", "C-bbbbbbbb")
def test_two_ids():
    assert True


@pytest.mark.l4("C-aaaaaaaa")
def test_failing_with_id():
    assert 1 == 2


@pytest.mark.l4("C-cccccccc")
@pytest.mark.parametrize("n", [1, 2])
def test_param(n):
    assert n == 1


def test_untagged():
    assert True


class TestGroup:
    @pytest.mark.l4("C-dddddddd")
    def test_in_class(self):
        assert True
PY

cat > "$work/tests/test_kinds.py" <<'PY'
import pytest


def stub():
    raise NotImplementedError


def wrong_signature(a):
    return a


class Thing:
    pass


def test_assert():
    assert [1, 2] == [1, 3]


def test_assert_message():
    assert 1 == 2, "values differ"


def test_raises_did_not_raise():
    with pytest.raises(ValueError):
        pass


def test_not_implemented():
    stub()


def test_not_implemented_with_text():
    raise NotImplementedError("later")


def test_type_error():
    wrong_signature(1, extra=2)


def test_attribute_error():
    Thing().missing


def test_value_error():
    raise ValueError("boom")


def test_explicit_fail():
    pytest.fail("explicit")
PY

for family in xunit1 xunit2; do
  for name in trace kinds; do
    (cd "$work" && uv run --project "$root" python -m pytest -q -p no:cacheprovider -o "junit_family=$family" \
      --junitxml="$work/$name-$family.xml" "tests/test_$name.py" >/dev/null || true)
    target="failure-kinds"; [ "$name" = trace ] && target="trace"
    sed -e "s#$work#/PATH#g" -e 's/time="[0-9.]*"/time="0.001"/g' -e 's/timestamp="[^"]*"/timestamp="T"/g' \
        -e 's/hostname="[^"]*"/hostname="host"/g' "$work/$name-$family.xml" > "$out/$target-$family.xml"
  done
done
uv run --project "$root" python -c "import pytest; print('recorded with pytest', pytest.__version__)" | tee "$out/PYTEST_VERSION"
