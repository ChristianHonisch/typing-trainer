"""Swap (transposition) visualization.

Shows the most frequently swapped bigrams as a horizontal bar chart.
A swap is two consecutive cognitive errors where the expected/actual
characters are transposed (e.g. typing "ne" instead of "en").

An optional filter limits the data to the most recent N keystrokes.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_DARK,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

_DEFAULT_LAST_N = 2000


class SwapChart(QWidget):
    """Horizontal bar chart of most-swapped bigrams."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repo: Repository | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # --- Filter controls ---
        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)

        self._limit_cb = QCheckBox("Limit to last")
        self._limit_cb.setFont(app_font(10))
        self._limit_cb.setChecked(True)
        self._limit_cb.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._limit_cb)

        self._limit_spin = QSpinBox()
        self._limit_spin.setFont(app_font(10))
        self._limit_spin.setRange(100, 999999)
        self._limit_spin.setSingleStep(500)
        self._limit_spin.setValue(_DEFAULT_LAST_N)
        self._limit_spin.setSuffix(" keys")
        self._limit_spin.valueChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._limit_spin)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

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

    def _get_last_n(self) -> int | None:
        """Return the last_n filter value, or None if unchecked."""
        if self._limit_cb.isChecked():
            return self._limit_spin.value()
        return None

    def _on_filter_changed(self) -> None:
        """Re-draw with the updated filter."""
        self._limit_spin.setEnabled(self._limit_cb.isChecked())
        if self._repo is not None:
            self._redraw()

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._repo = repo
        self._redraw()

    def _redraw(self) -> None:
        """Query and draw with current filter settings."""
        self._plot.clear()
        if self._repo is None:
            return

        last_n = self._get_last_n()
        swap_pairs = self._repo.get_swap_pairs(last_n=last_n)

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

        # Y-axis tick labels: "e<->n (12x)"
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
