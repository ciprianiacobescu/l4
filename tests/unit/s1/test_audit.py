from pathlib import Path

import l4.s1.export as export
from l4.s1 import audit
from l4.s1 import questions as q
from l4.s1 import records as r

from ._make import make_item


def dataset(tmp_path: Path) -> tuple[Path, Path]:
    items = [
        make_item(f"{n:032x}", unit=f"openspec:u{n}", set_name=q.FILE_RELEVANT,
                  truth={"relevant": n % 2 == 0, "named": n % 4 == 0}, state=f"state {n}")
        for n in range(40)
    ]  # fmt: skip
    cal = tmp_path / "cal.jsonl"
    r.append_records([cal], items)
    out = tmp_path / "ds"
    # a seed whose split puts several units in test
    for seed in range(50):
        manifest = export.write_dataset(export.ground_truth_rows([cal]), out, seed=seed)
        if manifest["counts"]["rows"]["test"] >= 6:
            break
    return cal, out


def test_checklist_round_trip_and_disagreement_becomes_label(tmp_path: Path):
    cal, ds = dataset(tmp_path)
    checklist = tmp_path / "audit.md"
    n = audit.write_checklist(ds, checklist, sample=5, seed=3)
    assert n == 5
    assert audit.write_checklist(ds, tmp_path / "again.md", sample=5, seed=3) == 5
    assert checklist.read_text() == (tmp_path / "again.md").read_text()  # seeded
    text = checklist.read_text()
    keys = [line.split()[2] for line in text.splitlines() if line.startswith("### item ")]
    assert len(keys) == 5 and "deterministic label:" in text

    # mark: first agrees, second disagrees with the other label, third uses a name the set does not have,
    # fourth is skipped, fifth is gibberish
    second = keys[1]
    row = next(x for x in (ds / "test.jsonl").read_text().splitlines() if f"item:{second}" in x)
    flip = "out_of_scope" if '"relevant": true' in row else "relevant"
    answers = iter(["agree", f"disagree: {flip}", "disagree: perhaps", "", "maybe"])
    marked = [f"verdict: {next(answers)}" if line.startswith("verdict:") else line for line in text.splitlines()]
    checklist.write_text("\n".join(marked))

    labels_file = tmp_path / "audit-labels.jsonl"
    result = audit.import_checklist(checklist, ds, labels_file)
    assert (result.audited, result.agreed, result.disagreed, result.skipped) == (2, 1, 1, 1)
    assert len(result.invalid) == 2 and result.noise == 0.5
    low, high = result.noise_interval
    assert 0.0 < low < 0.5 < high < 1.0
    (label,) = [x for x in r.read_records(labels_file, ("label",)) if isinstance(x, r.LabelRecord)]
    assert label.item_key == second and label.source == "human:audit" and export.source_allowed(label.source)
    assert label.truth == {"relevant": flip == "relevant"}
    # the next export takes the human label over the deterministic one
    merged = export.ground_truth_rows([cal, labels_file])
    changed = next(x for x in merged.rows if x.item_key == second)
    assert changed.expected["relevant"] is (flip == "relevant") and "human_overrides_deterministic" in changed.tags
