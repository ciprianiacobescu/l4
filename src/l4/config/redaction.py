"""The redactor once the config is known (L4-OBS-002): `observability.redact_env` plus every variable the config
names through a `*_env` key (`forge.token_env`, a profile's `api_key_env`, ...)."""

from collections.abc import Iterator, Mapping
from typing import Any

from l4.config.defaults import RUNNER_SECRET_ENV
from l4.config.loader import load_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.redact import Redactor

# `*_env` keys that name a variable holding something public: redacting a URL would only hide diagnostics.
NON_SECRET_ENV_KEYS = frozenset({"base_url_env"})


def _env_names(node: Any) -> Iterator[str]:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(key, str) and key.endswith("_env") and isinstance(value, str):
                if value and key not in NON_SECRET_ENV_KEYS:
                    yield value
            else:
                yield from _env_names(value)
    elif isinstance(node, list):
        for item in node:
            yield from _env_names(item)


def redactor_for_config(cfg: L4Config, environ: Mapping[str, str]) -> Redactor:
    names = {*cfg.observability.redact_env, *_env_names(cfg.model_dump()), *RUNNER_SECRET_ENV}
    return Redactor.from_env(sorted(names), environ)


def load_app_config(app: AppContext) -> tuple[AppContext, L4Config]:
    """Load the config (schema errors: exit 2) and widen `app.redactor` in place with the config-aware values. In
    place, because the log handler and `with_outcome` already hold that object: a copy would leave the stderr error
    line and `outcome.json` on the built-in list only."""
    cfg = load_config(app.repo, config_path=app.config_path)
    app.redactor.adopt(redactor_for_config(cfg, app.environ))
    app.redactor.forge_urls = None  # built for this config, on first use (`l4.forge.urls.app_forge_urls`)
    return app, cfg
