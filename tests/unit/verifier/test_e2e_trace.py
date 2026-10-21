from l4.gates.junit import TestCase, TestReport
from l4.specs.base import Criterion, Framework
from l4.specs.criteria import criterion_id
from l4.verifier.e2e_trace import e2e_coverage, trace_e2e


def criterion(requirement: str, scenario: str, capability: str = "cart-page") -> Criterion:
    return Criterion(
        id=criterion_id("openspec", capability, requirement, scenario),
        alias=f"{capability} › {requirement} › {scenario}",
        framework=Framework.OPENSPEC, capability=capability, requirement=requirement, scenario=scenario,
        text="WHEN x THEN y", source_path=f"specs/{capability}/spec.md", source_line=1,
    )  # fmt: skip


COUNT = criterion("Item count", "Demo cart")  # the live protocol's show-item-count criterion
SUBTOTAL, THIRD, FOURTH = criterion("Subtotal", "one"), criterion("Subtotal", "two"), criterion("Subtotal", "three")
ALL = [COUNT, SUBTOTAL, THIRD, FOURTH]


def report(*ids: str, skipped: tuple[str, ...] = ()) -> TestReport:
    tests = {i: TestCase(i, "passed") for i in ids} | {i: TestCase(i, "skipped") for i in skipped}
    return TestReport(tests)


def hexof(c: Criterion) -> str:
    return c.id.split("-", 1)[1]


def test_the_live_protocol_criterion_id_is_the_one_the_plan_computed():
    assert COUNT.id == "C-de7f2d3f"


def test_generated_file_name_traces_its_criterion():
    generated = f"e2e.test_l4_c_{hexof(COUNT)}::test_badge_shows_the_count"
    assert trace_e2e(ALL, report(generated)) == [SUBTOTAL, THIRD, FOURTH]
    assert e2e_coverage(ALL, report(generated)) == {COUNT.id: [generated]}


def test_the_three_spellings_in_any_case_all_trace():
    h = hexof(COUNT)
    for spelling in (f"c_{h}", f"C_{h}", f"C-{h}", f"c-{h.upper()}", f"c_{h}".upper()):
        assert COUNT.id not in [c.id for c in trace_e2e([COUNT], report(f"e2e.test_{spelling}::t"))], spelling
    assert trace_e2e([COUNT], report(f"e2e.test_x::{h}")) == [COUNT]  # the bare hex is not a reference
    assert trace_e2e([COUNT], report(f"e2e.test_abc_{h}::t")) == [COUNT]  # the c belongs to a longer word
    assert trace_e2e([COUNT], report(f"e2e.test_c_{h}0::t")) == [COUNT]  # nine hex digits are another id


def test_a_skipped_test_traces_nothing():
    assert trace_e2e([COUNT], report(skipped=(f"e2e.test_l4_c_{hexof(COUNT)}::t",))) == [COUNT]


def test_a_test_tracing_too_many_criteria_counts_for_none():
    many = "e2e.test_" + "_".join(f"c_{hexof(c)}" for c in ALL) + "::t"  # four criteria, the default maximum is three
    assert trace_e2e(ALL, report(many)) == ALL
    assert trace_e2e(ALL, report(many), max_criteria_per_test=4) == []
    three = "e2e.test_" + "_".join(f"c_{hexof(c)}" for c in ALL[:3]) + "::t"
    assert trace_e2e(ALL, report(three)) == [FOURTH]


def test_a_unit_test_never_covers_and_no_report_covers_nothing():
    assert trace_e2e(ALL, None) == ALL
    assert trace_e2e(ALL, TestReport()) == ALL
    assert trace_e2e(ALL, report("tests.test_cart::test_shows_count")) == ALL


def test_an_unknown_criterion_hex_is_not_a_trace():
    assert trace_e2e([COUNT], report("e2e.test_l4_c_00000000::t")) == [COUNT]
