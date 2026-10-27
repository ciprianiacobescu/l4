"""Built-in defaults of SPEC 3.2 that are lists, plus the runner paths of L4-CFG-005."""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from l4.exitcodes import ExitCode, L4Exit
from l4.safepath import resolve_tool, safe_path

if TYPE_CHECKING:
    from l4.config.schema import L4Config

OPENSPEC_PACKAGE = "@fission-ai/openspec"
OPENSPEC_VERSION = "1.14.0"

# Starting gates of the System-One decisions (docs/eval-framework.md 6.3). [G] guesses from one toy project, about
# one sample per cell: calibrate per project (SC-16) before trusting them.
S1_ROUTER_TECHNICAL_MIN = 0.85  # mean P(technical) over both option orders
S1_ROUTER_INTERNAL_MIN = 0.8  # P("derivable from the project's own material"), asked per citation
S1_CITATION_SUPPORT_MIN = 0.9  # P(cited text shows the claim)
S1_CITATION_ESTABLISHES_MIN = 0.8  # P(the claim, as the cited text shows it, establishes the answer): uncalibrated
S1_CITATION_OPPOSITE_MAX = 0.2  # P(cited text shows the opposite of the claim)
S1_CRITERION_ACCEPT = 0.9  # step 8: recorded only until the traceability-off row exists
S1_STATE_BUDGET_CAP = 300  # approx-tokens: within Laya's 463-token window for the worst case, code [V, M15-G2 P3]
MODULE_ROOTS = ("src", "lib", "packages", "apps")  # M1.6 [G]: a module is the first component under one of these
SCOPE_EXEMPT = ("docs/**", "**/*.md", "CHANGELOG*")
DIFF_COVERAGE_MIN_PERCENT = 80  # [G]
S1_MAX_ITEMS = 60  # [G] shadow items per round
S1_CHECKPOINTS_DIR = "s1/checkpoints"  # under $L4_CACHE: the only place a tuned checkpoint may be loaded from
EXEMPT_TASK_KINDS = ("docs", "config", "chore", "no-test", "test-infra")
TEST_GLOBS = (
    "**/test/**", "**/tests/**", "**/__tests__/**", "**/*_test.*", "**/test_*.*",
    "**/*.test.*", "**/*.spec.*", "e2e/**", "**/fixtures/**", "**/testdata/**", "**/conftest.py",
)  # fmt: skip
TEST_SUPPORT_GLOBS = (
    "**/conftest.py", "**/fixtures/**", "**/__mocks__/**", "**/mocks/**", "**/testdata/**",
    "**/test-setup.*", "**/setupTests.*", "**/tests/helpers/**", "**/test/helpers/**",
)  # fmt: skip
# pytest 9 also reads its configuration from `.pytest.ini`, `pytest.toml` and `.pytest.toml`
RUNNER_CONFIG_FILES = (
    "pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", ".coveragerc", "tox.ini", "setup.cfg", "pyproject.toml",
    "package.json", "jest.config.*", "vitest.config.*", "playwright.config.*", "karma.conf.*", ".mocharc.*",
)  # fmt: skip
GATE_CONFIG_GLOBS = (
    "tsconfig*.json", ".eslintrc*", "eslint.config.*", "mypy.ini", ".mypy.ini", "ruff.toml",
    ".ruff.toml", ".flake8", ".pylintrc", ".golangci.*", ".semgrepignore", ".gitleaksignore",
    ".gitleaks.toml", "pyrightconfig.json", "pylintrc", ".eslintignore", ".prettierrc*", ".prettierignore",
    "biome.json", "biome.jsonc",
)  # fmt: skip
FORBIDDEN_PATHS = (".github/workflows/**", ".gitlab-ci.yml", "**/migrations/**", "infra/**")
UI_PATHS = ("web/**", "frontend/**", "app/**/*.tsx", "src/**/*.vue", "templates/**")
DEFAULT_REDACT_ENV = (
    "L4_FORGE_TOKEN", "L4_TRIGGER_TOKEN", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "CODEX_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "KIRO_API_KEY", "TYPESAFE_API_KEY", "L4_GITHUB_APP_KEY",
    "OPENCODE_API_KEY", "COPILOT_GITHUB_TOKEN",
)  # fmt: skip
RUNNER_SECRET_ENV = ("CI_JOB_TOKEN",)  # the runner's own, always redacted: git may print it from an origin URL
CREDENTIAL_PATHS = {
    "codex": ("~/.codex",),
    "claude-code": ("~/.claude", "~/.claude.json"),
    "opencode": ("~/.local/share/opencode", "~/.config/opencode", "~/.cache/opencode"),
    "kiro-cli": (
        "~/.kiro",
        "~/.aws/sso/cache",
        "~/.local/share/kiro-cli",
        "~/Library/Application Support/kiro-cli",
    ),  # the login is in the CLI's data store (data.sqlite3, table auth_kv), not in ~/.kiro
    "copilot-cli": ("~/.copilot",),  # config.json can hold a plaintext token; never bound anywhere (NO_LOGIN_BIND)
}
CACHES = {
    "uv": ("$L4_CACHE/units/{unit}/cache/uv", "UV_CACHE_DIR", False),
    "pip": ("$L4_CACHE/units/{unit}/cache/pip", "PIP_CACHE_DIR", False),
    "npm": ("$L4_CACHE/units/{unit}/cache/npm", "npm_config_cache", False),
    "go": ("$L4_CACHE/units/{unit}/cache/go", "GOMODCACHE", False),
    "gobuild": ("$L4_CACHE/units/{unit}/cache/gobuild", "GOCACHE", False),
    "pnpm": ("$L4_CACHE/units/{unit}/cache/pnpm", "pnpm_config_store_dir", False),
    "playwright": ("$L4_CACHE/shared/ms-playwright", "PLAYWRIGHT_BROWSERS_PATH", True),
}  # name -> (path, env var, read_only)


def _home(environ: Mapping[str, str]) -> Path:
    return Path(environ["HOME"]) if environ.get("HOME") else Path.home()


def l4_home(environ: Mapping[str, str]) -> Path:
    """`$L4_HOME`, default `~/.local/share/l4`: user-local tools installed by `doctor --fix`."""
    value = environ.get("L4_HOME")
    return Path(value) if value else _home(environ) / ".local" / "share" / "l4"


COPILOT_CACHE_DIR = "copilot-cache"


def copilot_cache(environ: Mapping[str, str]) -> Path:
    """The Copilot CLI's package cache: `$L4_HOME/copilot-cache`, warmed at install and bound read-only into a sandbox
    (L4-PRV-048). The package lands in `<cache>/copilot/pkg/<platform>/<version>/`."""
    return l4_home(environ) / COPILOT_CACHE_DIR


def copilot_env(environ: Mapping[str, str]) -> dict[str, str]:
    """What a single `copilot` process that is not an agent run (a probe step, a `--version` read, the warm-up) gets
    on top of its environment: no auto-update, and the L4 package cache (L4-PRV-048)."""
    return {"COPILOT_AUTO_UPDATE": "false", "XDG_CACHE_HOME": str(copilot_cache(environ))}


def openspec_prefix(environ: Mapping[str, str]) -> Path:
    """The npm prefix PRQ-08 installed OpenSpec into (the one constant; see implementation-map M0)."""
    return l4_home(environ) / "npm"


def openspec_entrypoint(environ: Mapping[str, str]) -> Path:
    """`openspec.js`: run as `[<node>, <this>, ...]`, never through the `.bin` shim, `npx` or PATH (L4-OSP-001)."""
    return openspec_prefix(environ) / "node_modules" / OPENSPEC_PACKAGE / "bin" / "openspec.js"


def cache_root(environ: Mapping[str, str], *, repo: Path | None = None) -> Path:
    """`$L4_CACHE`, else `$XDG_CACHE_HOME/l4`, else `~/.cache/l4`; never inside `repo` (L4-CFG-005)."""
    explicit = environ.get("L4_CACHE")
    xdg = environ.get("XDG_CACHE_HOME")
    if explicit:
        root, source = Path(explicit), "L4_CACHE"
    elif xdg:
        root, source = Path(xdg) / "l4", "XDG_CACHE_HOME"
    else:
        root, source = _home(environ) / ".cache" / "l4", "HOME"
    if not root.is_absolute():
        raise L4Exit(ExitCode.USAGE_ERROR, f"{source} must be an absolute path (it names the runner cache)")
    if repo is not None:
        resolved, repo_real = root.resolve(), repo.resolve()
        if resolved == repo_real or repo_real in resolved.parents:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"the runner cache ({source}) must be outside the repository, but {resolved} is inside {repo_real}",
            )
    return root


def openspec_env(environ: Mapping[str, str], *, forbid: Iterable[Path] = ()) -> dict[str, str]:
    """The exact environment of every OpenSpec call (L4-OSP-001). The XDG directories are harness-owned and empty,
    so a runner user's global `defaultStore` cannot redirect the CLI to another repository (spikes/04)."""
    xdg = cache_root(environ) / "openspec-xdg"
    return {
        "PATH": safe_path(environ, forbid=forbid),
        "HOME": str(_home(environ)),
        "TZ": "UTC",
        "DO_NOT_TRACK": "1",
        "OPENSPEC_TELEMETRY": "0",
        "OPENSPEC_NO_UPDATE_CHECK": "1",
        "NO_COLOR": "1",
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_DATA_HOME": str(xdg / "data"),
    }


def resolve_executable(name: str, environ: Mapping[str, str], *, forbid: Iterable[Path] = ()) -> str | None:
    """Absolute path of `name` on the safe PATH (see `l4.safepath`). Doctor ENV-003 and the OpenSpec provider must
    both run the node this returns (L4-OSP-001)."""
    return resolve_tool(name, environ, forbid=forbid)


LESSONS_FILE = ".serena/memories/harness/lessons.md"
MAX_LESSONS = 40
MAX_LESSON_BYTES = 12000
SERENA_VERSION = "1.7.0"
LAYA_VERSION = "0.3.24"
PLAYWRIGHT_VERSION = "1.63.0"  # the Python playwright whose Chromium revision the shared browser cache must hold

# A line of `playwright install --dry-run chromium` that names a browser folder the gate needs (ENV-007 and the
# provisioning of Chromium read it alike, L4-ADO-020); the ffmpeg and other lines are not matched.
BROWSER_LOCATION = re.compile(r"^\s*Install location:\s*(\S*/(?:chromium|chromium_headless_shell)-\d+)\s*$", re.M)


def playwright_browsers_dir(environ: Mapping[str, str], *, repo: Path | None = None) -> Path:
    """Where the gate sandbox mounts the browsers, shared and read-only (`sandbox.caches.playwright`), and where
    runner provisioning installs Chromium: `<cache root>/shared/ms-playwright`."""
    return cache_root(environ, repo=repo) / "shared" / "ms-playwright"


def playwright_enabled(cfg: "L4Config") -> bool:
    """`auto` follows the e2e gate: on when `gates.e2e.command` is configured."""
    setting = cfg.verifier.playwright.enabled
    return bool(cfg.gates.e2e.command.strip()) if setting == "auto" else setting
