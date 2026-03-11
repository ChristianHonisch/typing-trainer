"""Motor-learning error type classification for QWERTZ layout.

Classifies a confusion pair ``(expected_char, actual_char)`` into one of
four categories based on the physical keyboard layout:

- **spatial**: keys are physically adjacent on QWERTZ
- **same_finger**: keys use the same finger but are not adjacent
- **mirror**: keys are on mirror-symmetric finger positions (homologous)
- **other**: none of the above (phonological, anticipation, etc.)

Priority when multiple categories apply: spatial > same_finger > mirror > other.
"""

from __future__ import annotations

from typing import Literal

from typing_trainer.models.keyboard_layout import QWERTZ_FINGER_MAP

ErrorCategory = Literal["spatial", "same_finger", "mirror", "other"]

# ---------------------------------------------------------------------------
# QWERTZ physical layout — adjacency map
# ---------------------------------------------------------------------------
#
# Key positions on a standard QWERTZ keyboard (with row stagger):
#
#   Row 0:  q   w   e   r   t   z   u   i   o   p
#   Row 1:   a   s   d   f   g   h   j   k   l
#   Row 2:    y   x   c   v   b   n   m
#
# Adjacency includes same-row horizontal neighbors and diagonal neighbors
# on adjacent rows (accounting for the ~0.25-key and ~0.5-key stagger).

_ROW0 = list("qwertzuiop")
_ROW1 = list("asdfghjkl")
_ROW2 = list("yxcvbnm")

# Row offsets (in key-widths) to compute stagger-aware adjacency.
# Row 0 starts at 0.0, Row 1 at ~0.25, Row 2 at ~0.75.
_ROWS: list[tuple[list[str], float]] = [
    (_ROW0, 0.0),
    (_ROW1, 0.25),
    (_ROW2, 0.75),
]


def _build_adjacency() -> dict[str, set[str]]:
    """Build adjacency map from physical key positions."""
    # Compute (row, col_offset) for each key
    pos: dict[str, tuple[int, float]] = {}
    for row_idx, (row_keys, offset) in enumerate(_ROWS):
        for col_idx, key in enumerate(row_keys):
            pos[key] = (row_idx, col_idx + offset)

    adj: dict[str, set[str]] = {k: set() for k in pos}

    keys = list(pos.keys())
    for i, k1 in enumerate(keys):
        r1, c1 = pos[k1]
        for k2 in keys[i + 1 :]:
            r2, c2 = pos[k2]
            row_dist = abs(r1 - r2)
            col_dist = abs(c1 - c2)

            # Adjacent if: same row and 1 apart, or adjacent rows and
            # column distance <= 1.0 (accounting for stagger)
            is_adjacent = False
            if row_dist == 0 and col_dist <= 1.0 and col_dist > 0:
                is_adjacent = True
            elif row_dist == 1 and col_dist <= 1.0:
                is_adjacent = True

            if is_adjacent:
                adj[k1].add(k2)
                adj[k2].add(k1)

    return adj


QWERTZ_ADJACENCY: dict[str, set[str]] = _build_adjacency()
"""Physical adjacency on QWERTZ: key → set of neighboring keys."""

# ---------------------------------------------------------------------------
# Mirror finger pairs (homologous keys)
# ---------------------------------------------------------------------------
#
# Fingers: 0=L-pinky, 1=L-ring, 2=L-middle, 3=L-index,
#          6=R-index, 7=R-middle, 8=R-ring, 9=R-pinky.
# Mirror pairs: 0↔9, 1↔8, 2↔7, 3↔6.

_MIRROR_FINGER: dict[int, int] = {
    0: 9, 9: 0,
    1: 8, 8: 1,
    2: 7, 7: 2,
    3: 6, 6: 3,
}


def classify_error(expected: str, actual: str) -> ErrorCategory:
    """Classify a confusion pair by its motor-learning error type.

    Args:
        expected: The character that should have been typed.
        actual: The character that was actually typed.

    Returns:
        One of ``"spatial"``, ``"same_finger"``, ``"mirror"``, or ``"other"``.

    Priority: spatial > same_finger > mirror > other.
    If either character is not in the QWERTZ letter map (e.g. space),
    returns ``"other"``.
    """
    if expected == actual:
        return "other"

    # Characters not in the finger map (e.g. space) → other
    if expected not in QWERTZ_FINGER_MAP or actual not in QWERTZ_FINGER_MAP:
        return "other"

    # 1. Spatial: physically adjacent keys
    if expected in QWERTZ_ADJACENCY and actual in QWERTZ_ADJACENCY[expected]:
        return "spatial"

    # 2. Same finger, different key
    if QWERTZ_FINGER_MAP[expected] == QWERTZ_FINGER_MAP[actual]:
        return "same_finger"

    # 3. Homologous mirror: symmetric finger positions across hands
    finger_exp = QWERTZ_FINGER_MAP[expected]
    finger_act = QWERTZ_FINGER_MAP[actual]
    if finger_exp in _MIRROR_FINGER and _MIRROR_FINGER[finger_exp] == finger_act:
        return "mirror"

    return "other"
