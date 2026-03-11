"""Per-letter reaction time chart with optional sliding-window smoothing.

Multi-line plot with one line per selected letter.  Letter visibility is
toggled via checkboxes on the left.  A "Sliding avg" toggle and window-size
spinner allow switching between per-run trimmed mean and a rolling trimmed
mean across the last *N* keystrokes.  Keystrokes with RT > 2 s are
pre-filtered at the database level (see ``RT_CAP_MS``).
"""

from __future__ import annotations

from collections import deque

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

from typing_trainer.core.stats import trimmed_mean
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

# Same color palette as per_letter_chart.py so letters have consistent colors.
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

_DEFAULT_WINDOW = 20


class PerLetterRtChart(QWidget):
    """Reaction time per letter with optional sliding-window smoothing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._letter_colors: dict[str, str] = {}
        self._series_cache: dict[str, list[tuple[int, list[int]]]] = {}
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

        # Right: controls bar + plot
        right = QVBoxLayout()
        right.setSpacing(2)

        # --- Sliding average controls (above plot) ---
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._sliding_cb = QCheckBox("Sliding avg")
        self._sliding_cb.setFont(app_font(9))
        self._sliding_cb.setChecked(True)
        self._sliding_cb.stateChanged.connect(self._on_mode_changed)
        controls.addWidget(self._sliding_cb)

        lbl = QLabel("Window")
        lbl.setFont(app_font(9))
        controls.addWidget(lbl)

        self._window_spin = QSpinBox()
        self._window_spin.setFont(app_font(9))
        self._window_spin.setRange(5, 100)
        self._window_spin.setSingleStep(5)
        self._window_spin.setValue(_DEFAULT_WINDOW)
        self._window_spin.setEnabled(True)
        self._window_spin.valueChanged.connect(self._redraw)
        controls.addWidget(self._window_spin)

        controls.addStretch()
        right.addLayout(controls)

        # Plot
        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel(
            "left", "Rolling RT (ms)", color=COLOR_TEXT_PRIMARY
        )
        self._plot.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        right.addWidget(self._plot, stretch=1)

        outer.addLayout(right, stretch=1)

    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        """Toggle sliding-average mode and update controls + axis label."""
        sliding = self._sliding_cb.isChecked()
        self._window_spin.setEnabled(sliding)
        if sliding:
            self._plot.setLabel(
                "left", "Rolling RT (ms)", color=COLOR_TEXT_PRIMARY
            )
        else:
            self._plot.setLabel(
                "left", "Trimmed Mean RT (ms)", color=COLOR_TEXT_PRIMARY
            )
        self._redraw()

    # ------------------------------------------------------------------

    def refresh(self, repo: Repository) -> None:
        """Reload data and rebuild checkboxes + plot."""
        # Get all letters that have keystroke data
        error_rates = repo.get_per_letter_error_rates()
        letters = sorted(error_rates.keys())

        # Assign stable colors (same order as per_letter_chart)
        for i, letter in enumerate(letters):
            if letter not in self._letter_colors:
                self._letter_colors[letter] = _LETTER_COLORS[
                    i % len(_LETTER_COLORS)
                ]

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
            self._series_cache[letter] = repo.get_per_letter_rt_series(letter)

        self._redraw()

    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        """Redraw visible lines based on checkbox state and mode."""
        self._plot.clear()
        sliding = self._sliding_cb.isChecked()

        y_max = 0.0
        for letter, cb in self._checkboxes.items():
            if not cb.isChecked():
                continue
            series = self._series_cache.get(letter, [])
            if not series:
                continue

            if sliding:
                x, y = self._compute_rolling(series)
            else:
                x, y = self._compute_per_run(series)

            if len(y) == 0:
                continue

            color = self._letter_colors.get(letter, "#cccccc")
            self._plot.plot(x, y, pen=pg.mkPen(color, width=2))
            y_max = max(y_max, float(y.max()))

        if y_max > 0:
            self._plot.getViewBox().setYRange(0, y_max * 1.1, padding=0)

    # ------------------------------------------------------------------

    @staticmethod
    def _compute_per_run(
        series: list[tuple[int, list[int]]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """One trimmed-mean point per run."""
        x = np.array([run_id for run_id, _ in series], dtype=np.float64)
        y = np.array(
            [trimmed_mean(rts) for _, rts in series], dtype=np.float64
        )
        return x, y

    def _compute_rolling(
        self,
        series: list[tuple[int, list[int]]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Rolling trimmed mean across last *N* keystrokes, one point per run."""
        window = self._window_spin.value()
        buf: deque[int] = deque(maxlen=window)
        xs: list[int] = []
        ys: list[float] = []
        for run_id, rts in series:
            for rt in rts:
                buf.append(rt)
            # Emit one value per run boundary
            if buf:
                xs.append(run_id)
                ys.append(trimmed_mean(list(buf)))
        return (
            np.array(xs, dtype=np.float64),
            np.array(ys, dtype=np.float64),
        )
