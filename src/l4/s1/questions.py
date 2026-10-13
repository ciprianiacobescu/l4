"""The versioned question sets (M16-G7) and the one map from a Stage A label to a training label.

A set is asked as ONE request: the API evaluates every question of a request against the same state. Choice
questions come in both option orders as two question ids (eval-framework 6.3); the reversed ids are training
augmentation, and `canonical()` is what the calibration and test splits ask.
Everything here is plain data: no engine, no network, no import of the System-One backend.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FILE_RELEVANT = "l4/file-relevant@1"
CHANGE_COVERED = "l4/change-covered@1"
TESTS_OK = "l4/tests-ok@2"  # @2: a skipped test counts as not passed (the label follows the literal question)
CRITERION = "l4/criterion-satisfied@2"

# the step 8 question of verifier/s1.py; tests/unit/s1/test_questions.py pins the two to each other
CRITERION_QUESTION = "Does this evidence show that the criterion is satisfied?"
STATUS_OPTIONS = {
    "implemented": "the tests that trace the criterion pass and exercise what it asks",
    "not_implemented": "no passing test shows what the criterion asks",
    "contradicted": "a test or the code shows the opposite of what the criterion asks",
}


@dataclass(frozen=True)
class SetQuestion:
    id: str
    kind: str  # noul | choice | score
    instructions: str
    criteria: Any = None  # noul: {true, false}; choice: ordered option map; score: list of level descriptions
    reversed: bool = False  # a choice question asked with the options in the opposite order

    def wire(self) -> dict[str, Any]:
        body: dict[str, Any] = {"type": self.kind, "instructions": self.instructions}
        if self.criteria is not None:
            body["criteria"] = self.criteria
        return body


@dataclass(frozen=True)
class QuestionSet:
    name: str
    questions: tuple[SetQuestion, ...]
    class_question: str  # the question whose expected label is the row's class (balance cap)

    def wire(self, *, canonical_only: bool = False) -> dict[str, dict[str, Any]]:
        return {q.id: q.wire() for q in self.questions if not (canonical_only and q.reversed)}

    @property
    def sha256(self) -> str:
        """Over the canonical JSON of every question: any edit to a text, option or order changes it."""
        blob = json.dumps(self.wire(), sort_keys=False, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _truefalse(yes: str, no: str) -> dict[str, str]:
    return {"true": yes, "false": no}


def _reversed(options: Mapping[str, str]) -> dict[str, str]:
    return dict(reversed(list(options.items())))


SETS: dict[str, QuestionSet] = {
    s.name: s
    for s in (
        QuestionSet(
            FILE_RELEVANT,
            (
                SetQuestion(
                    "relevant", "noul", "Is the changed file part of the feature that the spec describes?",
                    _truefalse(
                        "the file implements, tests or configures what the spec asks for",
                        "the file belongs to another module or another concern that the spec does not mention",
                    ),
                ),
                SetQuestion(
                    "unrelated", "noul", "Is the changed file unrelated to the feature that the spec describes?",
                    _truefalse(
                        "the file belongs to another module or another concern that the spec does not mention",
                        "the file implements, tests or configures what the spec asks for",
                    ),
                ),
                SetQuestion(
                    "relatedness", "score", "How closely does the changed file relate to the feature in the spec?",
                    ["another module, not mentioned", "the same module, this path not mentioned",
                     "this path is mentioned by the spec"],
                ),
            ),
            "relevant",
        ),
        QuestionSet(
            CHANGE_COVERED,
            (
                SetQuestion(
                    "exercised", "noul", "Do the unit's tests run the changed lines of this function?",
                    _truefalse("a test in the list calls the function and reaches the changed lines",
                               "no test in the list calls the function"),
                ),
                SetQuestion(
                    "untested", "noul", "Is the changed function left without any test that runs it?",
                    _truefalse("no test in the list calls the function",
                               "a test in the list calls the function and reaches the changed lines"),
                ),
                SetQuestion(
                    "extent", "score", "How much of the changed code do the unit's tests run?",
                    ["none of it", "less than half of it", "most of it, not all", "all of it"],
                ),
            ),
            "exercised",
        ),
        QuestionSet(
            TESTS_OK,
            (SetQuestion("all_passed", "noul", "Did every test of the run pass?",
                         _truefalse("no test failed, errored or was skipped, and every new test passed",
                                    "a test failed, errored or was skipped, or a new test did not run")),),
            "all_passed",
        ),
        QuestionSet(
            CRITERION,
            (
                SetQuestion(
                    "satisfied", "noul", CRITERION_QUESTION,
                    _truefalse("the evidence shows the criterion is satisfied", "the evidence does not show it"),
                ),
                SetQuestion("status_fwd", "choice", "What is the state of the criterion?", STATUS_OPTIONS),
                SetQuestion("status_rev", "choice", "What is the state of the criterion?", _reversed(STATUS_OPTIONS),
                            reversed=True),
            ),
            "satisfied",
        ),
    )
}  # fmt: skip


class UnknownQuestionSet(ValueError):
    pass


def get_set(name: str) -> QuestionSet:
    try:
        return SETS[name]
    except KeyError:
        raise UnknownQuestionSet(f"unknown question set {name!r}") from None


def _need(truth: Mapping[str, Any], *keys: str) -> None:
    missing = [k for k in keys if k not in truth]
    if missing:
        raise ValueError(f"the ground truth lacks {', '.join(missing)}")


def _extent(covered: bool, executed: int | None, executable: int | None) -> int:
    if executed is None or not executable:
        return 3 if covered else 0
    ratio = executed / executable
    return 0 if executed == 0 else 1 if ratio < 0.5 else 2 if ratio < 1.0 else 3


def expected_for(set_name: str, truth: Mapping[str, Any]) -> dict[str, Any]:
    """`{question id: label}` from a ground-truth mapping; the ONLY place a Stage A label becomes a training label.
    A question the truth cannot answer is left out. Truth keys by set: `file-relevant`: relevant, named (optional);
    `change-covered`: covered, executed and executable (optional); `tests-ok`: tests_ok; `criterion-satisfied`:
    satisfied (optional), outcome (optional: a false `satisfied` alone gives no choice label, since
    not_implemented and contradicted cannot be told apart, C-M16-5)."""
    get_set(set_name)
    out: dict[str, Any] = {}
    if set_name == FILE_RELEVANT:
        _need(truth, "relevant")
        relevant = bool(truth["relevant"])
        out.update(relevant=relevant, unrelated=not relevant)
        named = truth.get("named")
        if not relevant:
            out["relatedness"] = 0
        elif named is not None:
            out["relatedness"] = 2 if named else 1
    elif set_name == CHANGE_COVERED:
        _need(truth, "covered")
        covered = bool(truth["covered"])
        out.update(exercised=covered, untested=not covered)
        out["extent"] = _extent(covered, truth.get("executed"), truth.get("executable"))
    elif set_name == TESTS_OK:
        _need(truth, "tests_ok")
        out["all_passed"] = bool(truth["tests_ok"])
    else:
        satisfied, outcome = truth.get("satisfied"), truth.get("outcome")
        if satisfied is True and outcome is None:
            outcome = "implemented"
        if satisfied is not None:
            out["satisfied"] = bool(satisfied)
        if outcome is not None:
            if outcome not in STATUS_OPTIONS:
                raise ValueError(f"unknown criterion outcome {outcome!r}")
            out.update(status_fwd=outcome, status_rev=outcome)
    return out


_LABELS: dict[str, tuple[str, str, str]] = {  # set -> (truth key, name when true, name when false)
    FILE_RELEVANT: ("relevant", "relevant", "out_of_scope"),
    CHANGE_COVERED: ("covered", "covered", "uncovered"),
    TESTS_OK: ("tests_ok", "tests_ok", "tests_not_ok"),
    CRITERION: ("satisfied", "satisfied", "not_satisfied"),
}


def label_names(set_name: str) -> tuple[str, str]:
    """The two names a reader uses for a set's class label: (true, false)."""
    get_set(set_name)
    _, yes, no = _LABELS[set_name]
    return yes, no


def label_name(set_name: str, expected: Mapping[str, Any]) -> str | None:
    """The class label of an `expected` map as a name, or None when the class question has no label."""
    value = expected.get(get_set(set_name).class_question)
    if not isinstance(value, bool):
        return None
    return label_names(set_name)[0 if value else 1]


def truth_from_label(set_name: str, name: str) -> dict[str, Any]:
    """The `expected_for` input that a label name stands for; ValueError for a name the set does not have."""
    key, yes, no = _LABELS[get_set(set_name).name]
    if name not in (yes, no):
        raise ValueError(f"{name!r} is not a label of {set_name} (use {yes} or {no})")
    return {key: name == yes}
