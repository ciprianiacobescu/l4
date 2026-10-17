"""`L4Config`: the SPEC 3.2 tree that M0 reads, strict (`extra="forbid"`) everywhere it is modelled.

Sections owned by later changes (`archive`) are accepted as opaque mappings and
get their models when their consumer lands (see OPAQUE_SECTIONS). Not modelled yet, by M0 decision:
`ci.self_provision` (runner-provisioning).
"""

import re
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)

from l4.config import defaults as d
from l4.vcs.names import valid_branch_prefix

OPAQUE_SECTIONS = ("archive",)

_DURATION = re.compile(r"^(\d+)(s|m|h)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}

Duration = Annotated[str, StringConstraints(pattern=r"^\d+(s|m|h)$")]


def _zero_is_text(value: Any) -> Any:
    return "0" if type(value) is int and value == 0 else value  # YAML `0` is an int


DurationOrZero = Annotated[  # a bare `0` (YAML int or string) switches a wait off
    str, BeforeValidator(_zero_is_text), StringConstraints(pattern=r"^(0|\d+(s|m|h))$")
]
# These reach an installer's argv (`npm install <package>@<version>`, the Claude installer): a URL, a git spec or a
# flag must not pass. `doctor --ci --fix` runs the installers in every pipeline.
NpmName = Annotated[str, StringConstraints(pattern=r"^(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*$")]
ToolVersion = Annotated[str, StringConstraints(pattern=r"^\d+(\.\d+){0,2}([-+][0-9A-Za-z.-]+)?$")]
Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class ValueFree(ValueError):
    """A validation failure whose message never contains the configured value. The loader prints only these
    messages from custom validators (L4-CFG: errors name the path, never a value)."""


def duration_seconds(value: str) -> int:
    if value == "0":
        return 0
    match = _DURATION.match(value)
    if not match:
        raise ValueFree("expected 'auto' or a duration such as 30m (digits and one of s, m, h)")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def _auto_or_duration(value: str) -> str:
    if value != "auto":
        duration_seconds(value)
    return value


AutoOrDuration = Annotated[str, AfterValidator(_auto_or_duration)]
AUTO_TEST_TIMEOUT_S = 600


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _list(values: tuple[str, ...]) -> Any:
    return Field(default_factory=lambda: list(values))


_SCP_REPO = re.compile(r"^(?P<user>[A-Za-z0-9._-]+)@(?P<host>[A-Za-z0-9.-]+):(?P<path>[A-Za-z0-9._/-]+)$")
_HARNESS_REPO = re.compile(r"^(https|ssh)://(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9._/-]+$")


class HarnessCfg(_Strict):
    version: str | None = None
    commit: Sha | None = None
    # A fetched harness (github-parity L4-GHP-010): the shim runs `uvx --from git+<repository>@<commit>`. https or ssh
    # only, no credential in the URL (a private repository is reached with a deploy key); the scp form
    # `git@host:owner/repo.git` is written as `ssh://git@host/owner/repo.git`, which uv understands. None: vendored.
    repository: str | None = None
    # How the harness reaches CI (adoption-kit L4-ACT-004): `vendored` (.l4/vendor/), `fetched` (harness.repository at
    # harness.commit, through the shim) or `action` (the setup action, pinned in the workflow's `uses:`, no commit
    # here). None: derived by `effective_delivery`, so a config written before this key keeps meaning what it meant.
    delivery: Literal["vendored", "fetched", "action"] | None = None

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str | None) -> str | None:
        if value is None:
            return None
        scp = _SCP_REPO.match(value)
        if scp:
            value = f"ssh://{scp['user']}@{scp['host']}/{scp['path']}"
        if not _HARNESS_REPO.match(value) or (value.startswith("https://") and "@" in value):
            raise ValueError("must be an https:// or ssh:// git URL (or git@host:owner/repo.git) without a credential")
        return value

    @model_validator(mode="after")
    def _commit_with_repository(self) -> "HarnessCfg":
        if self.delivery == "fetched" and self.repository is None:
            raise ValueError("harness.delivery: fetched needs harness.repository")
        if self.delivery == "vendored" and self.repository is not None:
            raise ValueError("harness.delivery: vendored contradicts harness.repository (a fetched harness)")
        if self.delivery != "action" and self.repository is not None and self.commit is None:
            raise ValueError("harness.repository needs harness.commit: the fetched harness is pinned by commit SHA")
        return self


def effective_delivery(cfg: "L4Config") -> Literal["vendored", "fetched", "action"]:
    """The delivery in force: an explicit `harness.delivery` wins; else `fetched` when `harness.repository` is set,
    else `vendored` (the form that never had a key: `.l4/vendor/` is its only trace, and a repository
    without either is one `l4 init --vendor` would have written)."""
    if cfg.harness.delivery is not None:
        return cfg.harness.delivery
    if cfg.harness.repository is not None:
        return "fetched"
    return "vendored"


class OpenSpecCfg(_Strict):
    package: NpmName = d.OPENSPEC_PACKAGE
    version: ToolVersion = d.OPENSPEC_VERSION
    root: str = "openspec"


class KiroCfg(_Strict):
    root: str = ".kiro/specs"
    write_in_progress_marker: bool = True
    write_queued_marker: bool = False
    archive_dir: str | None = None


class SpecCfg(_Strict):
    frameworks: Literal["auto"] | list[Literal["openspec", "kiro"]] = "auto"
    primary: Literal["auto", "openspec", "kiro"] = "auto"
    allow_branch_specs: bool = False
    openspec: OpenSpecCfg = Field(default_factory=OpenSpecCfg)
    kiro: KiroCfg = Field(default_factory=KiroCfg)


class SddCfg(_Strict):
    enforce: bool = True
    require_traceability: bool = True
    scope_check: Literal["off", "warn", "fail"] = "warn"


def _append_unique(base: list[str], extra: list[str]) -> list[str]:
    """The base list with the `extra_` entries after it, each once (M1.8 A6: a list key that is set replaces its
    defaults, an `extra_` key adds to whatever the list holds)."""
    return list(dict.fromkeys([*base, *extra]))


class TddCfg(_Strict):
    mode: Literal["strict", "guided", "off"] = "strict"
    exempt_task_kinds: list[str] = _list(d.EXEMPT_TASK_KINDS)
    test_globs: list[str] = _list(d.TEST_GLOBS)
    test_support_globs: list[str] = _list(d.TEST_SUPPORT_GLOBS)
    runner_config_files: list[str] = _list(d.RUNNER_CONFIG_FILES)
    gate_config_globs: list[str] = _list(d.GATE_CONFIG_GLOBS)
    extra_test_globs: list[str] = Field(default_factory=list)  # appended to `test_globs`, whatever it holds
    extra_test_support_globs: list[str] = Field(default_factory=list)  # appended to `test_support_globs`

    @model_validator(mode="after")
    def _merge_extras(self) -> "TddCfg":
        self.test_globs = _append_unique(self.test_globs, self.extra_test_globs)
        self.test_support_globs = _append_unique(self.test_support_globs, self.extra_test_support_globs)
        return self


class OddCfg(_Strict):
    allowed_paths: list[str] = Field(default_factory=lambda: ["**"])
    forbidden_paths: list[str] = _list(d.FORBIDDEN_PATHS)
    extra_forbidden_paths: list[str] = Field(default_factory=list)  # appended to `forbidden_paths`
    require_test_oracle: bool = True
    bootstrap_tests: bool = True
    verify_preexisting: bool = True

    @model_validator(mode="after")
    def _merge_extras(self) -> "OddCfg":
        self.forbidden_paths = _append_unique(self.forbidden_paths, self.extra_forbidden_paths)
        return self


def _relative_paths(values: list[str]) -> list[str]:
    """Report paths are read from the worktree: relative, non-empty, and never leaving it."""
    for value in values:
        pure = PurePosixPath(value)
        if not value or pure.is_absolute() or ".." in pure.parts:
            raise ValueFree("every report path must be relative and stay inside the worktree")
    return values


class UnitGate(_Strict):
    command: str = ""
    reports: list[str] = Field(default_factory=lambda: [".l4-out/junit.xml"])

    _reports_inside = field_validator("reports")(_relative_paths)
    format: Literal["junit", "playwright-json", "pytest-json", "tap"] = "junit"
    targeted: str = ""


class ServeCfg(_Strict):
    command: str = ""
    ready_url: str = ""
    timeout: Duration = "120s"


class E2eGate(_Strict):
    command: str = ""
    reports: list[str] = Field(default_factory=list)

    _reports_inside = field_validator("reports")(_relative_paths)
    format: Literal["junit", "playwright-json", "pytest-json", "tap"] = "playwright-json"
    serve: ServeCfg = Field(default_factory=ServeCfg)


class ExtraGate(_Strict):
    name: str
    command: str
    required: bool = True


class GatesCfg(_Strict):
    setup: list[str] = Field(default_factory=list)
    build: list[str] = Field(default_factory=list)
    lint: list[str] = Field(default_factory=list)
    typecheck: list[str] = Field(default_factory=list)
    test: UnitGate = Field(default_factory=UnitGate)
    e2e: E2eGate = Field(default_factory=E2eGate)
    extra: list[ExtraGate] = Field(default_factory=list)
    timeout: Duration = "30m"
    test_timeout: AutoOrDuration = "auto"  # one test's limit (W-D1); auto: the smaller of 10m and half of `timeout`
    network: Literal["allow", "none"] = "allow"

    @model_validator(mode="after")
    def _one_test_is_shorter_than_the_gate(self) -> "GatesCfg":
        if self.test_timeout not in ("auto",) and 0 < duration_seconds(self.test_timeout) >= duration_seconds(
            self.timeout
        ):
            raise ValueFree("gates.test_timeout must be shorter than gates.timeout (or 0s to switch it off)")
        return self

    def test_timeout_seconds(self) -> int:
        """The limit of one test in seconds; 0: none."""
        if self.test_timeout == "auto":
            return min(AUTO_TEST_TIMEOUT_S, duration_seconds(self.timeout) // 2)
        return duration_seconds(self.test_timeout)


class CacheCfg(_Strict):
    path: str
    env: str
    read_only: bool = False

    @field_validator("path")
    @classmethod
    def _inside_the_runner_cache(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if ".." in pure.parts or not (value.startswith("$L4_CACHE/") or pure.is_absolute()):
            raise ValueFree("a cache path must be absolute or start with $L4_CACHE/, without '..'")
        return value


def _caches() -> dict[str, CacheCfg]:
    return {name: CacheCfg(path=p, env=e, read_only=ro) for name, (p, e, ro) in d.CACHES.items()}


class SandboxCfg(_Strict):
    mode: Literal["auto", "user", "bwrap", "container", "none"] = "auto"
    user_per_profile: dict[str, str] = Field(default_factory=dict)
    caches: dict[str, CacheCfg] = Field(default_factory=_caches)
    credential_paths: dict[str, list[str]] = Field(
        default_factory=lambda: {k: list(v) for k, v in d.CREDENTIAL_PATHS.items()}
    )
    user: str = "l4-sandbox"
    image: str | None = None
    allow_none: bool = False

    @field_validator("credential_paths")
    @classmethod
    def _merge_over_the_defaults(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        """A user entry replaces that adapter's default and nothing else: this is the set that is MOUNTED for an
        adapter. What is HIDDEN from the others is the union with the built-in defaults, computed where the sandbox
        argv is built (`l4.sandbox.base.hidden_credential_paths`, L4-SEC-005). Each path is `~/...` or absolute: a
        relative one would resolve against whatever directory bwrap runs in."""
        for paths in value.values():
            for raw in paths:
                if not (raw.startswith("~/") or PurePosixPath(raw).is_absolute()):
                    raise ValueFree("every credential path must start with ~/ or be absolute")
        return {**{k: list(v) for k, v in d.CREDENTIAL_PATHS.items()}, **value}


COMMAND_PLACEHOLDERS = ("prompt_file", "result_path", "model", "session_id")
PROBE_PLACEHOLDERS = ("model",)
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")  # `{"a": 1}` is literal text, `{name}` a placeholder


def command_option_problems(options: dict[str, Any]) -> list[str]:
    """The `command` adapter's argv templates, checked at load: a list of strings, and only the placeholders the
    adapter fills. The messages name the option, never the configured text (ValueFree)."""
    problems = []
    for key, known in (("argv", COMMAND_PLACEHOLDERS), ("probe_argv", PROBE_PLACEHOLDERS)):
        if key not in options and key == "probe_argv":
            continue
        argv = options.get(key)
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            problems.append(f"options.{key} must be a non-empty list of strings")
        elif any(m.group(1) not in known for a in argv for m in PLACEHOLDER.finditer(a)):
            problems.append(f"options.{key} has an unknown placeholder (known: {', '.join(known)})")
    return problems


OpencodeTool = Literal["bash", "edit", "write", "read", "glob", "grep", "list", "patch"]
OpencodeId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")]
_SECRET_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_RESERVED_ENV_NAMES = frozenset({"PATH", "HOME", "CI", "GITHUB_TOKEN"})
_RESERVED_ENV_PREFIXES = ("GITHUB_", "RUNNER_")


def _secret_env_name(value: str) -> str:
    """The name of a variable that holds a credential. It is written into the `env:` of the rendered workflow
    (`secrets.<NAME>`), so it must be a plain upper-case variable name (no `}}`, newline or space can reach the YAML)
    and not one the runner or the job owns."""
    if not _SECRET_ENV_NAME.match(value):
        raise ValueFree("not an environment variable name (upper-case letters, digits and underscores, up to 64)")
    if value in _RESERVED_ENV_NAMES or value.startswith(_RESERVED_ENV_PREFIXES):
        raise ValueFree("a reserved environment variable name (PATH, HOME, CI, GITHUB_*, RUNNER_*)")
    return value


EnvName = Annotated[str, AfterValidator(_secret_env_name)]


class OpencodeModelLimits(_Strict):
    """`provider.<id>.models.<model>.limit`: without `output` OpenCode asks the server for 32000 tokens."""

    context: int = Field(ge=1)
    output: int = Field(ge=1)


class OpencodeProvider(_Strict):
    """A custom OpenAI-compatible provider for an opencode profile. The key is named by the variable that holds it
    (`api_key_env`, read from the harness's own environment); the variable is never passed to the agent."""

    id: OpencodeId
    base_url: str
    api_key_env: EnvName
    models: dict[str, OpencodeModelLimits] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _plain_http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueFree("must be an http(s) URL with a host")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueFree("must carry no credentials, query or fragment (the key goes through api_key_env)")
        return value.rstrip("/")


class OpencodeOptions(_Strict):
    model_config = ConfigDict(
        extra="ignore", strict=True
    )  # other keys under `options` are other consumers' (not checked here)

    provider: OpencodeProvider | None = None
    tools: list[OpencodeTool] | None = Field(None, min_length=1)  # the only tools the agent is sent (implement mode)
    reasoning: Literal["none", "minimal", "low", "medium", "high"] | None = None  # the model's `reasoningEffort`

    @model_validator(mode="after")
    def _reasoning_rides_on_the_provider(self) -> "OpencodeOptions":
        if self.reasoning is not None and self.provider is None:
            raise ValueFree("reasoning is set through the model entry of options.provider")
        return self


def opencode_option_problems(options: dict[str, Any], model: str | None) -> list[str]:
    """The opencode profile's `options`, checked at load. Messages carry the option path and the rule, never the
    configured text."""
    if not options:
        return []
    try:
        parsed = OpencodeOptions.model_validate(options)
    except ValidationError as error:
        problems = []
        for item in error.errors():
            where = ".".join(str(part) for part in item["loc"])
            cause = item.get("ctx", {}).get("error")
            rule = str(cause) if isinstance(cause, ValueFree) else item["type"].replace("_", " ")
            problems.append(f"options.{where or 'options'}: {rule}")
        return problems
    if parsed.provider is not None and model is not None and model.split("/", 1)[0] != parsed.provider.id:
        return ["options.provider.id must equal the provider part of model (provider/model)"]
    if parsed.provider is not None and model is not None and model.split("/", 1)[-1] not in parsed.provider.models:
        return ["options.provider.models must have an entry (context, output) for the profile's model"]
    return []


TOOL_VENDORS = {"codex": "openai", "claude-code": "anthropic"}  # single-vendor CLIs: the tool says whose models run


class Profile(_Strict):
    """One model for adapter and backend profiles: "both" is a doctor finding (CFG-002), not a load error."""

    adapter: str | None = None
    backend: str | None = None
    model: str | None = None
    auth: Literal["subscription", "api_key"] | None = None
    min_version: ToolVersion | None = None
    min_remaining_percent: float | None = Field(None, ge=0, le=100)  # overrides availability.min_remaining_percent
    max_concurrency: int | None = Field(default=None, ge=1)
    context_budget_tokens: int | None = Field(default=None, ge=1000)  # this profile's steps: replaces the implementer's
    options: dict[str, Any] = Field(default_factory=dict)
    vendor: str | None = None
    base_url: str | None = None
    api_key_env: Annotated[str, AfterValidator(_secret_env_name)] | None = None
    engine: str | None = None

    @model_validator(mode="after")
    def _vendor_of_the_tool(self) -> "Profile":
        """A single-vendor CLI runs one vendor's models: a `vendor:` that says otherwise is a mistake, not a claim."""
        tool = TOOL_VENDORS.get(self.adapter or "")
        if tool and self.vendor is not None and self.vendor.strip().lower() != tool:
            raise ValueFree(f"vendor contradicts the adapter: the {self.adapter} adapter only runs {tool} models")
        return self

    @model_validator(mode="after")
    def _ollama_engine(self) -> "Profile":
        """`engine: ollama` is a keyless System-One server on the LAN: an http(s) origin is required, and a key is
        refused (it would never be sent)."""
        if self.backend != "system-one" or self.engine != "ollama":
            return self
        if not self.base_url:
            raise ValueFree("base_url is required for the ollama engine")
        parts = urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueFree("base_url must be an http(s) URL with a host")
        if parts.username or parts.password or parts.query or parts.fragment or parts.path.strip("/"):
            raise ValueFree("base_url must be a bare origin: no credentials, path, query or fragment")
        if self.api_key_env:
            raise ValueFree("api_key_env is not used by the ollama engine (it is keyless)")
        return self

    @model_validator(mode="after")
    def _opencode_options(self) -> "Profile":
        if self.adapter == "opencode" and (problems := opencode_option_problems(self.options, self.model)):
            raise ValueFree("; ".join(problems))
        return self

    def opencode_options(self) -> OpencodeOptions | None:
        """The typed options of an opencode profile (checked at load); None for another adapter or no options."""
        if self.adapter != "opencode" or not self.options:
            return None
        return OpencodeOptions.model_validate(self.options)

    @model_validator(mode="after")
    def _command_options(self) -> "Profile":
        if self.adapter == "command" and (problems := command_option_problems(self.options)):
            raise ValueFree("; ".join(problems))
        return self


class RolesCfg(_Strict):
    implementer: list[str] = Field(default_factory=list)
    clarifier: list[str] = Field(default_factory=list)
    verifier_agent: list[str] = Field(default_factory=list)
    judges: list[str] = Field(default_factory=list)
    s1_judge: list[str] = Field(default_factory=list)
    spec_writer: list[str] = Field(default_factory=list)


class AvailabilityCfg(_Strict):
    cache_ttl: Duration = "15m"
    auth_failure_ttl: Duration = "2m"  # a failed hello that was an auth refusal (401/403) is remembered this long
    probe_timeout: Duration = "60s"
    default_ladder: list[str] = Field(default_factory=lambda: ["binary", "auth", "quota", "hello"])
    min_remaining_percent: float = 10
    default_cooldown: Duration = "30m"
    login_lock_wait: Duration = "20m"  # how long a probe or run waits for another process to finish with the same login
    credits_cooldown: Duration = "24h"
    wait_in_run: DurationOrZero = (
        "5m"  # every implementer cooling, the earliest ends within this: wait and go on; 0 off
    )
    wait_in_run_max_total: Duration = "15m"  # the most one run waits in all (L4-AVL-011)
    min_remaining_usd: float = 0.50
    hello_prompt: str = "Reply with exactly: L4-OK"
    custom_probes: list[dict[str, Any]] = Field(default_factory=list)  # M1: agent-factory models the entries


class ImplementerCfg(_Strict):
    task_grouping: Literal["task", "parent"] = "task"
    context_budget_tokens: int = 32000  # tokens of 4 characters (L4-IMP-053)
    include_agents_md: bool = False  # the repository root's AGENTS.md joins the prompt as a convention (L4-IMP-051)
    max_task_attempts: int = Field(default=3, ge=1)
    escalate_after: int = Field(default=2, ge=0)  # failed attempts of a phase on one profile before the next (0: off)
    result_repair_attempts: int = Field(default=1, ge=0)
    wip_snapshot_interval: Duration = "10m"
    heartbeat: DurationOrZero = "2m"  # a progress line every interval while an agent step runs; 0: off (L4-IMP-023)
    idle_timeout: DurationOrZero = "10m"  # stop an agent silent for this long with no tool call open; 0: off
    session_resume: Literal["same_runner_only", "artifact", "never"] = "same_runner_only"

    @model_validator(mode="after")
    def _liveness_minimums(self) -> "ImplementerCfg":
        for key, minimum, text in (("heartbeat", 30, "30s"), ("idle_timeout", 60, "1m")):
            seconds = duration_seconds(getattr(self, key))
            if 0 < seconds < minimum:
                raise ValueFree(f"implementer.{key} must be 0 (off) or at least {text}")
        return self


class ClarifierCfg(_Strict):
    enabled: bool = True
    auto_accept_kinds: list[Literal["technical", "product", "ambiguous"]] = Field(default_factory=lambda: ["technical"])
    answer_by_agents: bool = False  # an agent may accept or answer any question with `l4 questions` (L4-QMD-009)
    min_confidence: Literal["high", "medium"] = "high"
    max_open_questions: int = Field(default=3, ge=1)
    s1_router: bool = True
    s1_standin: Literal["none", "llm_boolean"] = "none"


class PlaywrightCfg(_Strict):
    enabled: Literal["auto"] | bool = "auto"
    base_url_env: str = "L4_E2E_BASE_URL"
    ui_paths: list[str] = _list(d.UI_PATHS)


class RouterGate(_Strict):
    technical_min: float = Field(default=d.S1_ROUTER_TECHNICAL_MIN, ge=0.0, le=1.0)
    internal_min: float = Field(default=d.S1_ROUTER_INTERNAL_MIN, ge=0.0, le=1.0)


class CitationGate(_Strict):
    support_min: float = Field(default=d.S1_CITATION_SUPPORT_MIN, ge=0.0, le=1.0)
    opposite_max: float = Field(default=d.S1_CITATION_OPPOSITE_MAX, ge=0.0, le=1.0)
    establishes_min: float = Field(default=d.S1_CITATION_ESTABLISHES_MIN, ge=0.0, le=1.0)


class CriterionGate(_Strict):
    accept: float = Field(default=d.S1_CRITERION_ACCEPT, ge=0.0, le=1.0)


class S1Decisions(_Strict):
    """Thresholds per System-One question (not for the boolean stand-in, which keeps the two SPEC thresholds)."""

    router: RouterGate = Field(default_factory=RouterGate)
    citation: CitationGate = Field(default_factory=CitationGate)
    criterion: CriterionGate = Field(default_factory=CriterionGate)


class S1Cfg(_Strict):
    enabled: bool = True
    accept_threshold: float = 0.9  # the boolean stand-in's support gate (SPEC L4-CLR-002)
    reject_threshold: float = 0.1  # the boolean stand-in's p(product) gate
    max_state_tokens: int = 450
    shadow: list[str] = Field(default_factory=list)  # M1.6: extra System-One profiles asked record-only
    max_items: int = Field(default=d.S1_MAX_ITEMS, ge=1)
    decisions: S1Decisions = Field(default_factory=S1Decisions)

    def laya_budget(self) -> int:
        """`max_state_tokens` cut to what the Laya server's window takes (a System-One model, not an LLM stand-in)."""
        return min(self.max_state_tokens, d.S1_STATE_BUDGET_CAP)

    def budget(self, engine: str) -> int:
        """The state budget of an engine: Laya's window is small, Jev's (32k) is not, and cutting Jev to the Laya cap
        measurably cost accuracy (eval-framework 6.2). Ollama's decision models read a long window (Tev1: 262k), so it
        takes the full budget like Jev; its 64 KiB request limit is checked on the wire, not here."""
        return self.max_state_tokens if engine in ("jev", "ollama") else self.laya_budget()


class DiffCoverageCfg(_Strict):
    mode: Literal["off", "warn", "fail"] = "warn"
    min_percent: int = Field(default=d.DIFF_COVERAGE_MIN_PERCENT, ge=0, le=100)
    languages: list[Literal["python"]] = Field(default_factory=lambda: ["python"])


class EvidenceCfg(_Strict):
    module_roots: list[str] = _list(d.MODULE_ROOTS)
    scope_exempt: list[str] = _list(d.SCOPE_EXEMPT)
    diff_coverage: DiffCoverageCfg = Field(default_factory=DiffCoverageCfg)


class FeedbackCfg(_Strict):
    """A person's requests for changes (`feedback.md`, L4-FBK-006): `max_rounds` feedback fix units per unit, counted
    apart from `verifier.max_fix_rounds`; 0 turns taking off."""

    max_rounds: int = Field(default=5, ge=0)


class PanelCfg(_Strict):
    size: int = Field(default=1, ge=1)
    tie_breaker: bool = True
    pass_k: int = Field(default=1, ge=1)


class VerifierCfg(_Strict):
    independence: Literal["different_vendor", "different_model", "none"] = "different_vendor"
    max_fix_rounds: int = Field(default=3, ge=0)
    flaky_repeats: int = Field(default=3, ge=1)
    generate_missing_tests: bool = True
    audit_sample_ratio: float = 0.3
    max_criteria_per_test: int = Field(default=3, ge=1)
    playwright: PlaywrightCfg = Field(default_factory=PlaywrightCfg)
    s1: S1Cfg = Field(default_factory=S1Cfg)
    evidence: EvidenceCfg = Field(default_factory=EvidenceCfg)
    panel: PanelCfg = Field(default_factory=PanelCfg)
    fix_minor_findings: bool = False
    judge_context_budget_tokens: int = Field(default=48000, ge=1000)  # the step-9 judge's spec text (L4-KSP-014)
    secret_scan: Literal["gitleaks", "none"] = "gitleaks"


class GithubAppCfg(_Strict):
    app_id_env: str = "L4_GITHUB_APP_ID"
    private_key_env: str = "L4_GITHUB_APP_KEY"


def _branch_prefix(value: str) -> str:
    if not valid_branch_prefix(value):
        raise ValueFree("not a usable branch prefix (letters, digits, . _ - and single slashes; no '..' or '.lock')")
    return value


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _env_name(value: str) -> str:
    """The name is spliced into the git credential helper's shell text (`l4.forge.gitlab.git_auth_config`)."""
    if not _ENV_NAME.match(value):
        raise ValueFree("not an environment variable name (letters, digits and underscores, not starting with a digit)")
    return value


class GitlabCfg(_Strict):
    """Where the GitLab API is for a run outside CI; inside CI `CI_API_V4_URL` and `CI_PROJECT_ID` win."""

    api_url: str | None = None  # e.g. https://gitlab.example.com/api/v4
    project: str | None = None  # numeric id or `group/project`


class ForgeCfg(_Strict):
    type: Literal["auto", "github", "gitlab", "local"] = "auto"
    base_branch: str = "main"
    branch_prefix: Annotated[str, AfterValidator(_branch_prefix)] = "l4/"
    merge_policy: Literal["human", "auto"] = "human"
    token_env: Annotated[str, AfterValidator(_env_name)] = "L4_FORGE_TOKEN"
    gitlab: GitlabCfg = Field(default_factory=GitlabCfg)
    labels_prefix: str = "l4:"
    notify_mentions: list[str] = Field(default_factory=list)
    github_app: GithubAppCfg = Field(default_factory=GithubAppCfg)


class LocksCfg(_Strict):
    lease: Duration = "30m"


_CRON = re.compile(r"^[A-Za-z0-9*/,?#-]+( [A-Za-z0-9*/,?#-]+){4}$")


def _cron(value: str) -> str:
    """Five fields of a POSIX cron expression, as GitHub's `schedule:` reads them; it is written into the workflow."""
    if not _CRON.match(value):
        raise ValueFree('not a cron expression of five space-separated fields, for example "*/30 * * * *"')
    return value


# a version, a range (`>=22`, `^22.1.0`, `22.x`) or an alias (`lts/*`): one line, no quote or colon
_TOOL_VERSION = r"^[A-Za-z0-9<>=^~][A-Za-z0-9._+<>=^~ *|/-]{0,63}$"


def _toolchain_file(value: str) -> str:
    """A repository-relative file read by the setup action (`go.work`, `.nvmrc`)."""
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or "\n" in value or '"' in value:
        raise ValueFree("a version file must be a relative path inside the repository, without '..'")
    return value


class ToolchainCfg(_Strict):
    """One toolchain the L4 job provides (L4-CI-005): exactly one of `version` and `version_file`."""

    version: Annotated[str, StringConstraints(pattern=_TOOL_VERSION)] | None = None
    version_file: Annotated[str, AfterValidator(_toolchain_file)] | None = None

    @model_serializer(mode="wrap")
    def _without_unset(self, handler: Any) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class PnpmCfg(_Strict):
    version: Annotated[str, StringConstraints(pattern=_TOOL_VERSION)]


class ToolchainsCfg(_Strict):
    """`ci.toolchains` (L4-CI-005): the toolchains the generated GitHub job sets up before L4, for gates of Go and
    TypeScript code. Unset entries are left out of the dump, so the default dumps as `{}`."""

    go: ToolchainCfg | None = None
    node: ToolchainCfg | None = None
    pnpm: PnpmCfg | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "ToolchainsCfg":
        for name in ("go", "node"):
            entry = getattr(self, name)
            if entry is not None and (entry.version is None) == (entry.version_file is None):
                raise ValueFree(f"ci.toolchains.{name}: give exactly one of version and version_file")
        return self

    @model_serializer(mode="wrap")
    def _without_unset(self, handler: Any) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class CiCfg(_Strict):
    platform: Literal["auto", "github", "gitlab", "local"] = "auto"
    max_parallel_units: int = Field(default=2, ge=1)
    time_budget: AutoOrDuration = "auto"
    soft_deadline_margin: Duration = "20m"
    runner_tags: list[str] = Field(default_factory=lambda: ["agentic"])
    continuation: Literal["dispatch", "schedule-only"] = "dispatch"
    self_provision: Literal["auto"] | bool = "auto"
    # the GitHub Environment the generated job runs in: the forge token and the agent credentials are secrets of it
    # (repository secrets still resolve); null leaves `environment:` out of the workflow
    github_environment: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,255}$")] | None = "l4"
    # the cron of the generated GitHub workflow's `schedule:` trigger; null leaves the trigger out. `l4 upgrade`
    # re-renders the workflow, so this is where it is changed (L4-ACT-004)
    schedule: Annotated[str, AfterValidator(_cron)] | None = "*/30 * * * *"
    # whether the generated GitHub workflow uploads `.l4-out` (prompts and agent transcripts, secrets masked) as the
    # artifact `l4-out`; on a public repository any signed-in user can download it, so set false there
    upload_artifacts: bool = True
    # the toolchains the generated GitHub job sets up before L4 (L4-CI-005); GitLab renders nothing
    toolchains: ToolchainsCfg = Field(default_factory=ToolchainsCfg)


class PriceEntry(_Strict):
    input: float
    output: float


class BudgetsCfg(_Strict):
    max_iterations_per_unit: int = Field(default=30, ge=1)
    max_cost_usd_per_unit: float = 50
    no_progress_iterations: int = Field(default=3, ge=1)
    same_error_repeats: int = Field(default=3, ge=1)
    price_table: dict[str, PriceEntry] = Field(default_factory=dict)


class ObservabilityCfg(_Strict):
    log_dir: str = ".l4-out/logs"
    redact_env: list[str] = _list(d.DEFAULT_REDACT_ENV)
    redact_forge_urls: bool = True  # the forge host is `<forge>` in everything committed (L4-OBS-002)


class SerenaCfg(_Strict):
    enabled: bool = True
    version: str = d.SERENA_VERSION
    context: Literal["auto", "claude-code", "codex", "ide"] = "auto"


class MemoryCfg(_Strict):
    enabled: bool = True
    lessons_file: str = d.LESSONS_FILE
    max_lessons: int = Field(default=d.MAX_LESSONS, ge=1)
    max_bytes: int = Field(default=d.MAX_LESSON_BYTES, ge=1)
    serena: SerenaCfg = Field(default_factory=SerenaCfg)


YOLO_GATE_KINDS = ("setup", "build", "lint", "typecheck", "test", "e2e")
YOLO_RESERVED_PROFILES = ("all", "none")  # `all`: every configured gate; `none`: no check (batches only)
_YOLO_EXTRA = re.compile(r"^extra:[A-Za-z0-9][A-Za-z0-9._-]*$")
_YOLO_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class YoloReviewCfg(_Strict):
    """The readiness review (review-resolution design section 8): material budgets and the conditions of
    `l4 yolo accept`. The module constants in `yolo/readiness.py` stay as the defaults."""

    max_file_chars: int = Field(default=20_000, ge=1000)
    max_folder_chars: int = Field(default=80_000, ge=1000)
    max_dependency_chars: int = Field(default=20_000, ge=0)
    accept_after_rounds: int = Field(default=2, ge=1)
    accept_by_agents: bool = False


class YoloMergeCfg(_Strict):
    """How a plan's harness merge lands a unit (squash-and-delete L4-YOLO-032, L4-YOLO-033). Only the merges of an
    active `merge: auto` plan read it; a person's merge uses the forge's own options."""

    method: Literal["squash", "fast-forward"] = "squash"
    delete_branches: bool = True


class YoloCfg(_Strict):
    """Delivery plans (yolo-mode L4-YOLO-009): `profiles` maps a name to the gate kinds a post-merge check runs."""

    profiles: dict[str, list[str]] = Field(default_factory=dict)
    review: YoloReviewCfg = Field(default_factory=YoloReviewCfg)
    merge: YoloMergeCfg = Field(default_factory=YoloMergeCfg)
    hold: list[str] = Field(default_factory=list)

    @field_validator("hold")
    @classmethod
    def _hold(cls, value: list[str]) -> list[str]:
        if any(not entry.strip() for entry in value):
            raise ValueFree("yolo.hold: an entry is empty (name a unit id or an fnmatch pattern)")
        return value

    @field_validator("profiles")
    @classmethod
    def _profiles(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        for name, kinds in value.items():
            if name in YOLO_RESERVED_PROFILES:
                raise ValueFree(f"yolo.profiles: {name!r} is reserved (all = every configured gate, none = no check)")
            if not _YOLO_PROFILE.match(name):
                raise ValueFree(f"yolo.profiles: {name!r} is not a valid profile name")
            for kind in kinds:
                if kind not in YOLO_GATE_KINDS and not _YOLO_EXTRA.match(kind):
                    raise ValueFree(
                        f"yolo.profiles.{name}: {kind!r} is not a gate kind "
                        f"(one of {', '.join(YOLO_GATE_KINDS)}, or extra:<name>)"
                    )
        return value


class L4Config(_Strict):
    version: Literal[1] = 1
    harness: HarnessCfg = Field(default_factory=HarnessCfg)
    spec: SpecCfg = Field(default_factory=SpecCfg)
    sdd: SddCfg = Field(default_factory=SddCfg)
    tdd: TddCfg = Field(default_factory=TddCfg)
    odd: OddCfg = Field(default_factory=OddCfg)
    gates: GatesCfg = Field(default_factory=GatesCfg)
    sandbox: SandboxCfg = Field(default_factory=SandboxCfg)
    profiles: dict[str, Profile] = Field(default_factory=dict)
    roles: RolesCfg = Field(default_factory=RolesCfg)
    availability: AvailabilityCfg = Field(default_factory=AvailabilityCfg)
    implementer: ImplementerCfg = Field(default_factory=ImplementerCfg)
    clarifier: ClarifierCfg = Field(default_factory=ClarifierCfg)
    verifier: VerifierCfg = Field(default_factory=VerifierCfg)
    feedback: FeedbackCfg = Field(default_factory=FeedbackCfg)
    archive: dict[str, Any] = Field(default_factory=dict)
    memory: MemoryCfg = Field(default_factory=MemoryCfg)
    forge: ForgeCfg = Field(default_factory=ForgeCfg)
    locks: LocksCfg = Field(default_factory=LocksCfg)
    ci: CiCfg = Field(default_factory=CiCfg)
    budgets: BudgetsCfg = Field(default_factory=BudgetsCfg)
    observability: ObservabilityCfg = Field(default_factory=ObservabilityCfg)
    yolo: YoloCfg = Field(default_factory=YoloCfg)

    @model_validator(mode="after")
    def _no_credential_in_the_forge_token_variable(self) -> "L4Config":
        """A profile's key variable is never the forge token's: the job env would carry one secret under two roles."""
        token = self.forge.token_env
        for name, profile in self.profiles.items():
            if profile.api_key_env == token:
                raise ValueFree(f"profiles.{name}.api_key_env must not be the forge token variable (forge.token_env)")
            options = profile.opencode_options() if profile.adapter == "opencode" else None
            if options is not None and options.provider is not None and options.provider.api_key_env == token:
                raise ValueFree(f"profiles.{name}: the provider api_key_env must not be forge.token_env")
        return self
