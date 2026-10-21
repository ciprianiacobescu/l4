from l4.doctor.registry import Check, CheckResult, Registry, run_checks


def make(*checks: Check) -> Registry:
    registry = Registry()
    for check in checks:
        registry.register(check)
    return registry


def ok(_ctx) -> CheckResult:
    return CheckResult("pass", "fine")


def ids(outcomes) -> list[str]:
    return [o.id for o in outcomes]


def test_ci_and_unit_filters(make_ctx):
    ctx, _ = make_ctx()
    seen: list[str | None] = []

    def per_unit(c) -> CheckResult:
        seen.append(c.unit)
        return CheckResult("pass", f"unit {c.unit}")

    registry = make(
        Check("T-BOTH", "ci and local", "error", ok, frozenset({"ci", "local"})),
        Check("T-LOCAL", "local only", "warn", ok, frozenset({"local"})),
        Check("T-UNIT", "unit aware", "error", per_unit, unit_aware=True),
        Check("T-LIVE", "live", "error", ok, frozenset({"live"})),
    )
    assert ids(run_checks(ctx, registry=registry, scopes={"ci"})) == ["T-BOTH", "T-UNIT"]
    assert ids(run_checks(ctx, registry=registry)) == ["T-BOTH", "T-LOCAL", "T-UNIT"]
    assert seen == [None, None]  # without --unit a unit-aware check looks at every unit
    outcomes = run_checks(ctx, registry=registry, unit="openspec:a")
    assert seen[-1] == "openspec:a"
    assert [o.message for o in outcomes if o.id == "T-UNIT"] == ["unit openspec:a"]
    assert ids(run_checks(ctx, registry=registry, scopes={"ci"}, live=True)) == ["T-BOTH", "T-UNIT", "T-LIVE"]


def test_unit_independent_checks_run_once_and_without_a_unit(make_ctx):
    ctx, _ = make_ctx()
    seen: list[str | None] = []

    def plain(c) -> CheckResult:
        seen.append(c.unit)
        return CheckResult("pass", "x")

    run_checks(ctx, registry=make(Check("T-G", "global", "info", plain)), unit="kiro:b")
    assert seen == [None]


def test_only_reruns_named_checks(make_ctx):
    ctx, _ = make_ctx()
    registry = make(Check("T-A", "a", "info", ok), Check("T-B", "b", "info", ok))
    assert ids(run_checks(ctx, registry=registry, only={"T-B"})) == ["T-B"]


def test_adoption_runs_config_and_adoption_scopes_only(make_ctx):
    """A4 (M1.8): `--adoption` is the repository's own rows plus the gate dry run; no ENV, PRV, SANDBOX or LIVE row."""
    from l4.doctor.registry import doctor_scopes

    ctx, _ = make_ctx()
    registry = make(
        Check("T-CFG", "config row", "error", ok, frozenset({"ci", "local", "config"})),
        Check("T-GATE", "gate dry run", "error", ok, frozenset({"adoption"})),
        Check("T-ENV", "environment", "error", ok, frozenset({"ci", "local"})),
        Check("T-LIVE", "live", "error", ok, frozenset({"live"})),
    )
    scopes = doctor_scopes(ci=False, adoption=True, no_gates=False)
    assert scopes == {"config", "adoption"}
    assert ids(run_checks(ctx, registry=registry, scopes=scopes)) == ["T-CFG", "T-GATE"]
    assert ids(run_checks(ctx, registry=registry, scopes=doctor_scopes(ci=True, adoption=True, no_gates=False))) == [
        "T-CFG", "T-GATE", "T-ENV",
    ]  # fmt: skip


def test_no_gates_runs_the_config_scope_only(make_ctx):
    from l4.doctor.registry import doctor_scopes

    ctx, _ = make_ctx()
    registry = make(
        Check("T-CFG", "config row", "error", ok, frozenset({"ci", "local", "config"})),
        Check("T-GATE", "gate dry run", "error", ok, frozenset({"adoption"})),
    )
    scopes = doctor_scopes(ci=False, adoption=True, no_gates=True)
    assert scopes == {"config"} and ids(run_checks(ctx, registry=registry, scopes=scopes)) == ["T-CFG"]
    assert doctor_scopes(ci=False, adoption=False, no_gates=False) == {"ci", "local"}  # plain doctor: unchanged
    assert doctor_scopes(ci=True, adoption=False, no_gates=False) == {"ci"}


def test_the_config_scope_is_carried_by_the_repository_rows():
    from l4.doctor.registry import REGISTRY, load_check_modules

    load_check_modules()
    import l4.doctor.run  # noqa: F401  (registers the modules that run.py imports)

    in_config = {c.id for c in REGISTRY.checks() if "config" in c.scopes}
    assert {"CFG-002", "CFG-005", "SPEC-001", "SPEC-002", "SPEC-004", "MEM-001"} <= in_config
    assert not {"ENV-001", "ENV-004", "PRV-001", "SANDBOX-002"} & in_config
    assert all({"ci", "local"} <= c.scopes for c in REGISTRY.checks() if c.id in in_config)  # plain doctor unchanged
