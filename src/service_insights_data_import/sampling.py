"""Small weighted-random helpers shared by the generators."""

import random


def weighted_choice(weights: dict, rng: random.Random):
    """Pick one key from a {value: weight} dict. Weights need not sum to 1."""
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
