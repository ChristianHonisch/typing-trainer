"""Intra-run typing speed chart for the analysis tab.

Plots rolling reaction time over keystroke position for a selected run,
with three lines:

- **All** (green): all valid keystrokes.
- **Settled** (blue): only keystrokes for the best-performing letters
  (>= 2000 historical keystrokes, top third by accuracy).
- **Space** (cyan): spacebar keystrokes only.

Red scatter dots mark cognitive error positions.  In speed mode a
dashed horizontal line shows the target RT.

The user can select which run to view and adjust the rolling window
size.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.core.stats import RT_CAP_MS, compute_position_baselines
from typing_trainer.models.letter_state import ErrorType
from typing_trainer.models.run_result import RunResult
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

_DEFAULT_WINDOW = 1
_DEFAULT_EXCLUDE_PCT = 0
_WARMUP = 3  # same as config default; overridden at refresh if needed


class RunSpeedChart(QWidget):
    """Intra-run reaction time chart with run selector and window control."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repo: Repository | None = None
        self._settled_letters: set[str] = set()
        self._current_run: RunResult | None = None
        self._warmup = _WARMUP
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # --- Controls row ---
        controls = QHBoxLayout()
        controls.setSpacing(8)

        run_label = QLabel("Run:")
        run_label.setFont(app_font(10))
        controls.addWidget(run_label)

        self._run_combo = QComboBox()
        self._run_combo.setFont(app_font(10))
        self._run_combo.setMinimumWidth(260)
        self._run_combo.currentIndexChanged.connect(self._on_run_changed)
        controls.addWidget(self._run_combo)

        controls.addSpacing(20)

        win_label = QLabel("Window:")
        win_label.setFont(app_font(10))
        controls.addWidget(win_label)

        self._window_spin = QSpinBox()
        self._window_spin.setFont(app_font(10))
        self._window_spin.setRange(1, 50)
        self._window_spin.setSingleStep(1)
        self._window_spin.setValue(_DEFAULT_WINDOW)
        self._window_spin.valueChanged.connect(self._redraw)
        controls.addWidget(self._window_spin)

        controls.addSpacing(20)

        excl_label = QLabel("Exclude:")
        excl_label.setFont(app_font(10))
        controls.addWidget(excl_label)

        self._exclude_spin = QSpinBox()
        self._exclude_spin.setFont(app_font(10))
        self._exclude_spin.setRange(0, 30)
        self._exclude_spin.setSingleStep(1)
        self._exclude_spin.setValue(_DEFAULT_EXCLUDE_PCT)
        self._exclude_spin.setSuffix("%")
        self._exclude_spin.setToolTip("Exclude the slowest X% of keystrokes")
        self._exclude_spin.valueChanged.connect(self._redraw)
        controls.addWidget(self._exclude_spin)

        controls.addStretch()
        layout.addLayout(controls)

        # --- Empty label ---
        self._empty_label = QLabel("Select a run to view speed data.")
        self._empty_label.setFont(app_font(11))
        self._empty_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # --- Plot ---
        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "RT (ms)", color=COLOR_TEXT_PRIMARY)
        self._plot.setLabel("bottom", "Position", color=COLOR_TEXT_PRIMARY)
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        layout.addWidget(self._plot, stretch=1)

    # ------------------------------------------------------------------

    def refresh(self, repo: Repository) -> None:
        """Reload run list and settled letters from the database."""
        self._repo = repo

        # Compute settled letters (same logic as main_window)
        all_letters = list(repo.get_per_letter_error_rates().keys())
        rolling_long = repo.get_per_letter_rolling_accuracy(all_letters, 2000)
        qualifying = [
            (letter, acc)
            for letter, (acc, count) in rolling_long.items()
            if count >= 2000 and letter != " "
        ]
        self._settled_letters = set()
        if qualifying:
            qualifying.sort(key=lambda t: t[1], reverse=True)
            n = max(1, len(qualifying) // 3)
            self._settled_letters = {letter for letter, _ in qualifying[:n]}

        # Populate run combo (most recent first)
        summaries = repo.get_all_runs_summary()
        self._run_combo.blockSignals(True)
        prev_run_id: int | None = None
        if self._run_combo.currentIndex() >= 0:
            prev_run_id = self._run_combo.currentData()

        self._run_combo.clear()
        for s in reversed(summaries):
            status = "FAIL" if s.failed else f"{s.accuracy:.0%}"
            label = f"#{s.run_id}  {status}  {s.wpm:.0f} WPM"
            self._run_combo.addItem(label, s.run_id)

        # Restore previous selection or default to most recent
        restored = False
        if prev_run_id is not None:
            for i in range(self._run_combo.count()):
                if self._run_combo.itemData(i) == prev_run_id:
                    self._run_combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored and self._run_combo.count() > 0:
            self._run_combo.setCurrentIndex(0)

        self._run_combo.blockSignals(False)
        self._load_and_draw()

    # ------------------------------------------------------------------

    def _on_run_changed(self, index: int) -> None:
        self._load_and_draw()

    def _load_and_draw(self) -> None:
        """Load keystroke data for the selected run and redraw."""
        if self._repo is None or self._run_combo.currentIndex() < 0:
            self._plot.clear()
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return

        run_id = self._run_combo.currentData()
        if run_id is None:
            self._plot.clear()
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._plot.setVisible(True)
        self._current_run = self._repo.get_run_with_keystrokes(run_id)
        self._redraw()

    def _redraw(self) -> None:
        """Draw the three-line RT chart for the current run."""
        self._plot.clear()
        run = self._current_run
        if run is None or not run.keystrokes:
            return

        warmup = self._warmup
        settled = self._settled_letters
        window = self._window_spin.value()

        # ── Collect keystrokes into three streams ──
        all_pos: list[int] = []
        all_rt: list[float] = []
        settled_pos: list[int] = []
        settled_rt: list[float] = []
        space_pos: list[int] = []
        space_rt: list[float] = []
        error_set: set[int] = set()

        for ks in run.keystrokes:
            if ks.is_backspace:
                continue
            if ks.position < warmup:
                continue
            if ks.error_type in (ErrorType.MOTOR_OVERFLOW, ErrorType.BURST_REPEAT):
                continue
            if ks.reaction_time_ms is None or ks.reaction_time_ms > RT_CAP_MS:
                continue

            rt = float(ks.reaction_time_ms)
            pos = ks.position

            all_pos.append(pos)
            all_rt.append(rt)

            if ks.expected_char in settled:
                settled_pos.append(pos)
                settled_rt.append(rt)

            if ks.expected_char == " ":
                space_pos.append(pos)
                space_rt.append(rt)

            if ks.error_type == ErrorType.COGNITIVE_ERROR:
                error_set.add(pos)

        if len(all_rt) < 2:
            return

        # ── Exclude slowest X% (per stream) ──
        exclude_pct = self._exclude_spin.value()
        if exclude_pct > 0:

            def _exclude(
                positions: list[int],
                rts: list[float],
            ) -> tuple[list[int], list[float]]:
                if len(rts) < 2:
                    return positions, rts
                thresh = float(np.percentile(rts, 100 - exclude_pct))
                filt = [(p, r) for p, r in zip(positions, rts) if r <= thresh]
                return [x[0] for x in filt], [x[1] for x in filt]

            all_pos, all_rt = _exclude(all_pos, all_rt)
            settled_pos, settled_rt = _exclude(settled_pos, settled_rt)
            space_pos, space_rt = _exclude(space_pos, space_rt)

            if len(all_rt) < 2:
                return

        # ── Helper: rolling mean ──
        def rolling(
            positions: list[int],
            rts: list[float],
        ) -> tuple[np.ndarray, np.ndarray]:
            buf: deque[float] = deque(maxlen=window)
            xs: list[int] = []
            ys: list[float] = []
            for p, r in zip(positions, rts):
                buf.append(r)
                xs.append(p)
                ys.append(sum(buf) / len(buf))
            return (
                np.array(xs, dtype=np.float64),
                np.array(ys, dtype=np.float64),
            )

        # ── Legend ──
        legend = self._plot.addLegend(offset=(-10, 10), labelTextSize="9pt")
        legend.setBrush(pg.mkBrush(30, 30, 30, 180))

        y_max = 0.0

        # ── Green: all ──
        x_all, y_all = rolling(all_pos, all_rt)
        self._plot.plot(x_all, y_all, pen=pg.mkPen(COLOR_SUCCESS, width=2), name="All")
        y_max = max(y_max, float(y_all.max()))

        # ── Blue: settled ──
        if len(settled_rt) >= 2:
            x_set, y_set = rolling(settled_pos, settled_rt)
            self._plot.plot(
                x_set, y_set, pen=pg.mkPen("#44aaff", width=2), name="Settled"
            )
            y_max = max(y_max, float(y_set.max()))

        # ── Cyan: space ──
        if len(space_rt) >= 2:
            x_sp, y_sp = rolling(space_pos, space_rt)
            self._plot.plot(x_sp, y_sp, pen=pg.mkPen("#cc8844", width=2), name="Space")
            y_max = max(y_max, float(y_sp.max()))

        # ── Error markers ──
        err_x: list[int] = []
        err_y: list[float] = []
        for xi, yi in zip(x_all.tolist(), y_all.tolist()):
            if int(xi) in error_set:
                err_x.append(int(xi))
                err_y.append(float(yi))

        if err_x:
            self._plot.plot(
                np.array(err_x, dtype=np.float64),
                np.array(err_y, dtype=np.float64),
                pen=None,
                symbol="o",
                symbolSize=7,
                symbolBrush=COLOR_ERROR,
                symbolPen=None,
            )

        # ── Historical baselines (dashed lines) ──
        if self._repo is not None and run.target_length > 0:
            raw_hist = self._repo.get_historical_position_rts(
                min_target_length=run.target_length,
                n_runs=64,
                warmup=warmup,
            )
            if raw_hist:
                bl_all, bl_settled, bl_space = compute_position_baselines(
                    raw_hist,
                    settled,
                )
                dash_pen_all = pg.mkPen(COLOR_SUCCESS, width=1.5)
                dash_pen_all.setDashPattern([8, 6])
                dash_pen_settled = pg.mkPen("#44aaff", width=1.5)
                dash_pen_settled.setDashPattern([8, 6])
                dash_pen_space = pg.mkPen("#cc8844", width=1.5)
                dash_pen_space.setDashPattern([8, 6])

                run_positions = set(all_pos)
                bl_all_pts = sorted(
                    (p, v) for p, v in bl_all.items() if p in run_positions
                )
                if len(bl_all_pts) >= 2:
                    bx = np.array([p for p, _ in bl_all_pts], dtype=np.float64)
                    by = np.array([v for _, v in bl_all_pts], dtype=np.float64)
                    self._plot.plot(
                        bx,
                        by,
                        pen=dash_pen_all,
                        name="Avg All",
                    )
                    y_max = max(y_max, float(by.max()))

                bl_set_pts = sorted(
                    (p, v) for p, v in bl_settled.items() if p in run_positions
                )
                if len(bl_set_pts) >= 2:
                    bx = np.array([p for p, _ in bl_set_pts], dtype=np.float64)
                    by = np.array([v for _, v in bl_set_pts], dtype=np.float64)
                    self._plot.plot(
                        bx,
                        by,
                        pen=dash_pen_settled,
                        name="Avg Settled",
                    )
                    y_max = max(y_max, float(by.max()))

                bl_sp_pts = sorted(
                    (p, v) for p, v in bl_space.items() if p in run_positions
                )
                if len(bl_sp_pts) >= 2:
                    bx = np.array([p for p, _ in bl_sp_pts], dtype=np.float64)
                    by = np.array([v for _, v in bl_sp_pts], dtype=np.float64)
                    self._plot.plot(
                        bx,
                        by,
                        pen=dash_pen_space,
                        name="Avg Space",
                    )
                    y_max = max(y_max, float(by.max()))

        # ── Y range ──
        if y_max > 0:
            self._plot.getViewBox().setYRange(0, y_max * 1.15, padding=0)
