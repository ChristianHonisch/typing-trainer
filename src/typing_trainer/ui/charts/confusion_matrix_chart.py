"""Confusion matrix visualization: top-N bar chart + grid heatmap.

Shows which letters get confused with which, color-coded by motor-learning
error type (spatial, same-finger, mirror, other).

Confusion rates are **normalized**: each pair's count is divided by the
total number of scored keystrokes for the expected letter, giving a
percentage that is comparable across letters with different amounts of
training.

Filters:
  - Only letters with >= 20 total scored keystrokes are shown.
  - Only confusion pairs with >= 2 occurrences are shown.
  - Optional recency filter: limit to last N keystrokes.

Top section: horizontal bar chart of the highest confusion rates.
Bottom section: grid heatmap (ImageItem) with letters on both axes.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt

from typing_trainer.models.error_types import ErrorCategory, classify_error
from typing_trainer.models.keyboard_layout import KeyboardLayout, load_keyboard
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_MIRROR,
    COLOR_OTHER_ERROR,
    COLOR_SAME_FINGER,
    COLOR_SAME_COLUMN,
    COLOR_SAME_ROW,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

# Map error categories to colors
_CATEGORY_COLORS: dict[ErrorCategory, str] = {
    "mirror": COLOR_MIRROR,
    "same_column": COLOR_SAME_COLUMN,
    "same_finger": COLOR_SAME_FINGER,
    "same_row": COLOR_SAME_ROW,
    "other": COLOR_OTHER_ERROR,
}

_CATEGORY_LABELS: dict[ErrorCategory, str] = {
    "mirror": "Mirror",
    "same_column": "Same column",
    "same_finger": "Same finger",
    "same_row": "Same row",
    "other": "Other",
}

_MAX_BAR_PAIRS = 15
_MIN_KEYSTROKES = 20  # minimum scored keystrokes for the expected letter
_MIN_OCCURRENCES = 2  # minimum error count for a confusion pair
_DEFAULT_LAST_N = 2000


class ConfusionMatrixChart(QWidget):
    """Combined confusion pair bar chart + grid heatmap."""

    def __init__(
        self,
        keyboard_layout: KeyboardLayout | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._keyboard_layout = keyboard_layout or load_keyboard("qwertz")
        self._repo: Repository | None = None
        self._setup_ui()

    def set_keyboard_layout(self, keyboard_layout: KeyboardLayout) -> None:
        self._keyboard_layout = keyboard_layout

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Legend + filter row
        legend_layout = QHBoxLayout()
        legend_layout.setContentsMargins(0, 0, 0, 0)
        for cat in ("mirror", "same_column", "same_finger", "same_row", "other"):
            color = _CATEGORY_COLORS[cat]  # type: ignore[index]
            label_text = _CATEGORY_LABELS[cat]  # type: ignore[index]
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background-color: {color}; border: 1px solid #555;")
            text = QLabel(label_text)
            text.setFont(app_font(9))
            text.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
            legend_layout.addWidget(swatch)
            legend_layout.addWidget(text)
            legend_layout.addSpacing(10)

        legend_layout.addStretch()

        self._limit_cb = QCheckBox("Limit to last")
        self._limit_cb.setFont(app_font(10))
        self._limit_cb.setChecked(True)
        self._limit_cb.stateChanged.connect(self._on_filter_changed)
        legend_layout.addWidget(self._limit_cb)

        self._limit_spin = QSpinBox()
        self._limit_spin.setFont(app_font(10))
        self._limit_spin.setRange(100, 999999)
        self._limit_spin.setSingleStep(500)
        self._limit_spin.setValue(_DEFAULT_LAST_N)
        self._limit_spin.setSuffix(" keys")
        self._limit_spin.valueChanged.connect(self._on_filter_changed)
        legend_layout.addWidget(self._limit_spin)

        layout.addLayout(legend_layout)

        self._empty_label = QLabel("No confusion data yet.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # Splitter: bar chart (top) + heatmap (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Bar chart
        self._bar_plot = pg.PlotWidget()
        self._bar_plot.setBackground(COLOR_BG_DARK)
        self._bar_plot.showGrid(x=True, y=False, alpha=0.15)
        self._bar_plot.setLabel("bottom", "Confusion Rate %", color=COLOR_TEXT_PRIMARY)
        self._bar_plot.setLabel("left", "Confusion Pair", color=COLOR_TEXT_PRIMARY)
        self._bar_plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._bar_plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        splitter.addWidget(self._bar_plot)

        # Heatmap
        self._heat_widget = QWidget()
        heat_layout = QVBoxLayout(self._heat_widget)
        heat_layout.setContentsMargins(0, 0, 0, 0)

        self._heat_plot = pg.PlotWidget()
        self._heat_plot.setBackground(COLOR_BG_DARK)
        self._heat_plot.setLabel("bottom", "Typed (actual)", color=COLOR_TEXT_PRIMARY)
        self._heat_plot.setLabel("left", "Expected", color=COLOR_TEXT_PRIMARY)
        self._heat_plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._heat_plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        heat_layout.addWidget(self._heat_plot)

        splitter.addWidget(self._heat_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._splitter = splitter
        layout.addWidget(self._splitter)

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
        """Reload data from DB and redraw both views."""
        self._repo = repo
        self._redraw()

    def _redraw(self) -> None:
        """Query and draw with current filter settings."""
        self._bar_plot.clear()
        self._heat_plot.clear()
        if self._repo is None:
            return

        last_n = self._get_last_n()
        pairs = self._repo.get_confusion_pairs(last_n=last_n)
        if not pairs:
            self._empty_label.setVisible(True)
            self._splitter.setVisible(False)
            return
        self._empty_label.setVisible(False)
        self._splitter.setVisible(True)

        # Get total keystrokes per letter for normalization
        error_rates = self._repo.get_per_letter_error_rates(last_n=last_n)
        letter_totals: dict[str, int] = {
            letter: data[1] for letter, data in error_rates.items()
        }

        # Filter: expected letter must have >= _MIN_KEYSTROKES,
        # and the pair must have >= _MIN_OCCURRENCES
        filtered: list[tuple[str, str, int]] = [
            (exp, act, cnt)
            for exp, act, cnt in pairs
            if letter_totals.get(exp, 0) >= _MIN_KEYSTROKES and cnt >= _MIN_OCCURRENCES
        ]

        if not filtered:
            return

        self._draw_bar_chart(filtered, letter_totals)
        self._draw_heatmap(filtered, letter_totals)

    def _draw_bar_chart(
        self,
        pairs: list[tuple[str, str, int]],
        letter_totals: dict[str, int],
    ) -> None:
        """Draw horizontal bar chart of top confusion pairs by rate."""
        # Compute confusion rate for each pair
        rated: list[tuple[str, str, int, float]] = []
        for expected, actual, count in pairs:
            total = letter_totals.get(expected, 0)
            if total > 0:
                rate = count / total
                rated.append((expected, actual, count, rate))

        # Sort by rate descending, take top N
        rated.sort(key=lambda x: x[3], reverse=True)
        top = rated[:_MAX_BAR_PAIRS]

        # Reverse so highest rate is at the top of the chart
        top = list(reversed(top))

        n = len(top)
        if n == 0:
            return

        y_positions = np.arange(n, dtype=np.float64)
        widths = np.array([rate * 100 for _, _, _, rate in top], dtype=np.float64)

        brushes = []
        for expected, actual, _, _ in top:
            cat = classify_error(expected, actual, self._keyboard_layout)
            brushes.append(QColor(_CATEGORY_COLORS[cat]))

        bar = pg.BarGraphItem(
            x0=np.zeros(n, dtype=np.float64),
            y=y_positions,
            width=widths,
            height=0.6,
            brushes=brushes,
        )
        self._bar_plot.addItem(bar)

        # Y-axis tick labels: "n->e 1.3% (26x)"
        labels = []
        for expected, actual, count, rate in top:
            exp_label = "SPC" if expected == " " else expected
            act_label = "SPC" if actual == " " else actual
            labels.append(
                f"{exp_label}\u2192{act_label} {rate * 100:.1f}% ({count}\u00d7)"
            )
        ticks = [list(zip(y_positions.tolist(), labels))]
        self._bar_plot.getAxis("left").setTicks(ticks)

    def _draw_heatmap(
        self,
        pairs: list[tuple[str, str, int]],
        letter_totals: dict[str, int],
    ) -> None:
        """Draw grid heatmap using ImageItem with normalized rates."""
        # Collect all letters that appear in the filtered pairs
        all_letters: set[str] = set()
        for expected, actual, _ in pairs:
            all_letters.add(expected)
            all_letters.add(actual)

        # Sort letters; put space first if present, then alphabetical
        sorted_letters = sorted(all_letters - {" "})
        if " " in all_letters:
            sorted_letters.insert(0, " ")

        n = len(sorted_letters)
        if n == 0:
            return

        letter_to_idx = {l: i for i, l in enumerate(sorted_letters)}

        # Build rate matrix (confusion rate per pair)
        rate_matrix = np.zeros((n, n), dtype=np.float64)
        for expected, actual, count in pairs:
            row = letter_to_idx[expected]
            col = letter_to_idx[actual]
            total = letter_totals.get(expected, 0)
            rate_matrix[row, col] = (count / total * 100) if total > 0 else 0.0

        # Normalize rate to 0-255 for color mapping
        max_rate = rate_matrix.max()
        if max_rate > 0:
            normalized = (rate_matrix / max_rate * 255).astype(np.uint8)
        else:
            normalized = rate_matrix.astype(np.uint8)

        # Create RGBA image: red channel scaled by rate, with alpha
        rgba = np.zeros((n, n, 4), dtype=np.uint8)
        rgba[:, :, 0] = normalized  # Red
        rgba[:, :, 1] = (normalized * 0.15).astype(np.uint8)  # slight green
        rgba[:, :, 2] = (normalized * 0.15).astype(np.uint8)  # slight blue
        # Alpha: 0 for no data, 80-200 scaled by rate
        alpha = np.where(
            rate_matrix > 0,
            80 + (normalized * 0.5).astype(np.uint8),
            0,
        )
        rgba[:, :, 3] = alpha.astype(np.uint8)

        img = pg.ImageItem(image=rgba)
        self._heat_plot.addItem(img)

        # Position the image so each cell is 1x1, starting at (0,0)
        img.setRect(0, 0, n, n)

        # Set axis ticks
        display_labels = ["SPC" if l == " " else l for l in sorted_letters]
        # Center ticks at 0.5, 1.5, etc.
        tick_positions = [(i + 0.5, label) for i, label in enumerate(display_labels)]
        self._heat_plot.getAxis("bottom").setTicks([tick_positions])
        self._heat_plot.getAxis("left").setTicks([tick_positions])

        # Lock aspect ratio
        self._heat_plot.setAspectLocked(True)

        # Add text labels in each non-zero cell: "1.3%\n(26)"
        for expected, actual, count in pairs:
            row = letter_to_idx[expected]
            col = letter_to_idx[actual]
            rate = rate_matrix[row, col]
            text = pg.TextItem(
                f"{rate:.1f}%\n({count})",
                color=COLOR_TEXT_PRIMARY,
                anchor=(0.5, 0.5),
            )
            text.setFont(app_font(7))
            text.setPos(col + 0.5, row + 0.5)
            self._heat_plot.addItem(text)
