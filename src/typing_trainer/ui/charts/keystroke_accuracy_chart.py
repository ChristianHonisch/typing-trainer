"""Per-letter accuracy as a function of cumulative keystroke count.

X-axis: how many times a specific letter has been pressed.
Y-axis: rolling accuracy (sliding window).
One line per letter, toggled via checkboxes.  Interactive legend
with hover-to-highlight.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
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

_EMPTY_MSG = "No keystroke data yet."

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


class KeystrokeAccuracyChart(QWidget):
    """Per-letter accuracy vs. cumulative keystroke count."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._letter_colors: dict[str, str] = {}
        self._repo: Repository | None = None
        self._cache: dict[str, list[bool]] = {}
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

        # Right panel: controls + plot
        right = QVBoxLayout()

        # Controls bar
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Window:"))
        self._window_spin = QSpinBox()
        self._window_spin.setFont(app_font(10))
        self._window_spin.setRange(10, 500)
        self._window_spin.setSingleStep(10)
        self._window_spin.setValue(50)
        self._window_spin.setFixedWidth(70)
        self._window_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._window_spin.wheelEvent = lambda e: e.ignore()  # type: ignore[assignment]
        self._window_spin.valueChanged.connect(self._redraw)
        controls.addWidget(self._window_spin)
        controls.addStretch()
        right.addLayout(controls)

        # Empty label
        self._empty_label = QLabel(_EMPTY_MSG)
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        right.addWidget(self._empty_label)

        # Plot
        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "Accuracy", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Keystrokes", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        right.addWidget(self._plot)

        outer.addLayout(right, stretch=1)

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._repo = repo
        self._cache.clear()

        # Discover which letters have data
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

        # Sync checkboxes
        existing = set(self._checkboxes.keys())
        needed = set(letters)

        # Remove stale
        for letter in existing - needed:
            cb = self._checkboxes.pop(letter)
            self._checkbox_layout.removeWidget(cb)
            cb.deleteLater()

        # Add new
        for letter in sorted(needed - existing):
            display = repr(letter) if letter == " " else letter
            cb = QCheckBox(display)
            cb.setFont(app_font(11))
            cb.setChecked(True)
            color = self._letter_colors[letter]
            cb.setStyleSheet(f"color: {color};")
            cb.stateChanged.connect(self._redraw)
            # Insert before stretch
            idx = self._checkbox_layout.count() - 1
            self._checkbox_layout.insertWidget(idx, cb)
            self._checkboxes[letter] = cb

        # Prefetch all data
        for letter in letters:
            self._cache[letter] = repo.get_per_letter_keystroke_errors(letter)

        self._redraw()

    def _redraw(self) -> None:
        """Clear and redraw all visible lines."""
        self._plot.clear()
        self._interactive_legend = None

        window = self._window_spin.value()

        # 95% threshold
        threshold = pg.InfiniteLine(
            pos=0.95,
            angle=0,
            pen=pg.mkPen(COLOR_WARNING, width=1, style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(threshold)

        legend = self._plot.addLegend(offset=(10, 10), labelTextSize="9pt", colCount=2)

        curves: dict[str, pg.PlotDataItem] = {}
        y_min = 1.0

        for letter, cb in sorted(self._checkboxes.items()):
            if not cb.isChecked():
                continue
            errors = self._cache.get(letter)
            if not errors:
                continue

            # Compute rolling accuracy
            x_arr, y_arr = self._rolling_accuracy(errors, window)
            if len(x_arr) == 0:
                continue

            y_min = min(y_min, float(y_arr.min()))

            color = self._letter_colors.get(letter, "#ffffff")
            display = repr(letter) if letter == " " else letter
            pen = pg.mkPen(color, width=2)
            curve = self._plot.plot(x_arr, y_arr, pen=pen, name=display)
            curves[display] = curve

        # Set Y range
        self._plot.getViewBox().setYRange(max(0.5, y_min - 0.05), 1.02, padding=0)

        if legend is not None and curves:
            self._interactive_legend = InteractiveLegend(legend, curves, normal_width=2)

    @staticmethod
    def _rolling_accuracy(
        errors: list[bool], window: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute rolling accuracy over a keystroke sequence.

        Returns (x, y) numpy arrays where x is 1-indexed keystroke count
        and y is the rolling accuracy at that point.
        """
        buf: deque[bool] = deque(maxlen=window)
        err_count = 0
        x: list[int] = []
        y: list[float] = []

        for i, is_error in enumerate(errors):
            if len(buf) == window and buf[0]:
                err_count -= 1
            buf.append(is_error)
            if is_error:
                err_count += 1
            x.append(i + 1)
            y.append((len(buf) - err_count) / len(buf))

        return (
            np.array(x, dtype=np.float64),
            np.array(y, dtype=np.float64),
        )
