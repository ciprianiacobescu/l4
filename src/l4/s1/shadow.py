"""Shadow mode (M16-G10, plan D7 and D12): the same items asked of every configured System-One engine, recorded and
never used to decide.

Engines run one at a time (start, ask every item, stop), so two `laya-local` profiles never hold two `laya-serve`
processes. Every engine gets the identical state. An engine that is down, or answers badly, is recorded as an
`answer` with `error` and never blocks the others; the items are returned (and written by the caller) whatever
happens to the engines.
"""

import contextlib
import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.llm.system_one import (
    Question,
    SystemOneBackend,
    SystemOneBadAnswer,
    SystemOneUnavailable,
    open_s1_profile,
    parse_typed,
)
from l4.redact import Redactor
from l4.s1.questions import get_set
from l4.s1.records import AnswerRecord, ItemRecord

Opener = Callable[..., SystemOneBackend]


@dataclass(frozen=True)
class EngineRun:
    profile: str
    engine: str
    status: str  # ok | unavailable
    asked: int = 0
    failed: int = 0
    reason: str = ""


@dataclass
class ShadowRun:
    items: list[ItemRecord]
    asked: list[str] = field(default_factory=list)  # item keys that were sent, in stable hash order
    answers: list[AnswerRecord] = field(default_factory=list)
    engines: list[EngineRun] = field(default_factory=list)


def select_items(items: Sequence[ItemRecord], max_items: int) -> list[ItemRecord]:
    """At most `max_items`, in stable hash order: the same items win on every machine and every re-run."""
    ranked = sorted(items, key=lambda i: hashlib.sha256(i.item_key.encode()).hexdigest())
    return ranked[:max_items]


def wire_questions(set_name: str) -> dict[str, Question]:
    return {q.id: Question(q.kind, q.instructions, q.criteria) for q in get_set(set_name).questions}  # type: ignore[arg-type]


def _error(item: ItemRecord, profile: str, engine: str, model: str, reason: str, ms: int = 0) -> AnswerRecord:
    return AnswerRecord(item.item_key, engine, profile, model, {}, ms, error=reason)


def _profiles(cfg: L4Config, opener: Opener, kwargs: Mapping[str, object]) -> list[tuple[str, SystemOneBackend | str]]:
    """(profile, backend) or (profile, why not): the first usable `roles.s1_judge` profile, then each shadow one."""
    out: list[tuple[str, SystemOneBackend | str]] = []
    skipped: list[str] = []
    for name in cfg.roles.s1_judge:
        opened = _open(opener, cfg, name, kwargs)
        if not isinstance(opened[1], str):
            out.append(opened)
            break
        skipped.append(f"{name}: {opened[1]}")
    else:
        if cfg.roles.s1_judge:
            out.append((cfg.roles.s1_judge[0], "; ".join(skipped)))
    seen = {name for name, _ in out}
    for name in cfg.verifier.s1.shadow:
        if name in seen:
            continue
        seen.add(name)
        out.append(_open(opener, cfg, name, kwargs))
    return out


def _open(opener: Opener, cfg: L4Config, name: str, kwargs: Mapping[str, object]) -> tuple[str, SystemOneBackend | str]:
    """Any failure to open a profile (an unreadable checkpoint, a vanished cache directory) is that engine's reason,
    never an exception into the verifier (line 19: an engine error is data and blocks nothing)."""
    try:
        return name, opener(cfg, name, **kwargs)
    except RoleUnavailable as exc:
        return name, str(exc)
    except Exception as exc:  # noqa: BLE001
        return name, f"{type(exc).__name__} while opening the profile"


def run_shadow(
    cfg: L4Config,
    items: Sequence[ItemRecord],
    *,
    redactor: Redactor,
    environ: Mapping[str, str] | None = None,
    log_path: Path | None = None,
    opener: Opener = open_s1_profile,
    clock: Callable[[], float] = time.monotonic,
) -> ShadowRun:
    run = ShadowRun(list(items))
    if not cfg.verifier.s1.enabled or not items:
        return run
    chosen = select_items(items, cfg.verifier.s1.max_items)
    run.asked = [i.item_key for i in chosen]
    kwargs = {"environ": environ, "log_path": log_path, "redactor": redactor}
    for profile, backend in _profiles(cfg, opener, kwargs):
        if isinstance(backend, str):
            run.engines.append(EngineRun(profile, "", "unavailable", reason=backend))
            run.answers += [_error(i, profile, "", "", backend) for i in chosen]
            continue
        run.engines.append(_ask_all(backend, profile, chosen, run, clock))
    return run


def _ask_all(
    backend: SystemOneBackend, profile: str, chosen: Sequence[ItemRecord], run: ShadowRun, clock: Callable[[], float]
) -> EngineRun:
    engine, failed, down = backend.engine, 0, ""
    try:
        backend.start()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc) if isinstance(exc, SystemOneUnavailable) else f"{type(exc).__name__} while starting"
        with contextlib.suppress(Exception):
            backend.stop()
        run.answers += [_error(i, profile, engine, backend.model, reason) for i in chosen]
        return EngineRun(profile, engine, "unavailable", failed=len(chosen), reason=reason)
    try:
        for item in chosen:
            if down:
                run.answers.append(_error(item, profile, engine, backend.model, f"not asked: {down} earlier"))
                failed += 1
                continue
            questions = wire_questions(item.question_set)
            began = clock()
            try:
                reply = backend.query(item.state, questions)
                answers = parse_typed(reply, questions)
            except SystemOneBadAnswer as exc:
                run.answers.append(_error(item, profile, engine, backend.model, str(exc), _ms(began, clock)))
                failed += 1
                continue
            except Exception as exc:  # noqa: BLE001 - SystemOneUnavailable or anything else: the engine is down
                down = str(exc) if isinstance(exc, SystemOneUnavailable) else type(exc).__name__
                run.answers.append(_error(item, profile, engine, backend.model, down, _ms(began, clock)))
                failed += 1
                continue
            run.answers.append(
                AnswerRecord(
                    item.item_key,
                    engine,
                    profile,
                    reply.model or backend.model,
                    {qid: a.to_json() for qid, a in answers.items()},
                    _ms(began, clock),
                )  # fmt: skip
            )
    finally:
        with contextlib.suppress(Exception):
            backend.stop()
    return EngineRun(profile, engine, "ok" if not down else "unavailable", len(chosen) - failed, failed, down)


def _ms(began: float, clock: Callable[[], float]) -> int:
    return round((clock() - began) * 1000)
