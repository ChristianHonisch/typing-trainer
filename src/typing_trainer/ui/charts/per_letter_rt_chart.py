"""Per-letter reaction time chart with optional sliding-window smoothing.

Multi-line plot with one line per selected letter.  Letter visibility is
toggled via checkboxes on the left.  A "Sliding avg" toggle and window-size
spinner allow switching between per-run trimmed mean and a rolling trimmed
mean across the last *N* keystrokes.  Keystrokes with RT > 2 s are
pre-filtered at the database level (see ``RT_CAP_MS``).

The chart uses a **split axis**: the right quarter shows the last 40 runs
in detail, while the left three-quarters compress the full history.  A
diagonal break indicator separates the two regions.  When there are 40 or
fewer total runs the history panel is hidden automatically.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen
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
_RECENT_RUNS = 40


class _AxisBreakWidget(QWidget):
    """Narrow widget that draws diagonal break lines between two plots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(14)

    def paintEvent(self, a0: object) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(Qt.GlobalColor.white)
        pen.setWidth(2)
        p.setPen(pen)

        w = self.width()
        h = self.height()
        cx = w // 2
        seg = 8  # half-length of each diagonal stroke

        # Two diagonal strokes in the vertical middle
        mid = h // 2
        for offset in (-12, 12):
            y = mid + offset
            p.drawLine(cx - seg, y - seg, cx + seg, y + seg)

        p.end()


class PerLetterRtChart(QWidget):
    """Reaction time per letter with optional sliding-window smoothing.

    Uses a split x-axis: the right quarter of the chart shows the last
    40 runs in detail while the left three-quarters compress the full
    history.
    """

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

        # Right: controls bar + split plots
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

        # --- Split plot area: history | break | recent ---
        plot_row = QHBoxLayout()
        plot_row.setSpacing(0)

        self._plot_history = self._make_plot()
        self._plot_history.setLabel("bottom", "Run #", color=COLOR_TEXT_PRIMARY)
        plot_row.addWidget(self._plot_history, stretch=3)

        self._break_widget = _AxisBreakWidget()
        plot_row.addWidget(self._break_widget)

        self._plot_recent = self._make_plot()
        self._plot_recent.setLabel(
            "bottom", "Last 40 runs", color=COLOR_TEXT_PRIMARY
        )
        # Hide the Y-axis on the recent plot — shared with history plot
        self._plot_recent.getAxis("left").setWidth(0)
        self._plot_recent.getAxis("left").setTicks([])
        self._plot_recent.getAxis("left").setStyle(showValues=False)
        plot_row.addWidget(self._plot_recent, stretch=1)

        right.addLayout(plot_row, stretch=1)
        outer.addLayout(right, stretch=1)

        # Set initial Y-axis label
        self._update_y_label()

    def _make_plot(self) -> pg.PlotWidget:
        """Create and style a PlotWidget with common settings."""
        plot = pg.PlotWidget()
        plot.setBackground(COLOR_BG_DARK)
        plot.showGrid(x=True, y=True, alpha=0.15)
        plot.setLabel("left", "Rolling RT (ms)", color=COLOR_TEXT_PRIMARY)
        plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        return plot

    # ------------------------------------------------------------------

    def _update_y_label(self) -> None:
        """Set the Y-axis label on the history plot based on mode."""
        sliding = self._sliding_cb.isChecked()
        label = "Rolling RT (ms)" if sliding else "Trimmed Mean RT (ms)"
        self._plot_history.setLabel("left", label, color=COLOR_TEXT_PRIMARY)

    def _on_mode_changed(self) -> None:
        """Toggle sliding-average mode and update controls + axis label."""
        self._window_spin.setEnabled(self._sliding_cb.isChecked())
        self._update_y_label()
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

    def _collect_all_run_ids(self) -> list[int]:
        """Gather sorted unique run_ids across all *visible* letter series."""
        ids: set[int] = set()
        for letter, cb in self._checkboxes.items():
            if not cb.isChecked():
                continue
            for run_id, _ in self._series_cache.get(letter, []):
                ids.add(run_id)
        return sorted(ids)

    def _redraw(self) -> None:
        """Redraw visible lines across both plot panels."""
        self._plot_history.clear()
        self._plot_recent.clear()
        sliding = self._sliding_cb.isChecked()

        all_run_ids = self._collect_all_run_ids()

        # Split: last _RECENT_RUNS go to right panel, rest to left
        if len(all_run_ids) <= _RECENT_RUNS:
            recent_ids = set(all_run_ids)
            history_ids: set[int] = set()
        else:
            recent_ids = set(all_run_ids[-_RECENT_RUNS:])
            history_ids = set(all_run_ids[:-_RECENT_RUNS])

        # Show/hide history panel
        has_history = len(history_ids) > 0
        self._plot_history.setVisible(has_history)
        self._break_widget.setVisible(has_history)

        y_max = 0.0

        for letter, cb in self._checkboxes.items():
            if not cb.isChecked():
                continue
            series = self._series_cache.get(letter, [])
            if not series:
                continue

            # Compute full series first (rolling needs contiguous data)
            if sliding:
                full_x, full_y = self._compute_rolling(series)
            else:
                full_x, full_y = self._compute_per_run(series)

            if len(full_y) == 0:
                continue

            color = self._letter_colors.get(letter, "#cccccc")
            pen = pg.mkPen(color, width=2)

            # Split into history and recent segments
            if has_history:
                h_mask = np.isin(full_x.astype(int), list(history_ids))
                if h_mask.any():
                    self._plot_history.plot(
                        full_x[h_mask], full_y[h_mask], pen=pen
                    )
                    y_max = max(y_max, float(full_y[h_mask].max()))

            r_mask = np.isin(full_x.astype(int), list(recent_ids))
            if r_mask.any():
                self._plot_recent.plot(
                    full_x[r_mask], full_y[r_mask], pen=pen
                )
                y_max = max(y_max, float(full_y[r_mask].max()))

        # Synchronize Y ranges across both panels
        if y_max > 0:
            y_range = y_max * 1.1
            self._plot_recent.getViewBox().setYRange(0, y_range, padding=0)
            if has_history:
                self._plot_history.getViewBox().setYRange(
                    0, y_range, padding=0
                )

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
