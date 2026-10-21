"""SCN-DLG-75: doctor `DLG-001` passes on the file `l4 init` writes once its delegate block is uncommented."""

from l4.doctor import checks_delegate as c
from l4.init.init import loaded_config, render_config

from ..init.test_init_delegate_block import uncomment


def test_the_uncommented_block_passes_dlg_001(make_ctx):
    cfg = loaded_config(uncomment(render_config("a" * 40)))
    ctx, _ = make_ctx(cfg=cfg)
    result = c._dlg_001(ctx)
    assert result.status == "pass", result.message
