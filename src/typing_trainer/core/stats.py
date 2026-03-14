"""Shared statistical helper functions and constants."""

from __future__ import annotations

import math
from collections import defaultdict
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


def _gliding_average(
    pos_values: list[tuple[int, float]], window: int,
) -> list[tuple[int, float]]:
    """Apply a centered gliding average over position-sorted (pos, value) pairs.

    Returns the same number of points with smoothed values.  At the
    edges the window shrinks symmetrically.
    """
    if not pos_values or window <= 1:
        return pos_values
    n = len(pos_values)
    result: list[tuple[int, float]] = []
    half = window // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        avg = sum(v for _, v in pos_values[lo:hi]) / (hi - lo)
        result.append((pos_values[i][0], avg))
    return result


def compute_position_baselines(
    raw: list[tuple[int, str, float]],
    settled_letters: set[str],
    smooth_window: int = 5,
) -> tuple[dict[int, float], dict[int, float], dict[int, float]]:
    """Compute per-position trimmed-mean RT baselines from historical data.

    Args:
        raw: List of ``(position, expected_char, reaction_time_ms)`` from
            :meth:`Repository.get_historical_position_rts`.
        settled_letters: Set of settled letter characters.
        smooth_window: Gliding average window for settled and space
            baselines (applied after trimmed mean per position).

    Returns:
        Three dicts mapping ``position -> trimmed_mean_rt``:
        ``(all_baseline, settled_baseline, space_baseline)``.
    """
    all_by_pos: dict[int, list[float]] = defaultdict(list)
    settled_by_pos: dict[int, list[float]] = defaultdict(list)
    space_by_pos: dict[int, list[float]] = defaultdict(list)

    for pos, char, rt in raw:
        all_by_pos[pos].append(rt)
        if char in settled_letters:
            settled_by_pos[pos].append(rt)
        if char == " ":
            space_by_pos[pos].append(rt)

    # Trimmed mean per position
    all_baseline: dict[int, float] = {
        pos: trimmed_mean(rts) for pos, rts in all_by_pos.items()
    }

    # Settled + space: trimmed mean then gliding average
    settled_raw = sorted(
        ((pos, trimmed_mean(rts)) for pos, rts in settled_by_pos.items()),
        key=lambda t: t[0],
    )
    settled_smoothed = _gliding_average(settled_raw, smooth_window)
    settled_baseline: dict[int, float] = dict(settled_smoothed)

    space_raw = sorted(
        ((pos, trimmed_mean(rts)) for pos, rts in space_by_pos.items()),
        key=lambda t: t[0],
    )
    space_smoothed = _gliding_average(space_raw, smooth_window)
    space_baseline: dict[int, float] = dict(space_smoothed)

    return all_baseline, settled_baseline, space_baseline
