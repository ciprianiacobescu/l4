## MODIFIED Requirements

### Requirement: L4-VER-059 A person's reject decides a fix task's check
The `WHEN … THEN …` of a reject's reason SHALL be read from the reason that `human.verdict` records, which SHALL keep up to
4,000 characters; a longer reason that has such a sentence SHALL keep the sentence whole, from its last `WHEN`, and cut the
text before it (marked ` … `), so that the fix unit's scenario is the person's whole sentence.

#### Scenario: SCN-VER-262 (+) a long reject keeps its scenario whole
- **WHEN** a person rejects a finding with a reason of 4,500 characters that ends with `WHEN x THEN a test asserts that
  [...DEFAULT_ROLES].sort() deep-equals ["approver", "auditor"]`
- **THEN** `human.verdict.reason` is at most 4,000 characters and ends with that whole sentence, and the fix unit's scenario
  is `WHEN x` / `THEN a test asserts that [...DEFAULT_ROLES].sort() deep-equals ["approver", "auditor"]`

#### Scenario: SCN-VER-263 (−) a reason without a scenario, or whose sentence is longer than the limit, is cut at its end
- **WHEN** a reject's reason has 5,000 characters and no `WHEN … THEN …`, or a sentence of 3,900 characters
- **THEN** the recorded reason is its first 4,000 characters; a reason of at most 4,000 characters is recorded whole

### Requirement: L4-IMP-006 (7) a fix unit's text carries no human tag
Model- or person-written text that becomes a fix unit's or a follow-up unit's heading, task or proposal line SHALL turn a
bracket into a parenthesis only where it could form a tag: a pair whose content is letters, digits, `_`, `-` and
whitespace only, and every bracket without a partner. Any other pair SHALL stay as written.

#### Scenario: SCN-VER-264 (+) code brackets stay, tag brackets go
- **WHEN** a finding's text is `[test-infra] [...DEFAULT_ROLES].sort() deep-equals ["approver"] [ ] [x.[chore]`
- **THEN** the fix unit's task reads `(test-infra) [...DEFAULT_ROLES].sort() deep-equals ["approver"] ( ) (x.(chore)`, and
  neither tag pattern of the harness finds a tag in it
