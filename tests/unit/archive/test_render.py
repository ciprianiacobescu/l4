from pathlib import Path

from l4.archive import labels_for, proposal_title, render_pr_body, render_pr_title


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "proposal.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_title_format_and_body_is_pure_function_of_state(tmp_path: Path):
    unit = write(tmp_path, "## Why\n\nShoppers expect to enter a discount code.\n\n## What Changes\n- x\n")
    assert proposal_title(unit) == "Shoppers expect to enter a discount code."
    assert render_pr_title("add-discount-codes", proposal_title(unit)) == (
        "[l4] add-discount-codes: Shoppers expect to enter a discount code."
    )
    args = ("openspec:add-discount-codes", "l4/openspec/add-discount-codes", "openspec/changes/x/verification.md")
    assert render_pr_body(*args, "https://gitlab.example.test/g/p") == render_pr_body(
        *args, "https://gitlab.example.test/g/p"
    )


def test_the_title_is_the_heading_without_a_leading_proposal_colon(tmp_path: Path):
    """M1.1 line 40: `# Proposal: average unit price` names the MR `[l4] add-x: average unit price`."""
    text = "# Proposal: average unit price\n\n## Why\nSales reports need the average price paid per unit.\n"
    assert proposal_title(write(tmp_path, text)) == "average unit price"
    assert render_pr_title("add-x", proposal_title(tmp_path)) == "[l4] add-x: average unit price"
    assert proposal_title(write(tmp_path, "# proposal:   Lower case\n")) == "Lower case"
    assert proposal_title(write(tmp_path, "# Add discount codes\n\ntext\n")) == "Add discount codes"
    assert proposal_title(write(tmp_path, "#  Proposal:Tight\n")) == "Tight"
    assert proposal_title(write(tmp_path, "# The Proposal: not leading\n")) == "The Proposal: not leading"


def test_the_title_falls_back_to_the_why_line_then_to_the_name(tmp_path: Path):
    assert proposal_title(write(tmp_path, "# Proposal:\n\n## Why\nThe reason.\n")) == "The reason."
    assert proposal_title(write(tmp_path, "## Why\n\nOnly a Why line.\n")) == "Only a Why line."
    assert proposal_title(write(tmp_path, "just words\n")) == ""
    assert render_pr_title("add-x", "") == "[l4] add-x"
    assert proposal_title(tmp_path / "nowhere") == ""


def test_proposal_text_cannot_break_the_title_line(tmp_path: Path):
    evil = "## Why\n\nfirst\x1b[31m line Draft: second\x00\n"
    title = render_pr_title("add-x", proposal_title(write(tmp_path, evil)))
    assert "\n" not in title and " " not in title and "\x1b" not in title and "\x00" not in title
    assert title.startswith("[l4] add-x: first")


def test_a_long_proposal_line_is_capped(tmp_path: Path):
    title = render_pr_title("add-x", proposal_title(write(tmp_path, "## Why\n\n" + "word " * 200)))
    assert len(title) <= 200 and title.endswith("...")


def test_a_symlinked_proposal_is_not_read(tmp_path: Path):
    secret = tmp_path / "outside.txt"
    secret.write_text("## Why\n\nSECRET\n")
    unit = tmp_path / "unit"
    unit.mkdir()
    (unit / "proposal.md").symlink_to(secret)
    assert proposal_title(unit) == ""


def test_the_body_says_any_merge_method_works():
    """W9: the harness detects a merge from the merge request and the tree, so a squash loses nothing it needs."""
    body = render_pr_body("openspec:x", "l4/openspec/x", "openspec/changes/x/verification.md", None)
    assert "Any merge method works" in body and "a squash drops them" in body
    assert "squashing discards" not in body and "Merge with the merge-commit method" not in body


def test_the_body_never_has_an_l4_run_line():
    body = render_pr_body("openspec:x", "l4/openspec/x", "openspec/changes/x/verification.md", "https://h.test/g/p")
    assert "L4-Run:" not in body and "\nL4-" not in "\n" + body


def test_body_links_the_evidence_on_the_unit_branch_and_advises_merge_commits():
    body = render_pr_body("openspec:x", "l4/openspec/x", "openspec/changes/x/verification.md", "https://h.test/g/p")
    assert "(https://h.test/g/p/-/blob/l4/openspec/x/openspec/changes/x/verification.md)" in body
    assert "never merges" in body
    plain = render_pr_body("openspec:x", "l4/openspec/x", "openspec/changes/x/verification.md", None)
    assert "`openspec/changes/x/verification.md`" in plain and "http" not in plain


def test_labels_are_one_phase_plus_needs_answers():
    assert labels_for("l4:", "implementing", needs_answers=False) == ["l4:implementing"]
    assert labels_for("l4:", "awaiting_human", needs_answers=True) == ["l4:awaiting_human", "l4:needs-answers"]


def test_heading_repeating_the_unit_name_falls_back_to_why(tmp_path: Path):
    """M1.8 R6 (live job 5561): `[l4] build-without-extra-modules: build-without-extra-modules`."""
    text = "# Proposal: build-without-extra-modules\n\n## Why\nThe index must build on Linux.\n"
    title = proposal_title(write(tmp_path, text), "build-without-extra-modules")
    assert title == "The index must build on Linux."
    assert render_pr_title("build-without-extra-modules", title) == (
        "[l4] build-without-extra-modules: The index must build on Linux."
    )
    spaced = "# Build without extra_modules\n\n## Why\nReason.\n"  # case, spaces, `-` and `_` do not make a title
    assert proposal_title(write(tmp_path, spaced), "build-without-extra-modules") == "Reason."


def test_heading_repeating_the_name_without_why_gives_the_bare_title(tmp_path: Path):
    unit = write(tmp_path, "# Proposal: add-x\n\nno why section\n")
    assert proposal_title(unit, "add-x") == ""
    assert render_pr_title("add-x", proposal_title(unit, "add-x")) == "[l4] add-x"
    assert proposal_title(unit) == "add-x"  # without the name nothing is known to repeat


def test_a_different_heading_is_kept_with_the_name_given(tmp_path: Path):
    assert proposal_title(write(tmp_path, "# Proposal: average unit price\n"), "add-x") == "average unit price"


def test_github_evidence_link():
    """L4-GHP-009, SCN-GHP-12: GitHub has no `/-/` in its blob URLs; GitLab keeps it."""
    args = ("openspec:x", "l4/openspec/x", "openspec/changes/x/verification.md", "https://github.com/o/r")
    github = render_pr_body(*args, platform="github")
    assert "(https://github.com/o/r/blob/l4/openspec/x/openspec/changes/x/verification.md)" in github
    assert "/-/blob/" not in github
    assert "/-/blob/" in render_pr_body(*args, platform="gitlab")
    assert "/-/blob/" in render_pr_body(*args)  # GitLab by default
