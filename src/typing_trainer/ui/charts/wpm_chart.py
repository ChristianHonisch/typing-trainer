"""WPM over time chart, split by practice type.

Separate lines for each practice type (random_strings, random_words,
sentences) so speed can be compared across different practice modes.
Failed runs marked with red scatter points.  X-axis is global run
number to preserve chronological context.
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
}

_PRACTICE_LABELS: dict[str, str] = {
    "random_strings": "Random Strings",
    "random_words": "Random Words",
    "sentences": "Sentences",
}


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

        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._plot.clear()
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
