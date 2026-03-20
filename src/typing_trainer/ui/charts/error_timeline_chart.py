"""Error timeline chart for the analysis tab.

Plots all errors across training history with error type on the y-axis
(text labels) and run number on the x-axis.  Each error is an ``x``
marker, color-coded by category:

- **Same Column** (blue): correct column, wrong row
- **Same Finger** (orange): correct finger, wrong column
- **Same Row** (yellow): correct row, wrong finger
- **Mirror** (purple): homologous mirror position across hands
- **Swap** (orange): transposition pair (consecutive cognitive errors
  with expected/actual swapped)
- **Other** (grey): unclassified cognitive error
- **Motor Overflow** (red): unintentional double-tap
- **Burst Repeat** (dark yellow): stuck/held key
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from typing_trainer.models.error_types import classify_error
from typing_trainer.models.keyboard_layout import KeyboardLayout, load_keyboard
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_MIRROR,
    COLOR_OTHER_ERROR,
    COLOR_SAME_COLUMN,
    COLOR_SAME_FINGER,
    COLOR_SAME_ROW,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)

# Y-axis category order (bottom to top)
_CATEGORIES = [
    "Burst Repeat",
    "Motor Overflow",
    "Other",
    "Swap",
    "Mirror",
    "Same Row",
    "Same Finger",
    "Same Column",
]

_CATEGORY_COLORS = {
    "Same Column": COLOR_SAME_COLUMN,
    "Same Finger": COLOR_SAME_FINGER,
    "Same Row": COLOR_SAME_ROW,
    "Mirror": COLOR_MIRROR,
    "Swap": COLOR_ALERT,
    "Other": COLOR_OTHER_ERROR,
    "Motor Overflow": COLOR_ERROR,
    "Burst Repeat": "#cc4444",  # dark red — distinct from Same Finger yellow
}

_SUBTYPE_TO_LABEL = {
    "same_column": "Same Column",
    "same_finger": "Same Finger",
    "same_row": "Same Row",
    "mirror": "Mirror",
    "other": "Other",
}


class ErrorTimelineChart(QWidget):
    """Error type timeline across all training runs."""

    def __init__(
        self,
        keyboard_layout: KeyboardLayout | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._keyboard_layout = keyboard_layout or load_keyboard("qwertz")
        self._setup_ui()

    def set_keyboard_layout(self, keyboard_layout: KeyboardLayout) -> None:
        self._keyboard_layout = keyboard_layout

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._empty_label = QLabel("No error timeline data yet.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=False, alpha=0.15)
        self._plot.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Redraw with current data from the repository."""
        self._plot.clear()

        timeline = repo.get_error_timeline()
        if not timeline:
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._plot.setVisible(True)

        # ── Detect swaps ──
        # A swap is two consecutive cognitive errors within the same run
        # where expected₁ == actual₂ and actual₁ == expected₂.
        swap_indices: set[int] = set()
        for i in range(len(timeline) - 1):
            run1, exp1, act1, et1, _, _ = timeline[i]
            run2, exp2, act2, et2, _, _ = timeline[i + 1]
            if (
                et1 == "cognitive_error"
                and et2 == "cognitive_error"
                and run1 == run2
                and exp1 == act2
                and act1 == exp2
            ):
                swap_indices.add(i)
                swap_indices.add(i + 1)

        # ── Classify each error into a category ──
        # Per-category: collect (run_id, y with position-based offset)
        cat_data: dict[str, tuple[list[float], list[float]]] = {
            cat: ([], []) for cat in _CATEGORIES
        }

        for i, (
            run_id,
            expected,
            actual,
            error_type,
            position,
            target_length,
        ) in enumerate(timeline):
            if error_type == "motor_overflow":
                label = "Motor Overflow"
            elif error_type == "burst_repeat":
                label = "Burst Repeat"
            elif error_type == "cognitive_error":
                if i in swap_indices:
                    label = "Swap"
                else:
                    subtype = classify_error(
                        expected,
                        actual,
                        self._keyboard_layout,
                    )
                    label = _SUBTYPE_TO_LABEL.get(subtype, "Other")
            else:
                continue

            cat_y = _CATEGORIES.index(label)
            # Y-offset encodes relative position within the run
            # (bottom of band = start of run, top = end of run)
            relative = position / max(target_length, 1)
            offset = (relative - 0.5) * 0.4
            xs, ys = cat_data[label]
            xs.append(float(run_id))
            ys.append(cat_y + offset)

        # ── Plot each category as a separate scatter ──
        legend = self._plot.addLegend(offset=(-10, 10), labelTextSize="9pt")
        legend.setBrush(pg.mkBrush(30, 30, 30, 180))

        for cat in _CATEGORIES:
            xs, ys = cat_data[cat]
            if not xs:
                continue
            color = _CATEGORY_COLORS[cat]
            self._plot.plot(
                np.array(xs, dtype=np.float64),
                np.array(ys, dtype=np.float64),
                pen=None,
                symbol="x",
                symbolSize=8,
                symbolBrush=color,
                symbolPen=pg.mkPen(color, width=1.5),
                name=cat,
            )

        # ── Y-axis: category labels ──
        left_axis = self._plot.getAxis("left")
        ticks = [(float(i), cat) for i, cat in enumerate(_CATEGORIES)]
        left_axis.setTicks([ticks, []])
        left_axis.setStyle(tickFont=app_font(10))

        # ── Ranges ──
        all_run_ids = [t[0] for t in timeline]
        x_min = min(all_run_ids) - 1
        x_max = max(all_run_ids) + 1
        self._plot.getViewBox().setXRange(x_min, x_max, padding=0.02)
        self._plot.getViewBox().setYRange(-0.8, len(_CATEGORIES) - 0.2, padding=0)
