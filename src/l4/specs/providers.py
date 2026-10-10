"""Which providers a repository uses: the frameworks `spec.frameworks` names, or what detection finds (SPEC 4.1).

Spec Kit is detected and reported by doctor, never driven. M1: spec-providers 4.2 (`primary_framework`).
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.config.schema import L4Config
from l4.specs.base import Framework, ProviderRegistry, SpecProvider, UnknownUnit
from l4.specs.detect import active_frameworks
from l4.specs.kiro import KiroProvider
from l4.specs.openspec import OpenSpecProvider


def providers_for(cfg: L4Config, repo: Path, environ: Mapping[str, str]) -> list[SpecProvider]:
    """OpenSpec first, then Kiro; none when the repository has no framework (`run` alone turns that into exit 14)."""
    registry = ProviderRegistry()
    for framework in active_frameworks(cfg, repo):
        if framework is Framework.OPENSPEC:
            registry.register(OpenSpecProvider(repo, environ, root=cfg.spec.openspec.root))
        else:
            registry.register(
                KiroProvider(
                    repo, root=cfg.spec.kiro.root, enforce=cfg.sdd.enforce, exempt_kinds=cfg.tdd.exempt_task_kinds
                )
            )
    return registry.providers()


def provider_for_unit(providers: Sequence[SpecProvider], unit_id: str) -> SpecProvider:
    """The provider whose framework starts the unit id (`kiro:greet` -> Kiro)."""
    framework = unit_id.partition(":")[0]
    for provider in providers:
        if provider.framework.value == framework:
            return provider
    raise UnknownUnit(f"no spec provider is active for {unit_id}")
