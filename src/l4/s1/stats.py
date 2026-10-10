"""Small statistics shared by the report and the audit (M16-G13, G14). Imports nothing from the scoring side, so the
audit, whose labels feed the next export, stays out of the engine-answer import graph."""

import math

Z95 = 1.96


def wilson(correct: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval of a proportion; (0, 1) when nothing was counted."""
    if n == 0:
        return 0.0, 1.0
    p = correct / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
