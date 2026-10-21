import sys

from ._tune import S1, load


def test_vendored_script_matches_pinned_sha(tmp_path):
    check = load("check_vendor")
    assert check.mismatches() == []
    copy = tmp_path / "vendor"
    copy.mkdir()
    (copy / "SHA256").write_text((S1 / "vendor" / "SHA256").read_text())
    (copy / "laya_finetune_mps.py").write_text("# edited\n")
    assert check.mismatches(copy) == ["laya_finetune_mps.py"]


def test_script_helpers_import_without_torch():
    load("laya_tune")
    assert "torch" not in sys.modules
