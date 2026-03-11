"""Shared statistical helper functions and constants."""

from __future__ import annotations

import math
from typing import Sequence

# Hard cap: keystrokes with reaction_time_ms above this are excluded from
# RT analysis.  Values above 2 s are almost certainly pauses or distractions,
# not genuine motor responses.
RT_CAP_MS = 2000


def trimmed_mean(values: Sequence[int | float], fraction: float = 0.10) -> float:
    """Compute trimmed mean, removing ``fraction`` from each tail.

    Args:
        values: Sequence of numeric values.
        fraction: Fraction to trim from each end (0.10 = 10%).

    Returns:
        Trimmed mean.  Returns 0.0 for empty input.
    """
    if not values:
        return 0.0
    n = len(values)
    trim_count = int(math.floor(n * fraction))
    if trim_count * 2 >= n:
        # Not enough data to trim — use plain mean
        return sum(values) / n
    sorted_vals = sorted(values)
    trimmed = sorted_vals[trim_count : n - trim_count]
    return sum(trimmed) / len(trimmed)
