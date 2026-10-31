## MODIFIED Requirements

### Requirement: L4-SEC-004 Protected paths
A `.gitattributes` file at any depth SHALL be a protected path of the contract list (any case), and the root one SHALL be
listed literally among the anchored roots; a change an agent step or a gate makes there SHALL be put back and recorded.

#### Scenario: SCN-SEC-120 (+) a `.gitattributes` file at any depth is a protected path
- **WHEN** the rules match `.gitattributes`, `src/.gitattributes`, `.GitAttributes` and the lookalike `.gitattributes.bak`
- **THEN** the first three are protected by `**/.gitattributes` and the lookalike is not

#### Scenario: SCN-SEC-121 (−) an agent's `.gitattributes` is put back, also behind an edited `.gitignore`
- **WHEN** a step writes `.gitattributes` with `*.py -diff`, and adds `.gitattributes` to `.gitignore`
- **THEN** the file is removed with `guard.violation{rule: "**/.gitattributes"}` and the step's production change stays
