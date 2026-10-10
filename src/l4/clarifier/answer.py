"""`l4/clarifier-answer@2` (SPEC L4-CLR-001): what the clarifier model returns for one question.

The schema is the SPEC's JSON example made strict (design D3). It is what `claude --json-schema` receives and what
the reply is validated against again here: validation is mandatory (L4-FAC-003). Violations name paths, never values.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from l4.schemacheck import validate

ANSWER_SCHEMA_ID = "l4/clarifier-answer@2"
MAX_ANSWER_CHARS = 1200  # S1 reads the answer and the cited text within verifier.s1.max_state_tokens together
MAX_CITATIONS = 3  # S1 is asked once per citation: each is a model call
MAX_REF_CHARS = 512
MAX_QUOTE_CHARS = 2000
MAX_CLAIM_CHARS = 400
MAX_PROBLEMS = 5

CLARIFIER_ANSWER_SCHEMA: dict[str, Any] = {
    "$id": ANSWER_SCHEMA_ID,
    "type": "object",
    "required": ["question_id", "answer", "confidence", "kind", "citations", "rationale"],
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string", "pattern": "^Q-[0-9]{3,}$"},
        "answer": {"type": "string", "minLength": 1, "maxLength": MAX_ANSWER_CHARS},
        "confidence": {"enum": ["high", "medium", "low"]},
        "kind": {"enum": ["technical", "product", "ambiguous"]},
        "citations": {
            "type": "array",
            "maxItems": MAX_CITATIONS,
            "items": {
                "type": "object",
                "required": ["ref", "quote", "claim"],
                "additionalProperties": False,
                "properties": {
                    "ref": {"type": "string", "minLength": 1, "maxLength": MAX_REF_CHARS},
                    "quote": {"type": "string", "minLength": 1, "maxLength": MAX_QUOTE_CHARS},
                    "claim": {"type": "string", "minLength": 1, "maxLength": MAX_CLAIM_CHARS},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(_Strict):
    ref: str  # `<path>`, `<path>#L<n>` or `<path>#L<a>-L<b>`, relative to the unit directory or the repository
    quote: str
    claim: str  # the one thing this citation is cited for: S1 asks whether the cited text shows exactly that


class ClarifierAnswer(_Strict):
    question_id: str
    answer: str
    confidence: Literal["high", "medium", "low"]
    kind: Literal["technical", "product", "ambiguous"]
    citations: tuple[Citation, ...]
    rationale: str


@dataclass(frozen=True)
class AnswerInvalid:
    """The reply does not satisfy `l4/clarifier-answer@2`: paths only, never values (they may be secrets)."""

    problems: tuple[str, ...]


def validate_answer(raw: str | bytes | Mapping[str, Any]) -> ClarifierAnswer | AnswerInvalid:
    if isinstance(raw, str | bytes):
        try:
            data: Any = json.loads(raw)
        except ValueError:
            return AnswerInvalid(("$: not valid JSON",))
    else:
        data = dict(raw)
    problems = validate(data, CLARIFIER_ANSWER_SCHEMA)
    if problems:
        return AnswerInvalid(tuple(problems[:MAX_PROBLEMS]))
    try:
        return ClarifierAnswer.model_validate(data)
    except ValidationError as exc:  # the schema subset accepted what the model does not: name the fields only
        fields = (".".join(str(p) for p in e["loc"]) for e in exc.errors()[:MAX_PROBLEMS])
        return AnswerInvalid(tuple(f"{name}: invalid" for name in fields))
