from pathlib import Path

import pytest

from l4.clarifier.answer import Citation
from l4.clarifier.router import resolve_citation

DESIGN = (
    "\n".join(f"line {n}" for n in range(1, 11))
    + "\nThe tax rate is\nstored in basis points.\n"
    + "\n".join(f"tail {n}" for n in range(1, 6))
)  # "The tax rate is" is line 11, "stored in basis points." line 12


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    unit = repo / "openspec" / "changes" / "add-x"
    unit.mkdir(parents=True)
    (unit / "design.md").write_text(DESIGN)
    (repo / "src").mkdir()
    code = "RATE_BP = 1900  # basis points\n\n\ndef vat(net):\n    return net * RATE_BP // 10000\n"
    (repo / "src" / "vat.py").write_text(code)
    return unit, repo


def check(roots, ref: str, quote: str):
    return resolve_citation(Citation(ref=ref, quote=quote, claim="c"), roots)


def test_unresolvable_citation_reason(roots):
    gone = check(roots, "design.md#L3", "the tax rate is stored in basis points")
    assert not gone.ok and gone.reason == "citation design.md#L3: quote not found within 2 lines of L3"
    assert "tax rate" not in gone.reason  # a quote can be a secret: reasons never echo it
    assert check(roots, "nope.md", "some quoted text").reason == "citation nope.md: file not found"


def test_a_line_number_may_be_off_by_two_but_not_three(roots):
    quote = "stored in basis points"  # line 12
    assert check(roots, "design.md#L12", quote).ok
    assert check(roots, "design.md#L10", quote).ok and check(roots, "design.md#L14", quote).ok
    assert not check(roots, "design.md#L9", quote).ok and not check(roots, "design.md#L15", quote).ok
    both = "The tax rate is stored in basis points."  # lines 11-12: all of it must be inside the window
    assert check(roots, "design.md#L11", both).ok and check(roots, "design.md#L10", both).ok
    assert not check(roots, "design.md#L9", both).ok


def test_a_range_is_widened_by_the_same_tolerance(roots):
    assert check(roots, "design.md#L11-L12", "stored in basis points").ok
    assert check(roots, "design.md#L13-L14", "stored in basis points").ok  # two lines off
    assert not check(roots, "design.md#L1-L5", "stored in basis points").ok


def test_without_a_line_the_quote_may_be_anywhere_in_the_file(roots):
    found = check(roots, "design.md", "  stored   in\n basis points. ")
    assert found.ok and "stored in basis points." in found.cited_text
    assert not check(roots, "design.md", "never written in this file").ok


def test_cited_text_is_the_quoted_lines_with_context(roots):
    found = check(roots, "design.md#L12", "basis points")
    assert found.ok and found.cited_text.splitlines()[0] == "line 10" and "tail 1" in found.cited_text


def test_repository_files_are_found_after_the_unit_directory(roots):
    assert check(roots, "src/vat.py#L5", "net * RATE_BP // 10000").ok
    assert check(roots, "openspec/changes/add-x/design.md#L11", "The tax rate is").ok


@pytest.mark.parametrize(
    "ref",
    ["/etc/passwd", "../../../outside.md", "src/../../outside.md", "C:\\x.md", "src\\vat.py", "", "#L3", "a\x00b",
     "design.md#L0", "design.md#L5-L3", "design.md#x3", "design.md#L3#L4"],
)  # fmt: skip
def test_refusals_never_read_outside(roots, tmp_path, ref):
    (tmp_path / "outside.md").write_text("quoted text here")
    out = check(roots, ref, "quoted text here")
    assert not out.ok and out.reason.startswith("citation ")


def test_symlinks_are_not_followed(roots, tmp_path):
    unit, repo = roots
    (tmp_path / "secret.md").write_text("quoted secret text")
    (unit / "link.md").symlink_to(tmp_path / "secret.md")
    (repo / "linkdir").symlink_to(tmp_path)
    assert not check(roots, "link.md", "quoted secret text").ok
    assert not check(roots, "linkdir/secret.md", "quoted secret text").ok


def test_short_quotes_and_big_files_do_not_count(roots):
    assert check(roots, "design.md", "line 1").reason == "citation design.md: quote shorter than 8 characters"
    unit, _ = roots
    (unit / "big.md").write_text("x" * 2_000_000)
    assert check(roots, "big.md", "xxxxxxxxxxxx").reason == "citation big.md: file is not a regular file under 1 MiB"


# --- Router.route: the five conditions of L4-CLR-002 -----------------------------------------------------------------

from l4.clarifier.answer import ClarifierAnswer  # noqa: E402
from l4.clarifier.ports import QuestionView  # noqa: E402
from l4.clarifier.router import AskJudge, Router, S1Query, S1Unavailable  # noqa: E402
from l4.config.schema import ClarifierCfg, S1Cfg  # noqa: E402
from l4.specs.questions import QuestionKind, QuestionStatus  # noqa: E402


class FakeS1(AskJudge):
    source = "llm_boolean"

    def __init__(self, *replies: float | Exception) -> None:
        self.replies, self.asked = list(replies), []

    def ask(self, query: S1Query) -> float:
        self.asked.append(query)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def view(kind: QuestionKind | None = QuestionKind.TECHNICAL) -> QuestionView:
    return QuestionView(
        id="Q-001", title="Which type?", status=QuestionStatus.OPEN, kind=kind, blocking=("1.1",),
        context="Prices are stored somewhere.", options=(), answer_text="", suggestion_text="", by=None,
    )  # fmt: skip


def answer(*, kind="technical", confidence="high", citations=(("src/vat.py#L1", "RATE_BP = 1900"),)) -> ClarifierAnswer:
    return ClarifierAnswer.model_validate(
        {
            "question_id": "Q-001", "answer": "Use basis points.", "confidence": confidence, "kind": kind,
            "citations": [{"ref": r, "quote": q, "claim": "c"} for r, q in citations], "rationale": "r",
        }
    )  # fmt: skip


def route(roots, s1, ans=None, v=None, *, cfg=None, s1_cfg=None):
    router = Router(cfg or ClarifierCfg(), s1_cfg or S1Cfg(), s1, roots)
    return router.route(v or view(), ans or answer())


def test_all_conditions_hold_auto_accepts_and_each_failure_blocks(roots):
    s1 = FakeS1(0.0, 1.0)
    ok_ = route(roots, s1)
    assert ok_.auto_accept and ok_.reasons == () and ok_.s1 == "llm_boolean"
    assert ok_.p_product == 0.0 and ok_.citation_support == (1.0,)
    assert s1.asked[0].instruction.startswith("Does answering this require")
    assert s1.asked[1].instruction == "Does `cited_text` support `answer`?" and "RATE_BP = 1900" in s1.asked[1].state

    # 1: the implementer's label, the clarifier's kind
    for v, a, text in (
        (view(QuestionKind.PRODUCT), answer(), "implementer kind product"),
        (view(None), answer(), "implementer kind"),
        (view(), answer(kind="ambiguous"), "clarifier kind ambiguous"),
    ):
        spy = FakeS1()
        blocked = route(roots, spy, a, v)
        assert not blocked.auto_accept and any(text in r for r in blocked.reasons)
        assert spy.asked == [] and blocked.s1 == "not_asked"  # a cheaper rule blocks: no S1 call
    # 2: confidence
    low = route(roots, FakeS1(), answer(confidence="medium"))
    assert not low.auto_accept and "confidence medium" in low.reasons[0]
    relaxed = ClarifierCfg(min_confidence="medium")
    assert route(roots, FakeS1(0.0, 1.0), answer(confidence="medium"), cfg=relaxed).auto_accept
    # 4a: no citation, an unresolved one; every failed reason is collected
    none = route(roots, FakeS1(), answer(citations=()))
    assert not none.auto_accept and "no citation" in none.reasons[0]
    bad = route(roots, FakeS1(), answer(kind="product", citations=(("nope.py", "does not exist here"),)))
    assert len(bad.reasons) == 2 and bad.citation_failures == ("citation nope.py: file not found",)
    # 3: the router says product, 4b: S1 does not see the support
    product = route(roots, FakeS1(0.5))
    assert not product.auto_accept and product.p_product == 0.5 and "p(technical)=0.50" in product.reasons[0]
    assert product.citation_support == ()  # no further call once the question is a product decision
    unsupported = route(roots, FakeS1(0.0, 0.0))
    assert not unsupported.auto_accept and unsupported.citation_support == (0.0,)
    assert "citation src/vat.py#L1" in unsupported.reasons[0]
    # 5: S1 unavailable, or switched off by the config
    gone = route(roots, FakeS1(S1Unavailable("usage limit")))
    assert not gone.auto_accept and gone.s1 == "unavailable" and gone.reasons == ("S1 unavailable: usage limit",)
    off = route(roots, FakeS1(), cfg=ClarifierCfg(s1_router=False))
    assert not off.auto_accept and off.s1 == "not_asked" and "s1_router" in off.reasons[0]


def test_a_ref_the_os_rejects_is_a_failed_citation_never_an_exception(roots):
    long_name = check(roots, "x" * 300 + ".py", "some quoted text")
    assert not long_name.ok and long_name.reason.endswith("file not found")
    deep = check(roots, "/".join(["d" * 200] * 40) + "/a.py", "some quoted text")
    assert not deep.ok and deep.reason.startswith("citation ")
    huge_line = check(roots, "design.md#L" + "9" * 4400, "some quoted text")
    assert not huge_line.ok and huge_line.reason.startswith("citation ")
    assert not check(roots, "a" * 600, "some quoted text").ok


def test_the_units_own_files_and_harness_output_are_no_evidence(roots):
    unit, repo = roots
    (unit / "questions.md").write_text("Should the VAT rate be 19 percent or 21 percent for Romania?\n")
    (unit / ".l4" / "ledger").mkdir(parents=True)
    (unit / ".l4" / "ledger" / "r.jsonl").write_text('{"note":"use 19 percent VAT for Romania"}\n')
    (repo / ".l4-out").mkdir()
    (repo / ".l4-out" / "r.md").write_text("use 19 percent VAT for Romania\n")
    for ref, quote in (
        ("questions.md", "Should the VAT rate be 19 percent"),
        ("openspec/changes/add-x/questions.md", "Should the VAT rate be 19 percent"),
        (".l4/ledger/r.jsonl", "use 19 percent VAT"),
        ("openspec/changes/add-x/.l4/ledger/r.jsonl", "use 19 percent VAT"),
        (".l4-out/r.md", "use 19 percent VAT"),
    ):
        assert check(roots, ref, quote).reason == f"citation {ref}: file not found"


def test_a_wide_range_a_newline_or_a_control_character_is_refused(roots):
    quote = "stored in basis points"  # line 12
    assert check(roots, "design.md#L1-L60", quote).ok  # 60 lines: the cap
    assert not check(roots, "design.md#L1-L100000", quote).ok
    assert not check(roots, "design.md#L1-L61", quote).ok
    assert not check(roots, "design.md#L12\n", quote).ok
    assert not check(roots, "design.md\n#L12", quote).ok
    assert not check(roots, "design.md\x1b[0m", quote).ok


@pytest.mark.parametrize("ref", [".", "./", "./.", ".#L1", ".#L1-L2", "././"])
def test_a_ref_without_a_file_name_is_refused_not_an_exception(roots, ref):
    found = check(roots, ref, "stored in basis points")
    assert not found.ok and found.reason == f"citation {ref}: the path must name a file"


def test_a_directory_symlink_to_harness_output_or_another_spelling_of_it_is_no_evidence(roots):
    unit, repo = roots
    (repo / ".l4" / "ledger").mkdir(parents=True)
    (repo / ".l4" / "ledger" / "r.jsonl").write_text('{"note":"use 19 percent VAT for Romania"}\n')
    (repo / "docs").symlink_to(repo / ".l4")
    (unit / "questions.md").write_text("Should the VAT rate be 19 percent or 21 percent for Romania?\n")
    for ref, quote in (
        ("docs/ledger/r.jsonl", "use 19 percent VAT"),
        (".L4/ledger/r.jsonl", "use 19 percent VAT"),
        ("openspec/changes/add-x/QUESTIONS.md", "Should the VAT rate be 19 percent"),
    ):
        assert check(roots, ref, quote).reason == f"citation {ref}: file not found"


GENERATED = (".venv", "node_modules", ".pytest_cache", "__pycache__", ".ruff_cache", ".mypy_cache", "dist", "build")


@pytest.mark.parametrize("directory", GENERATED)
def test_agent_writable_and_generated_directories_are_no_evidence(roots, directory):
    unit, repo = roots
    for where in (repo / directory, repo / "pkg" / directory.upper()):
        where.mkdir(parents=True)
        (where / "f.txt").write_text("use 19 percent VAT for Romania\n")
    for ref in (f"{directory}/f.txt", f"pkg/{directory.upper()}/f.txt"):
        assert check(roots, ref, "use 19 percent VAT").reason == f"citation {ref}: file not found"


def test_a_symlink_into_a_generated_directory_is_no_evidence(roots):
    unit, repo = roots
    (repo / ".venv").mkdir()
    (repo / ".venv" / "f.txt").write_text("use 19 percent VAT for Romania\n")
    (repo / "vendored").symlink_to(repo / ".venv")
    assert check(roots, "vendored/f.txt", "use 19 percent VAT").reason == "citation vendored/f.txt: file not found"


@pytest.mark.parametrize("p_product, accepted", [(0.1, True), (0.1000001, False), (0.0, True), (0.5, False)])
def test_the_router_threshold_is_inclusive_at_reject_threshold(roots, p_product, accepted):
    """L4-CLR-002 rule 3: p(product) <= verifier.s1.reject_threshold passes."""
    decision = route(roots, FakeS1(p_product, 1.0), s1_cfg=S1Cfg(reject_threshold=0.1))
    assert decision.auto_accept is accepted


@pytest.mark.parametrize("support, accepted", [(0.9, True), (0.8999999, False), (1.0, True), (0.5, False)])
def test_the_citation_threshold_is_inclusive_at_accept_threshold(roots, support, accepted):
    """L4-CLR-002 rule 4: p(the cited text supports the answer) >= verifier.s1.accept_threshold passes."""
    decision = route(roots, FakeS1(0.0, support), s1_cfg=S1Cfg(accept_threshold=0.9))
    assert decision.auto_accept is accepted


def test_every_citation_must_reach_accept_threshold_and_a_failed_router_stops_before_the_citations(roots):
    two = answer(citations=(("src/vat.py#L1", "RATE_BP = 1900"), ("design.md", "stored in basis points")))
    assert route(roots, FakeS1(0.0, 0.9, 0.9), two).auto_accept
    assert not route(roots, FakeS1(0.0, 0.9, 0.89), two).auto_accept
    s1 = FakeS1(0.11)
    assert not route(roots, s1).auto_accept and len(s1.asked) == 1


def test_an_llm_stand_in_gets_the_full_state_budget(roots):
    from dataclasses import replace

    from l4.clarifier.router import approx_tokens

    cap = 450
    s1 = FakeS1(0.0, 1.0)
    long_view = replace(view(), context="word " * 1000)
    route(roots, s1, v=long_view)
    used = approx_tokens(s1.asked[0].state + s1.asked[0].instruction)
    assert cap - 40 < used <= cap


# --- the System-One verdicts and their gates -----------------------------------------------------------------------


class VerdictS1:
    """A judge that speaks verdicts (the System-One shape), with the starting gates."""

    source = "system_one"
    question_set = "test@1"

    def __init__(self, technical=0.95, internal=0.9, support=0.95, opposite=0.05, cut=False, establishes=0.95):
        self.args = (technical, internal, support, opposite, cut, establishes)
        self.supports = 0

    def gates(self, limits):
        from l4.clarifier.router import Gates

        d = limits.decisions
        return Gates(
            d.router.technical_min, d.citation.support_min, d.router.internal_min, d.citation.opposite_max,
            d.citation.establishes_min,
        )

    def route(self, question, limits):
        from l4.clarifier.router import RouterVerdict

        return RouterVerdict(self.args[0], None, {"route_a": self.args[0]}, "jev-1.13.0")

    def support(self, answer, citation, cited_text, limits, *, question):
        from l4.clarifier.router import CitationVerdict

        self.supports += 1
        return CitationVerdict(
            self.args[2], self.args[3], self.args[4], {"shows": self.args[2]}, "jev-1.13.0",
            internal=self.args[1], establishes=self.args[5],
        )

    def close(self):
        pass


def test_system_one_verdicts_pass_at_the_starting_gates_and_are_recorded(roots):
    decision = route(roots, VerdictS1())
    assert decision.auto_accept and decision.s1 == "system_one" and decision.reasons == ()
    assert decision.p_product == pytest.approx(0.05) and decision.p_internal == 0.9
    assert decision.citation_support == (0.95,) and decision.citation_opposite == (0.05,)
    assert decision.s1_model == "jev-1.13.0" and decision.s1_questions == "test@1"
    assert decision.s1_detail == {"router.route_a": 0.95, "citation1.shows": 0.95}


@pytest.mark.parametrize(
    ("kwargs", "text"),
    [
        ({"technical": 0.84}, "p(technical)=0.84 is below 0.85"),
        ({"internal": 0.79}, "p(derivable from the project)=0.79 is below 0.80"),
        ({"support": 0.89}, "S1 support p=0.89 is below 0.90"),
        ({"opposite": 0.21}, "S1 opposite p=0.21 is above 0.20"),
        ({"establishes": 0.79}, "establishes the answer)=0.79 is below 0.80"),
    ],
)
def test_each_system_one_gate_blocks_just_past_its_threshold(roots, kwargs, text):
    decision = route(roots, VerdictS1(**kwargs))
    assert not decision.auto_accept and text in decision.reasons[0]


def test_the_gates_are_the_configured_values_and_the_edges_are_inclusive(roots):
    edge = S1Cfg.model_validate({"decisions": {
        "router": {"technical_min": 0.7, "internal_min": 0.6},
        "citation": {"support_min": 0.5, "opposite_max": 0.5, "establishes_min": 0.4}}})
    assert route(roots, VerdictS1(0.7, 0.6, 0.5, 0.5, establishes=0.4), s1_cfg=edge).auto_accept
    assert not route(roots, VerdictS1(0.69, 0.6, 0.5, 0.5, establishes=0.4), s1_cfg=edge).auto_accept


def test_a_failed_router_gate_skips_the_citation_calls(roots):
    s1 = VerdictS1(technical=0.3)
    assert not route(roots, s1).auto_accept and s1.supports == 0
