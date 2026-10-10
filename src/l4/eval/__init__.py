"""`l4 eval` (M1.14): a fixed seed set run through the real implement and verify paths, scored into a scorecard, and a
regression gate that compares two scorecards (docs/eval.md).

No network from the harness: the only network in a real run is the agent CLIs' own, and `l4 eval --warm-cache` (the one
path allowed to reach an index) is explicit.
"""
