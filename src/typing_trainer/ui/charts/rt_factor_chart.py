"""Per-letter RT Factor trend over time.

Shows how each letter's RT compares to space (the baseline) across runs.
Factor = letter_median_rt / space_median_rt per run.
Lower is better; below 1.25 = mastery range.

One line per letter, toggled via checkboxes.  Interactive legend
with hover-to-highlight.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.charts.interactive_legend import InteractiveLegend
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)

_EMPTY_MSG = "No RT data yet."

_LETTER_COLORS = [
    "#4a9e4a",  # green
    "#44aaff",  # blue
    "#ff4444",  # red
    "#cccc44",  # yellow
    "#cc44cc",  # magenta
    "#44cccc",  # cyan
    "#ff8844",  # orange
    "#88ff44",  # lime
    "#8844ff",  # purple
    "#ff44aa",  # pink
    "#44ff88",  # mint
    "#ffaa44",  # gold
]

_MIN_RTS_PER_RUN = 3
"""Minimum keystrokes per run for a reliable median."""


class RtFactorChart(QWidget):
    """Per-letter RT Factor trend over runs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._letter_colors: dict[str, str] = {}
        self._repo: Repository | None = None
        self._letter_series: dict[str, list[tuple[int, float]]] = {}
        self._space_medians: dict[int, float] = {}
        self._interactive_legend: InteractiveLegend | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)

        # Checkbox panel (left)
        self._checkbox_container = QWidget()
        self._checkbox_container.setFixedWidth(80)
        self._checkbox_layout = QVBoxLayout(self._checkbox_container)
        self._checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self._checkbox_layout.setSpacing(2)
        self._checkbox_layout.addStretch()
        outer.addWidget(self._checkbox_container)

        # Right panel: plot
        right = QVBoxLayout()

        self._empty_label = QLabel(_EMPTY_MSG)
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        right.addWidget(self._empty_label)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "RT Factor", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Run", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        right.addWidget(self._plot)

        outer.addLayout(right, stretch=1)

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._repo = repo
        self._letter_series.clear()
        self._space_medians.clear()

        # Get letters that have data
        error_rates = repo.get_per_letter_error_rates()
        letters = sorted(error_rates.keys())

        if not letters:
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._plot.setVisible(True)

        # Assign colors
        for i, letter in enumerate(letters):
            if letter not in self._letter_colors:
                self._letter_colors[letter] = _LETTER_COLORS[i % len(_LETTER_COLORS)]

        # Get space RT series for baseline
        space_series = repo.get_per_letter_rt_series(" ")
        for run_id, rts in space_series:
            if len(rts) >= _MIN_RTS_PER_RUN:
                sorted_rts = sorted(rts)
                self._space_medians[run_id] = float(sorted_rts[len(sorted_rts) // 2])

        # Get per-letter RT series and compute factor per run
        for letter in letters:
            if letter == " ":
                continue
            raw = repo.get_per_letter_rt_series(letter)
            factors: list[tuple[int, float]] = []
            for run_id, rts in raw:
                if len(rts) < _MIN_RTS_PER_RUN:
                    continue
                space_med = self._space_medians.get(run_id)
                if space_med is None or space_med <= 0:
                    continue
                sorted_rts = sorted(rts)
                letter_median = float(sorted_rts[len(sorted_rts) // 2])
                factors.append((run_id, letter_median / space_med))
            if factors:
                self._letter_series[letter] = factors

        # Sync checkboxes
        existing = set(self._checkboxes.keys())
        needed = set(self._letter_series.keys())

        for letter in existing - needed:
            cb = self._checkboxes.pop(letter)
            self._checkbox_layout.removeWidget(cb)
            cb.deleteLater()

        for letter in sorted(needed - existing):
            display = repr(letter) if letter == " " else letter
            cb = QCheckBox(display)
            cb.setFont(app_font(11))
            cb.setChecked(True)
            color = self._letter_colors.get(letter, "#ffffff")
            cb.setStyleSheet(f"color: {color};")
            cb.stateChanged.connect(self._redraw)
            idx = self._checkbox_layout.count() - 1
            self._checkbox_layout.insertWidget(idx, cb)
            self._checkboxes[letter] = cb

        self._redraw()

    def _redraw(self) -> None:
        """Clear and redraw all visible lines."""
        self._plot.clear()
        self._interactive_legend = None

        # Mastery threshold line (1.25x)
        mastery_line = pg.InfiniteLine(
            pos=1.25,
            angle=0,
            pen=pg.mkPen(COLOR_SUCCESS, width=1, style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(mastery_line)

        # Stable threshold line (1.50x)
        stable_line = pg.InfiniteLine(
            pos=1.50,
            angle=0,
            pen=pg.mkPen(COLOR_WARNING, width=1, style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(stable_line)

        legend = self._plot.addLegend(offset=(10, 10), labelTextSize="9pt", colCount=2)

        curves: dict[str, pg.PlotDataItem] = {}
        y_max = 2.0

        for letter, cb in sorted(self._checkboxes.items()):
            if not cb.isChecked():
                continue
            series = self._letter_series.get(letter)
            if not series:
                continue

            x = np.array([run_id for run_id, _ in series], dtype=np.float64)
            y = np.array([factor for _, factor in series], dtype=np.float64)

            y_max = max(y_max, float(y.max()))

            color = self._letter_colors.get(letter, "#ffffff")
            display = repr(letter) if letter == " " else letter
            pen = pg.mkPen(color, width=2)
            curve = self._plot.plot(x, y, pen=pen, name=display)
            curves[display] = curve

        self._plot.getViewBox().setYRange(0.8, min(y_max * 1.1, 3.0), padding=0)

        if legend is not None and curves:
            self._interactive_legend = InteractiveLegend(legend, curves, normal_width=2)
