"""Review F1 (L4-SEC-039): the verifier's workbench builds the project environment from a cache of its own, emptied
at the start of each round, never from the cache any implementer step or gate used."""

from l4.sandbox.caches import VERIFY_SCOPE
from l4.verifier import ladder

from .test_ladder import IMPLEMENT, judge_step


def test_the_verifier_builds_from_its_own_emptied_cache(run_l4, valid_spec, tdd_repo, monkeypatch):  # SCN-PRV-111
    unit_cache = tdd_repo.cache / "units" / tdd_repo.key / "verify" / "openspec" / "add-discount-codes" / "cache" / "uv"
    (unit_cache / "archive-v0").mkdir(parents=True)
    (unit_cache / "archive-v0" / "stale-from-the-last-round").write_text("x")
    seen: list[dict] = []
    real = ladder.make_workbench

    def spy(**kw):
        caches = kw.get("caches")
        seen.append({"caches": caches, "uv_listing": sorted(p.name for p in unit_cache.iterdir())})
        return real(**kw)

    monkeypatch.setattr(ladder, "make_workbench", spy)
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    assert seen and all(entry["caches"] is not None for entry in seen)
    mounts = seen[0]["caches"]
    uv = next(c for c in mounts if c.env == "UV_CACHE_DIR")
    assert VERIFY_SCOPE in uv.path.parts and uv.path == unit_cache
    assert seen[0]["uv_listing"] == []  # emptied before the round's first workbench
    assert len({tuple(c.path for c in entry["caches"]) for entry in seen}) == 1  # one cache for the whole round
