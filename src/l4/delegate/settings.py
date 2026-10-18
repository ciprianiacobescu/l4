"""What the base branch says about the delegate (L4-DLG-001, D1): the `delegate:` section and `roles.delegate` of
`.l4/config.yaml` at `refs/remotes/origin/<base>`, never a unit branch or the working tree, so a branch cannot turn
the delegate on or change its limits."""

from dataclasses import dataclass, field

from l4.config.schema import DelegateCfg, Profile
from l4.vcs.git import Git
from l4.yolo.accept import target_full_config

REMOTE_REF = "refs/remotes/origin/"


@dataclass(frozen=True)
class DelegateSettings:
    delegate: DelegateCfg = field(default_factory=DelegateCfg)
    chain: list[str] = field(default_factory=list)  # `roles.delegate`
    profiles: dict[str, Profile] = field(default_factory=dict)  # the profiles the base defines


def delegate_settings(git: Git, base: str) -> DelegateSettings:
    """The defaults (`enabled: false`) when the file is absent, the base is unknown or the file is invalid."""
    full = target_full_config(git, f"{REMOTE_REF}{base}")
    if full is None:
        return DelegateSettings()
    return DelegateSettings(full.delegate, list(full.roles.delegate), dict(full.profiles))
