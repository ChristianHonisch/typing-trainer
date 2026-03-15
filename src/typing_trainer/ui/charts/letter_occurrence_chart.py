"""Letter occurrence percentage chart for the analysis tab.

Plots the share of each letter (as a percentage of all keystrokes) per
run, with one line per letter.  Hovering over a legend entry highlights
the corresponding line and dims the others.
"""

from __future__ import annotations

import pyqtgraph as pg
import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.charts.interactive_legend import InteractiveLegend
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

# Visually distinct colours for up to ~26 letters.  Picked to be
# readable on a dark background.
_PALETTE = [
    "#4a9e4a",  # green
    "#44aaff",  # blue
    "#ff4444",  # red
    "#cccc44",  # yellow
    "#cc66ff",  # purple
    "#44cccc",  # cyan
    "#cc8800",  # orange
    "#ff66aa",  # pink
    "#88cc44",  # lime
    "#aa44ff",  # violet
    "#44ffaa",  # mint
    "#ffaa44",  # gold
    "#4488cc",  # steel blue
    "#cc4488",  # magenta
    "#88cccc",  # teal
    "#ccaa88",  # tan
    "#8888ff",  # periwinkle
    "#ff8888",  # salmon
    "#88ff88",  # light green
    "#ffcc44",  # amber
    "#aa88cc",  # lavender
    "#88ccaa",  # sage
    "#cc8888",  # dusty rose
    "#aaccff",  # sky
    "#ffaacc",  # blush
    "#ccffaa",  # honeydew
]


class LetterOccurrenceChart(QWidget):
    """Per-letter occurrence percentage over run history."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._interactive_legend: InteractiveLegend | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._empty_label = QLabel("No occurrence data yet.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("left", "Share (%)", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Redraw with current data from the repository."""
        self._plot.clear()
        self._interactive_legend = None

        series = repo.get_per_letter_occurrence_series()
        if not series:
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._plot.setVisible(True)

        # Collect all letters that appear anywhere
        all_letters: set[str] = set()
        for _rid, pcts in series:
            all_letters.update(pcts.keys())

        # Sort letters alphabetically (space last)
        letters = sorted(all_letters - {" "}) + ([" "] if " " in all_letters else [])

        # Build x (run ids) and per-letter y arrays
        run_ids = [rid for rid, _ in series]
        x = np.array(run_ids, dtype=np.float64)

        curves: dict[str, pg.PlotDataItem] = {}

        legend = self._plot.addLegend(
            offset=(-10, 10),
            labelTextSize="9pt",
            colCount=2,
        )
        legend.setBrush(pg.mkBrush(30, 30, 30, 180))

        for i, letter in enumerate(letters):
            color = _PALETTE[i % len(_PALETTE)]
            y = np.array(
                [pcts.get(letter, 0.0) for _, pcts in series],
                dtype=np.float64,
            )

            display_name = "Space" if letter == " " else letter
            pen = pg.mkPen(color, width=1.5)
            curve = self._plot.plot(x, y, pen=pen, name=display_name)
            curves[display_name] = curve

        # Install interactive legend hover
        self._interactive_legend = InteractiveLegend(legend, curves)
