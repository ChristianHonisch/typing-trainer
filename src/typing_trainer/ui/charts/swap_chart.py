"""Swap (transposition) visualization.

Shows the most frequently swapped bigrams as a horizontal bar chart.
A swap is two consecutive cognitive errors where the expected/actual
characters are transposed (e.g. typing "ne" instead of "en").
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_DARK,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)


class SwapChart(QWidget):
    """Horizontal bar chart of most-swapped bigrams."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._empty_label = QLabel("No swap errors detected yet.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=False, alpha=0.15)
        self._plot.setLabel("bottom", "Swap Count", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel(
            "left", "Bigram Pair", color=COLOR_TEXT_PRIMARY
        )
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)

        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._plot.clear()

        swap_pairs = repo.get_swap_pairs()

        if not swap_pairs:
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._plot.setVisible(True)

        # Reverse so highest count is at the top
        pairs = list(reversed(swap_pairs))
        n = len(pairs)

        y_positions = np.arange(n, dtype=np.float64)
        widths = np.array([count for _, _, count in pairs], dtype=np.float64)

        bar = pg.BarGraphItem(
            x0=np.zeros(n, dtype=np.float64),
            y=y_positions,
            width=widths,
            height=0.6,
            brush=COLOR_ALERT,
        )
        self._plot.addItem(bar)

        # Y-axis tick labels: "e↔n (12×)"
        labels = []
        for char_a, char_b, count in pairs:
            a_label = "SPC" if char_a == " " else char_a
            b_label = "SPC" if char_b == " " else char_b
            labels.append(f"{a_label}\u2194{b_label} ({count}\u00d7)")

        ticks = [list(zip(y_positions.tolist(), labels))]
        self._plot.getAxis("left").setTicks(ticks)

        # Add count text at bar end
        for i, (_, _, count) in enumerate(pairs):
            text = pg.TextItem(
                str(count),
                color=COLOR_TEXT_SECONDARY,
                anchor=(0.0, 0.5),
            )
            text.setPos(float(widths[i]), float(y_positions[i]))
            self._plot.addItem(text)
