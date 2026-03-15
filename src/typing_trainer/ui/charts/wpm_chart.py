"""WPM over time chart, split by practice type.

Separate lines for each practice type (random_strings, random_words,
sentences) so speed can be compared across different practice modes.
Failed runs marked with red scatter points.  X-axis is global run
number to preserve chronological context.
A secondary right Y-axis shows the number of unlocked (active) letters
as a step line.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)

# Practice type display names and colors
_PRACTICE_COLORS: dict[str, str] = {
    "random_strings": COLOR_INFO,       # blue
    "random_words": COLOR_SUCCESS,      # green
    "sentences": COLOR_WARNING,         # yellow
    "fix_keys": COLOR_ERROR,            # red
}

_PRACTICE_LABELS: dict[str, str] = {
    "random_strings": "Random Strings",
    "random_words": "Random Words",
    "sentences": "Sentences",
    "fix_keys": "Fix Keys",
}

_COLOR_LETTERS = "#888888"


class WpmChart(QWidget):
    """Per-run WPM plotted chronologically, split by practice type."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "WPM", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)

        self._plot.addLegend(
            offset=(10, 10),
            labelTextColor=COLOR_TEXT_SECONDARY,
        )

        # Second Y-axis (right) for active letter count
        self._right_vb = pg.ViewBox()
        plot_item = self._plot.plotItem
        assert plot_item is not None
        plot_item.showAxis("right")
        plot_item.scene().addItem(self._right_vb)
        plot_item.getAxis("right").linkToView(self._right_vb)
        self._right_vb.setXLink(plot_item)
        plot_item.getAxis("right").setLabel("Letters", color=_COLOR_LETTERS)
        plot_item.getAxis("right").setTextPen(_COLOR_LETTERS)

        # Keep right ViewBox geometry in sync
        vb = plot_item.vb
        assert vb is not None
        vb.sigResized.connect(self._update_right_vb)

        layout.addWidget(self._plot)

    def _update_right_vb(self) -> None:
        plot_item = self._plot.plotItem
        assert plot_item is not None
        vb = plot_item.vb
        assert vb is not None
        self._right_vb.setGeometry(vb.sceneBoundingRect())

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._plot.clear()
        self._right_vb.clear()
        plot_item = self._plot.plotItem
        if plot_item is not None and plot_item.legend is not None:
            plot_item.legend.clear()

        runs = repo.get_all_runs_summary()
        if not runs:
            return

        # Group by practice type, keeping global run index
        groups: dict[str, list[tuple[int, float, bool]]] = defaultdict(list)
        for i, r in enumerate(runs):
            groups[r.practice_type].append((i + 1, r.wpm, r.failed))

        # Plot each practice type as a separate line
        for ptype in sorted(groups.keys()):
            entries = groups[ptype]
            color = _PRACTICE_COLORS.get(ptype, COLOR_TEXT_SECONDARY)
            label = _PRACTICE_LABELS.get(ptype, ptype)

            x = np.array([e[0] for e in entries], dtype=np.float64)
            y = np.array([e[1] for e in entries], dtype=np.float64)

            self._plot.plot(
                x,
                y,
                pen=pg.mkPen(color, width=2),
                symbol="o",
                symbolPen=color,
                symbolBrush=color,
                symbolSize=4,
                name=label,
            )

        # Failed runs as red X markers (across all types)
        x_failed = np.array(
            [i + 1 for i, r in enumerate(runs) if r.failed], dtype=np.float64
        )
        y_failed = np.array(
            [r.wpm for r in runs if r.failed], dtype=np.float64
        )

        if len(x_failed) > 0:
            self._plot.plot(
                x_failed,
                y_failed,
                pen=None,
                symbol="x",
                symbolPen=COLOR_ERROR,
                symbolBrush=COLOR_ERROR,
                symbolSize=10,
                name="Failed",
            )

        # Active letter count on right axis (step line)
        letter_counts = repo.get_letter_count_at_runs()
        if letter_counts:
            x_step: list[float] = []
            y_step: list[float] = []
            for i, (run_num, count) in enumerate(letter_counts):
                if i == 0:
                    x_step.append(float(run_num))
                    y_step.append(float(count))
                else:
                    x_step.append(float(run_num))
                    y_step.append(y_step[-1])
                    x_step.append(float(run_num))
                    y_step.append(float(count))
            # Extend to the end of the x-axis
            if len(runs) > 0:
                last_run = len(runs)
                if x_step[-1] < last_run:
                    x_step.append(float(last_run))
                    y_step.append(y_step[-1])

            letters_curve = pg.PlotDataItem(
                np.array(x_step, dtype=np.float64),
                np.array(y_step, dtype=np.float64),
                pen=pg.mkPen(_COLOR_LETTERS, width=1),
            )
            self._right_vb.addItem(letters_curve)

            counts_arr = np.array(
                [c for _, c in letter_counts], dtype=np.float64
            )
            count_min = float(counts_arr.min())
            count_max = float(counts_arr.max())
            padding = max(1, (count_max - count_min) * 0.15)
            self._right_vb.setYRange(
                count_min - padding, count_max + padding, padding=0,
            )

        # Force geometry update
        self._update_right_vb()
