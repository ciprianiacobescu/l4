"""The experience graph (SPEC 13.1, L4-KG-001..014): a manual, derived index over the committed records of one
repository, with a report, a per-unit timeline and draft lesson proposals for a person.

Nothing on a run path imports this package (L4-KG-001, design D1): the only link is the handler string in
`l4.commands`. The package uses git read-only, and never the network, a model or a fetch.
"""
