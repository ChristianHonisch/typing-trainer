"""Motor-learning error type classification.

Classification priority:

1. mirror -- homologous position on the opposite hand
2. same_column -- correct physical column, wrong row
3. same_finger -- correct finger, wrong column
4. same_row -- correct row, wrong finger/column
5. other -- none of the above
"""

from __future__ import annotations

from typing import Literal

from typing_trainer.models.keyboard_layout import KeyboardLayout

ErrorCategory = Literal["mirror", "same_column", "same_finger", "same_row", "other"]


def classify_error(
    expected: str,
    actual: str,
    layout: KeyboardLayout,
) -> ErrorCategory:
    """Classify a confusion pair using a keyboard layout definition."""
    if expected == actual:
        return "other"

    if expected not in layout.fingers or actual not in layout.fingers:
        return "other"

    # 1. Mirror: explicit homologous pair across the center split.
    if layout.mirror_pairs.get(expected) == actual:
        return "mirror"

    # 2. Same physical column, wrong row.
    if layout.column_of.get(expected) == layout.column_of.get(actual):
        return "same_column"

    # 3. Same finger, wrong column. Important for index fingers that
    # cover two columns (and for future layouts with wider pinky usage).
    if layout.fingers.get(expected) == layout.fingers.get(actual):
        return "same_finger"

    # 4. Same row, wrong finger/column.
    if layout.row_of.get(expected) == layout.row_of.get(actual):
        return "same_row"

    return "other"
