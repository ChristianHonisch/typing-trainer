"""WPM over time chart, split by practice type and capitalization.

Separate lines for each (practice_type, capitalize) combination so
speed can be compared across different practice modes and settings.
Failed runs marked with red scatter points.  X-axis is global run
number to preserve chronological context.
A secondary right Y-axis shows the number of unlocked (active) letters
as a step line.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_MIRROR,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)

# Display names and colors keyed by (practice_type, capitalize).
# Entries without a capitalize variant use False as default.
_GROUP_COLORS: dict[tuple[str, bool], str] = {
    ("random_strings", False): COLOR_INFO,  # blue
    ("random_words", False): COLOR_SUCCESS,  # green
    ("random_words", True): "#2d8a2d",  # darker green
    ("sentences", False): COLOR_WARNING,  # yellow
    ("sentences", True): "#aaaa33",  # darker yellow
    ("bigram_words", False): COLOR_MIRROR,  # purple
    ("bigram_words", True): "#9944cc",  # darker purple
    ("fix_keys", False): COLOR_ALERT,  # orange
}

_GROUP_LABELS: dict[tuple[str, bool], str] = {
    ("random_strings", False): "Random Strings",
    ("random_words", False): "Words",
    ("random_words", True): "Words (Caps)",
    ("sentences", False): "Sentences",
    ("sentences", True): "Sentences (Caps)",
    ("bigram_words", False): "Bigrams",
    ("bigram_words", True): "Bigrams (Caps)",
    ("fix_keys", False): "Fix Keys",
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
        self._right_y_range: tuple[float, float] | None = None
        self._right_vb = pg.ViewBox()
        plot_item = self._plot.plotItem
        if plot_item is None:
            return
        plot_item.showAxis("right")
        plot_item.scene().addItem(self._right_vb)
        plot_item.getAxis("right").linkToView(self._right_vb)
        self._right_vb.setXLink(plot_item)
        plot_item.getAxis("right").setLabel("Letters", color=_COLOR_LETTERS)
        plot_item.getAxis("right").setTextPen(_COLOR_LETTERS)

        # Keep right ViewBox geometry in sync
        vb = plot_item.vb
        if vb is None:
            return
        vb.sigResized.connect(self._update_right_vb)
        vb.sigRangeChanged.connect(self._on_main_range_changed)

        self._empty_label = QLabel("No runs recorded yet.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        layout.addWidget(self._plot)

    def _on_main_range_changed(self) -> None:
        """Re-apply the right Y-axis range when the main ViewBox resets."""
        if self._right_y_range is not None:
            self._right_vb.setYRange(*self._right_y_range, padding=0)

    def _update_right_vb(self) -> None:
        plot_item = self._plot.plotItem
        if plot_item is None:
            return
        vb = plot_item.vb
        if vb is None:
            return
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
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._plot.setVisible(True)

        # Group by (practice_type, capitalize), keeping global run index
        groups: dict[tuple[str, bool], list[tuple[int, float, bool]]] = defaultdict(
            list
        )
        for i, r in enumerate(runs):
            key = (r.practice_type, r.capitalize)
            groups[key].append((i + 1, r.wpm, r.failed))

        # Plot each group as a separate line
        for group_key in sorted(groups.keys()):
            entries = groups[group_key]
            color = _GROUP_COLORS.get(group_key, COLOR_TEXT_SECONDARY)
            label = _GROUP_LABELS.get(group_key, f"{group_key[0]}")

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
        y_failed = np.array([r.wpm for r in runs if r.failed], dtype=np.float64)

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

        # Active letter count on right axis (step line).
        # stepMode="right" draws _| shapes: the horizontal segment
        # extends through the run, then jumps at the end.
        letter_counts = repo.get_letter_count_at_runs()
        if letter_counts:
            runs_arr_lc = np.array([r for r, _ in letter_counts], dtype=np.float64)
            counts_arr_lc = np.array([c for _, c in letter_counts], dtype=np.float64)
            letters_curve = pg.PlotDataItem(
                runs_arr_lc,
                counts_arr_lc,
                pen=pg.mkPen(_COLOR_LETTERS, width=1),
                stepMode="right",
            )
            self._right_vb.addItem(letters_curve)

            counts_arr = np.array([c for _, c in letter_counts], dtype=np.float64)
            count_min = float(counts_arr.min())
            count_max = float(counts_arr.max())
            padding = max(1, (count_max - count_min) * 0.15)
            self._right_y_range = (count_min - padding, count_max + padding)
            self._right_vb.setYRange(*self._right_y_range, padding=0)

        # Force geometry update
        self._update_right_vb()
