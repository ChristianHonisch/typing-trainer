"""Error rate per letter bar chart with stacked error-type segments.

Each letter's error bar is broken into stacked segments by motor-learning
error type (spatial, same-finger, mirror, other).  Total bar height
shows the overall error rate.

Sorted by error rate descending (worst letters first).

An optional filter limits the data to the most recent N keystrokes.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pyqtgraph as pg

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.models.error_types import ErrorCategory, classify_error
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_MIRROR,
    COLOR_OTHER_ERROR,
    COLOR_SAME_FINGER,
    COLOR_SPATIAL,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

# Stacking order (bottom to top)
_STACK_ORDER: list[ErrorCategory] = ["spatial", "same_finger", "mirror", "other"]

_CATEGORY_COLORS: dict[ErrorCategory, str] = {
    "spatial": COLOR_SPATIAL,
    "same_finger": COLOR_SAME_FINGER,
    "mirror": COLOR_MIRROR,
    "other": COLOR_OTHER_ERROR,
}

_CATEGORY_LABELS: dict[ErrorCategory, str] = {
    "spatial": "Spatial",
    "same_finger": "Same finger",
    "mirror": "Mirror",
    "other": "Other",
}

_DEFAULT_LAST_N = 2000


class ErrorHeatmap(QWidget):
    """Stacked bar chart of error rate per letter, by error type."""

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

        # Legend
        for cat in _STACK_ORDER:
            color = _CATEGORY_COLORS[cat]
            label_text = _CATEGORY_LABELS[cat]
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(
                f"background-color: {color}; border: 1px solid #555;"
            )
            text = QLabel(label_text)
            text.setFont(app_font(9))
            text.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            filter_layout.addWidget(swatch)
            filter_layout.addWidget(text)
            filter_layout.addSpacing(10)

        filter_layout.addStretch()

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

        layout.addLayout(filter_layout)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setLabel("left", "Error Rate %", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Letter", color=COLOR_TEXT_PRIMARY)
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
        error_rates = self._repo.get_per_letter_error_rates(last_n=last_n)
        if not error_rates:
            return

        # Get confusion pairs to classify error types per letter
        confusion_pairs = self._repo.get_confusion_pairs(last_n=last_n)

        # Build per-letter error-type counts
        # letter -> category -> count
        type_counts: dict[str, dict[ErrorCategory, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for expected, actual, count in confusion_pairs:
            cat = classify_error(expected, actual)
            type_counts[expected][cat] += count

        # Sort by error rate descending
        sorted_letters = sorted(
            error_rates.items(), key=lambda item: item[1][2], reverse=True
        )

        letters = [letter for letter, _ in sorted_letters]
        totals = [data[1] for _, data in sorted_letters]
        total_errors = [data[0] for _, data in sorted_letters]

        n = len(letters)
        x = np.arange(n, dtype=np.float64)

        # Build stacked bars
        bottoms = np.zeros(n, dtype=np.float64)

        for cat in _STACK_ORDER:
            heights = np.zeros(n, dtype=np.float64)
            for i, letter in enumerate(letters):
                total = totals[i]
                if total > 0 and letter in type_counts:
                    cat_count = type_counts[letter].get(cat, 0)
                    heights[i] = (cat_count / total) * 100
                else:
                    heights[i] = 0.0

            if np.any(heights > 0):
                bar = pg.BarGraphItem(
                    x=x,
                    height=heights,
                    width=0.6,
                    y0=bottoms,
                    brush=QColor(_CATEGORY_COLORS[cat]),
                )
                self._plot.addItem(bar)

            bottoms = bottoms + heights

        # Set x-axis tick labels
        display_labels = ["SPC" if l == " " else l for l in letters]
        ticks = [list(zip(x.tolist(), display_labels))]
        self._plot.getAxis("bottom").setTicks(ticks)

        # Add text labels showing total count on top of each bar
        for i, (errors, total) in enumerate(zip(total_errors, totals)):
            top = float(bottoms[i])
            text = pg.TextItem(
                f"n={total}",
                color=COLOR_TEXT_SECONDARY,
                anchor=(0.5, 1.0),
            )
            text.setPos(float(x[i]), top)
            self._plot.addItem(text)
