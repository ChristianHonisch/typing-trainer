"""Accuracy over time chart.

Line plot showing per-run accuracy with a 95% threshold reference line.
Failed runs are marked with red scatter points.
A secondary right Y-axis shows the number of unlocked (active) letters
as a step line.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)

_COLOR_LETTERS = "#888888"


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

        # Second Y-axis (right) for active letter count
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

        self._empty_label = QLabel("No runs recorded yet.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        layout.addWidget(self._plot)

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

        runs = repo.get_all_runs_summary()
        if not runs:
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._plot.setVisible(True)

        # Separate passed and failed runs
        x_all = np.array([i + 1 for i in range(len(runs))], dtype=np.float64)
        y_all = np.array([r.accuracy for r in runs], dtype=np.float64)

        x_failed = np.array(
            [i + 1 for i, r in enumerate(runs) if r.failed], dtype=np.float64
        )
        y_failed = np.array([r.accuracy for r in runs if r.failed], dtype=np.float64)

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

        # Active letter count on right axis (step line)
        letter_counts = repo.get_letter_count_at_runs()
        if letter_counts:
            # Build step data: duplicate each point to create horizontal
            # segments, then a vertical jump
            x_step: list[float] = []
            y_step: list[float] = []
            for i, (run_num, count) in enumerate(letter_counts):
                if i == 0:
                    x_step.append(float(run_num))
                    y_step.append(float(count))
                else:
                    # Horizontal segment at previous count up to this run
                    x_step.append(float(run_num))
                    y_step.append(y_step[-1])
                    # Vertical jump to new count
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

            counts_arr = np.array([c for _, c in letter_counts], dtype=np.float64)
            count_min = float(counts_arr.min())
            count_max = float(counts_arr.max())
            padding = max(1, (count_max - count_min) * 0.15)
            self._right_vb.setYRange(
                count_min - padding,
                count_max + padding,
                padding=0,
            )

        # Auto-range left y-axis
        self._plot.getViewBox().setYRange(
            max(0.5, float(y_all.min()) - 0.05), 1.02, padding=0
        )

        # Force geometry update
        self._update_right_vb()
