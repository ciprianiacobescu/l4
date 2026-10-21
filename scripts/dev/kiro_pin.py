"""Print what moving the Kiro CLI pin to a version needs (design D11): the `KIRO_SHA256` row, the `KIRO_DMG_SHA256`
entry and the `scripts/runner/prereqs.sh` lines, read from Kiro's `stable/index.json` (or a saved copy, `--index`).

    python scripts/dev/kiro_pin.py 2.32.0 [--index PATH]

Exits 1 when the version, or one of its four Linux zips, is not in the index. Maintenance only: the harness never
reads the index to install, and no test that runs offline fetches it. Recompute one digest over the downloaded bytes
before you paste (docs/live/pin-clis/README.md shows how).
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

INDEX_URL = "https://prod.download.cli.kiro.dev/stable/index.json"
# platform key -> (zip file name, prereqs.sh variable)
ZIPS = {
    "linux-x64": ("kirocli-x86_64-linux.zip", "KIRO_SHA256_X86_64"),
    "linux-arm64": ("kirocli-aarch64-linux.zip", "KIRO_SHA256_AARCH64"),
    "linux-x64-musl": ("kirocli-x86_64-linux-musl.zip", "KIRO_SHA256_X86_64_MUSL"),
    "linux-arm64-musl": ("kirocli-aarch64-linux-musl.zip", "KIRO_SHA256_AARCH64_MUSL"),
}
DMG = "Kiro CLI.dmg"


def load_index(source: str | None) -> dict:
    if source is not None:
        return json.loads(Path(source).read_text(encoding="utf-8"))
    with urllib.request.urlopen(INDEX_URL, timeout=60) as response:  # noqa: S310 (a fixed https URL)
        return json.loads(response.read())


def digests(index: dict, version: str) -> dict[str, str] | None:
    """The sha256 of each file of `version` by its file name, or None when the version is not listed."""
    for entry in index.get("versions", []):
        if entry.get("version") == version:
            return {p["download"].split("/", 1)[1]: p["sha256"] for p in entry.get("packages", [])}
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--index", help="a saved copy of stable/index.json (default: fetch it)")
    args = parser.parse_args(argv)
    files = digests(load_index(args.index), args.version)
    if files is None:
        print(f"kiro_pin: version {args.version} is not in the index", file=sys.stderr)
        return 1
    missing = [name for name, _var in ZIPS.values() if name not in files]
    if missing:
        print(f"kiro_pin: {args.version} has no {', '.join(missing)} in the index", file=sys.stderr)
        return 1
    print("# src/l4/provision/catalog.py: KIRO_SHA256")
    print(f'    "{args.version}": {{')
    for key, (name, _var) in ZIPS.items():
        print(f'        "{key}": "{files[name]}",')
    print("    },")
    print("# src/l4/provision/catalog.py: KIRO_DMG_SHA256")
    if DMG in files:
        print(f'    "{args.version}": "{files[DMG]}",')
    else:
        print(f"    # {args.version} has no disk image in the index")
    print("# scripts/runner/prereqs.sh, top block")
    print(f"KIRO_VERSION=${{KIRO_VERSION:-{args.version}}}")
    for _key, (name, var) in ZIPS.items():
        print(f"{var}=${{{var}:-{files[name]}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
