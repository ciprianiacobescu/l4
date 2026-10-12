"""`dispatch_continuation` on the forges without a dispatch (github-parity L4-GHP-004): they say so."""

from l4.forge.local import LocalForge


def test_local_forge_cannot_dispatch():
    assert LocalForge().dispatch_continuation("main") == "unsupported"
