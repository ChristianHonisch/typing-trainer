"""Accuracy over time chart.

Line plot showing per-run accuracy with a 95% threshold reference line.
Failed runs are marked with red scatter points.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)


class AccuracyChart(QWidget):
    """Per-run accuracy plotted chronologically."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "Accuracy", units=None, color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)

        # Y-axis as percentage
        self._plot.getViewBox().setYRange(0.7, 1.02, padding=0)

        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._plot.clear()

        runs = repo.get_all_runs_summary()
        if not runs:
            return

        # Separate passed and failed runs
        x_all = np.array([i + 1 for i in range(len(runs))], dtype=np.float64)
        y_all = np.array([r.accuracy for r in runs], dtype=np.float64)

        x_failed = np.array(
            [i + 1 for i, r in enumerate(runs) if r.failed], dtype=np.float64
        )
        y_failed = np.array(
            [r.accuracy for r in runs if r.failed], dtype=np.float64
        )

        # Main accuracy line
        self._plot.plot(
            x_all,
            y_all,
            pen=pg.mkPen(COLOR_SUCCESS, width=2),
            symbol=None,
        )

        # Failed runs as red markers
        if len(x_failed) > 0:
            self._plot.plot(
                x_failed,
                y_failed,
                pen=None,
                symbol="x",
                symbolPen=COLOR_ERROR,
                symbolBrush=COLOR_ERROR,
                symbolSize=10,
            )

        # 95% threshold line
        threshold = pg.InfiniteLine(
            pos=0.95,
            angle=0,
            pen=pg.mkPen(COLOR_WARNING, width=1, style=pg.QtCore.Qt.PenStyle.DashLine),
        )
        self._plot.addItem(threshold)

        # Auto-range x, keep y fixed
        self._plot.getViewBox().setYRange(
            max(0.5, float(y_all.min()) - 0.05), 1.02, padding=0
        )
