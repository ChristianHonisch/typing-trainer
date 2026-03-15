"""Per-letter rolling accuracy chart.

Multi-line plot with one line per selected letter.  Letter visibility is
toggled via checkboxes on the left.  A 95% threshold reference line is shown.
"""

from __future__ import annotations

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
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)

_EMPTY_MSG = "No per-letter data yet."

# Distinct colors for up to ~12 letters (enough for a long time)
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


class PerLetterChart(QWidget):
    """Rolling accuracy per letter with letter-selector checkboxes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._letter_colors: dict[str, str] = {}
        self._repo: Repository | None = None
        self._series_cache: dict[str, list[tuple[int, float]]] = {}
        self._window = 200
        self._interactive_legend: InteractiveLegend | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)

        # Left: letter checkboxes
        self._checkbox_layout = QVBoxLayout()
        self._checkbox_layout.setSpacing(4)
        self._checkbox_container = QWidget()
        self._checkbox_container.setLayout(self._checkbox_layout)
        self._checkbox_container.setFixedWidth(80)
        outer.addWidget(self._checkbox_container)

        # Empty label
        self._empty_label = QLabel(_EMPTY_MSG)
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        outer.addWidget(self._empty_label)

        # Right: plot
        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "Accuracy", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getViewBox().setYRange(0.7, 1.02, padding=0)
        outer.addWidget(self._plot, stretch=1)

    def refresh(self, repo: Repository) -> None:
        """Reload data and rebuild checkboxes + plot."""
        self._repo = repo

        # Get all letters that have keystroke data
        error_rates = repo.get_per_letter_error_rates()
        if not error_rates:
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            self._checkbox_container.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._plot.setVisible(True)
        self._checkbox_container.setVisible(True)

        letters = sorted(error_rates.keys())

        # Assign stable colors
        for i, letter in enumerate(letters):
            if letter not in self._letter_colors:
                self._letter_colors[letter] = _LETTER_COLORS[i % len(_LETTER_COLORS)]

        # Update checkboxes: add new, remove gone
        existing = set(self._checkboxes.keys())
        needed = set(letters)

        for letter in existing - needed:
            cb = self._checkboxes.pop(letter)
            self._checkbox_layout.removeWidget(cb)
            cb.deleteLater()

        for letter in letters:
            if letter not in self._checkboxes:
                display = repr(letter) if letter == " " else letter
                cb = QCheckBox(display)
                cb.setFont(app_font(11))
                color = self._letter_colors[letter]
                cb.setStyleSheet(f"color: {color};")
                cb.setChecked(True)
                cb.stateChanged.connect(self._redraw)
                self._checkboxes[letter] = cb
                self._checkbox_layout.addWidget(cb)

        # Cache all series
        self._series_cache.clear()
        for letter in letters:
            self._series_cache[letter] = repo.get_per_letter_accuracy_series(
                letter, self._window
            )

        self._redraw()

    def _redraw(self) -> None:
        """Redraw visible lines based on checkbox state."""
        self._plot.clear()
        self._interactive_legend = None

        # 95% threshold
        threshold = pg.InfiniteLine(
            pos=0.95,
            angle=0,
            pen=pg.mkPen(
                COLOR_WARNING,
                width=1,
                style=pg.QtCore.Qt.PenStyle.DashLine,
            ),
        )
        self._plot.addItem(threshold)

        # Legend
        legend = self._plot.addLegend(
            offset=(10, -10),
            labelTextSize="9pt",
            colCount=2,
        )
        legend.setBrush(pg.mkBrush(30, 30, 30, 180))

        curves: dict[str, pg.PlotDataItem] = {}
        y_min = 0.9
        for letter, cb in self._checkboxes.items():
            if not cb.isChecked():
                continue
            series = self._series_cache.get(letter, [])
            if not series:
                continue

            # We use actual run_id as x so all letters share the same x-axis.
            x = np.array([run_id for run_id, _ in series], dtype=np.float64)
            y = np.array([acc for _, acc in series], dtype=np.float64)

            color = self._letter_colors.get(letter, "#cccccc")
            display_name = "Space" if letter == " " else letter
            pen = pg.mkPen(color, width=2)
            curve = self._plot.plot(x, y, pen=pen, name=display_name)
            curves[display_name] = curve

            if len(y) > 0:
                y_min = min(y_min, float(y.min()))

        if curves:
            self._interactive_legend = InteractiveLegend(
                legend,
                curves,
                normal_width=2,
            )

        self._plot.getViewBox().setYRange(max(0.5, y_min - 0.05), 1.02, padding=0)
