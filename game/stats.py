"""The arithmetic behind the README's error bars.

Sixty games per cell is a small sample, and the README says so with
numbers: a Wilson interval on every win rate and a two-proportion z-score
between policies. Both live here so the benchmark prints them and the tests
pin them, instead of being worked out by hand once and pasted.
"""
from __future__ import annotations

import math

Z95 = 1.959964   # two-sided 95% normal quantile


def wilson_interval(wins: int, games: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, as (low, high).

    Chosen over the textbook normal approximation because it behaves at the
    edges: a 60/60 cell gets a lower bound near 94% instead of a zero-width
    interval at 100%, and a small sample never yields a negative bound.
    """
    if games <= 0:
        raise ValueError("games must be positive")
    p = wins / games
    z2 = z * z
    denom = 1.0 + z2 / games
    centre = (p + z2 / (2.0 * games)) / denom
    half = z * math.sqrt(p * (1.0 - p) / games + z2 / (4.0 * games * games)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_z(wins_a: int, games_a: int,
                     wins_b: int, games_b: int) -> float:
    """Pooled two-proportion z statistic for win rate A against win rate B.

    Positive when A wins more often. The pooled two-sample form treats the
    samples as independent and ignores that the benchmark pairs seeds across
    policies, which makes it the conservative choice here: the pairing can
    only add evidence a paired test would count.
    """
    pooled = (wins_a + wins_b) / (games_a + games_b)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / games_a + 1.0 / games_b))
    if se == 0.0:                     # both rates are 0 or both are 1
        return 0.0
    return (wins_a / games_a - wins_b / games_b) / se
