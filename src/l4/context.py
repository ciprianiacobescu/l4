from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from l4.redact import Redactor

OUT_DIRNAME = ".l4-out"


@dataclass(frozen=True)
class AppContext:
    """What every command handler receives, built once per invocation from the common options."""

    repo: Path
    config_path: Path | None
    log_format: str  # "human" | "json"
    verbosity: int  # -q lowers, -v raises; 0 is the default
    run_id: str
    environ: Mapping[str, str]
    redactor: Redactor

    @property
    def out_dir(self) -> Path:
        return self.repo / OUT_DIRNAME
