"""Post-run statistics display with rest suggestion timer.

Shows:
- Aggregate stats (keystrokes, accuracy, WPM, errors)
- Intra-run typing speed chart (rolling RT over position)
- Per-letter error rates
- Per-letter mean reaction times
- Delta vs previous run
- Rest suggestion countdown
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.config import Config
from typing_trainer.core.speed_manager import SpeedRunResult
from typing_trainer.core.stats import RT_CAP_MS
from typing_trainer.models.letter_state import ErrorType
from typing_trainer.models.run_result import RunResult
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_BTN_DISABLED_BG,
    COLOR_BTN_DISABLED_TEXT,
    COLOR_BTN_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
    make_selectable,
)

_RT_WINDOW = 10
"""Rolling window size for the intra-run speed chart."""


class RunSummaryWidget(QWidget):
    """Displays run results and manages the rest period.

    Signals:
        continue_clicked: emitted when the user wants to start another run.
    """

    continue_clicked = pyqtSignal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._rest_seconds = config.rest_suggestion_seconds
        self._rest_remaining = 0
        self._rest_timer = QTimer(self)
        self._rest_timer.setInterval(1000)
        self._rest_timer.timeout.connect(self._on_rest_tick)

        # State for chart re-draw on window change
        self._last_result: RunResult | None = None
        self._last_speed_result: SpeedRunResult | None = None
        self._last_settled: set[str] | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        # Title
        self._title = QLabel("Run Complete")
        self._title.setFont(app_font(20, bold=True))
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        # Aggregate stats
        stats_group = QGroupBox("Summary")
        stats_group.setFont(app_font(11))
        stats_layout = QVBoxLayout(stats_group)
        self._stats_label = QLabel()
        self._stats_label.setFont(app_font(13))
        self._stats_label.setTextFormat(Qt.TextFormat.RichText)
        make_selectable(self._stats_label)
        stats_layout.addWidget(self._stats_label)
        layout.addWidget(stats_group)

        # Intra-run speed chart
        speed_group = QGroupBox("Typing Speed")
        speed_group.setFont(app_font(11))
        speed_layout = QVBoxLayout(speed_group)
        speed_layout.setContentsMargins(4, 4, 4, 4)

        # Window spinner above chart
        speed_controls = QHBoxLayout()
        speed_controls.setSpacing(8)
        win_label = QLabel("Window:")
        win_label.setFont(app_font(9))
        speed_controls.addWidget(win_label)
        self._rt_window_spin = QSpinBox()
        self._rt_window_spin.setFont(app_font(9))
        self._rt_window_spin.setRange(3, 50)
        self._rt_window_spin.setSingleStep(1)
        self._rt_window_spin.setValue(_RT_WINDOW)
        self._rt_window_spin.valueChanged.connect(self._on_rt_window_changed)
        speed_controls.addWidget(self._rt_window_spin)
        speed_controls.addStretch()
        speed_layout.addLayout(speed_controls)

        self._speed_chart = pg.PlotWidget()
        self._speed_chart.setBackground(COLOR_BG_DARK)
        self._speed_chart.showGrid(x=True, y=True, alpha=0.15)
        self._speed_chart.setLabel(
            "left", "RT (ms)", color=COLOR_TEXT_PRIMARY
        )
        self._speed_chart.setLabel(
            "bottom", "Position", color=COLOR_TEXT_PRIMARY
        )
        self._speed_chart.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._speed_chart.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        self._speed_chart.setMinimumHeight(150)

        speed_layout.addWidget(self._speed_chart, stretch=1)
        self._speed_group = speed_group
        layout.addWidget(speed_group, stretch=1)

        # Per-letter table
        letter_group = QGroupBox("Per-Letter Breakdown")
        letter_group.setFont(app_font(11))
        letter_layout = QVBoxLayout(letter_group)

        self._letter_table = QTableWidget()
        self._letter_table.setFont(app_font(11))
        self._letter_table.setColumnCount(5)
        self._letter_table.setHorizontalHeaderLabels(
            ["Letter", "Attempts", "Errors", "Error Rate", "Avg RT (ms)"]
        )
        header = self._letter_table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._letter_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._letter_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        letter_layout.addWidget(self._letter_table)
        layout.addWidget(letter_group)

        # Rest timer and buttons
        bottom_layout = QHBoxLayout()

        self._rest_label = QLabel()
        self._rest_label.setFont(app_font(12))
        self._rest_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(self._rest_label, stretch=1)

        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setFont(app_font(14, bold=True))
        self._continue_btn.setMinimumHeight(45)
        self._continue_btn.setMinimumWidth(200)
        self._continue_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BTN_PRIMARY};
                color: {COLOR_TEXT_BRIGHT};
                border: none;
                border-radius: 5px;
                padding: 10px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_BTN_HOVER};
            }}
            QPushButton:disabled {{
                background-color: {COLOR_BTN_DISABLED_BG};
                color: {COLOR_BTN_DISABLED_TEXT};
            }}
            """
        )
        self._continue_btn.clicked.connect(self._on_continue)
        bottom_layout.addWidget(self._continue_btn)

        layout.addLayout(bottom_layout)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def show_result(
        self,
        result: RunResult,
        previous: RunResult | None = None,
        speed_result: SpeedRunResult | None = None,
        settled_letters: set[str] | None = None,
    ) -> None:
        """Display the run result."""
        # Title
        if result.failed:
            self._title.setText("Run Failed")
            self._title.setStyleSheet(f"color: {COLOR_ERROR};")
        elif speed_result is not None and not speed_result.passed:
            self._title.setText("Speed Run Failed")
            self._title.setStyleSheet(f"color: {COLOR_ERROR};")
        else:
            self._title.setText("Run Complete")
            self._title.setStyleSheet(f"color: {COLOR_SUCCESS};")

        # Aggregate stats
        lines: list[str] = []
        lines.append(f"Total keystrokes:    {result.total_keystrokes}")
        lines.append(f"Cognitive errors:    {result.cognitive_errors}")
        lines.append(f"Motor overflow:      {result.motor_overflow_errors}")
        if result.burst_repeat_count > 0:
            lines.append(f"Burst repeats:       {result.burst_repeat_count}")
        lines.append(f"Backspaces:          {result.backspace_count}")
        if result.swap_count > 0:
            lines.append(f"Swap errors:         {result.swap_count}")
        lines.append(f"Accuracy:            {result.accuracy:.1%}")
        lines.append(f"WPM:                 {result.wpm:.1f}")

        # Duration
        if result.start_time is not None and result.end_time is not None:
            duration_s = int(
                (result.end_time - result.start_time).total_seconds()
            )
            if duration_s >= 60:
                lines.append(
                    f"Duration:            {duration_s // 60}m {duration_s % 60:02d}s"
                )
            else:
                lines.append(f"Duration:            {duration_s}s")

        # Speed-specific stats
        if speed_result is not None:
            lines.append("")
            lines.append(f"--- Speed Training ---")
            lines.append(f"Target WPM:          {speed_result.target_wpm:.0f}")
            lines.append(f"Achieved WPM:        {speed_result.achieved_wpm:.1f}")
            passed_text = f'<span style="color:{COLOR_SUCCESS}">PASSED</span>' if speed_result.passed else f'<span style="color:{COLOR_ERROR}">FAILED</span>'
            lines.append(f"Result:              {passed_text}")
            lines.append(f"New target WPM:      {speed_result.new_target_wpm:.0f}")
            if speed_result.run_median_rt_ms > 0:
                lines.append(f"Median RT:           {speed_result.run_median_rt_ms:.0f} ms")

            # Speed bottlenecks
            bottlenecks = [d for d in speed_result.per_key_diagnostics if d.is_bottleneck]
            if bottlenecks:
                lines.append("")
                lines.append("Speed bottlenecks (> 1.5x median):")
                for d in bottlenecks:
                    lines.append(f"  '{d.letter}': {d.mean_rt_ms:.0f} ms")

        # Delta vs previous
        if previous is not None:
            acc_delta = result.accuracy - previous.accuracy
            wpm_delta = result.wpm - previous.wpm
            acc_color = COLOR_SUCCESS if acc_delta >= 0 else COLOR_ERROR
            wpm_color = COLOR_SUCCESS if wpm_delta >= 0 else COLOR_ERROR
            acc_sign = "+" if acc_delta >= 0 else ""
            wpm_sign = "+" if wpm_delta >= 0 else ""
            lines.append("")
            lines.append(
                f'vs previous run:     '
                f'<span style="color:{acc_color}">{acc_sign}{acc_delta:.1%}</span> accuracy, '
                f'<span style="color:{wpm_color}">{wpm_sign}{wpm_delta:.1f}</span> WPM'
            )

        self._stats_label.setText("<pre>" + "\n".join(lines) + "</pre>")

        # Intra-run speed chart (store for re-draw on window change)
        self._last_result = result
        self._last_speed_result = speed_result
        self._last_settled = settled_letters
        self._update_speed_chart(result, speed_result, settled_letters)

        # Per-letter table
        letters = sorted(result.per_letter.keys())
        self._letter_table.setRowCount(len(letters))
        for row, letter in enumerate(letters):
            stats = result.per_letter[letter]

            self._letter_table.setItem(row, 0, QTableWidgetItem(letter))
            self._letter_table.setItem(
                row, 1, QTableWidgetItem(str(stats.total_attempts))
            )

            errors_item = QTableWidgetItem(str(stats.cognitive_errors))
            if stats.cognitive_errors > 0:
                errors_item.setForeground(QColor(COLOR_ERROR))
            self._letter_table.setItem(row, 2, errors_item)

            error_item = QTableWidgetItem(f"{stats.error_rate:.1%}")
            if stats.error_rate > 0.08:
                error_item.setForeground(QColor(COLOR_ERROR))
            elif stats.error_rate > 0.05:
                error_item.setForeground(QColor(COLOR_WARNING))
            self._letter_table.setItem(row, 3, error_item)

            rt_text = (
                f"{stats.mean_reaction_time_ms:.0f}"
                if stats.mean_reaction_time_ms is not None
                else "-"
            )
            self._letter_table.setItem(row, 4, QTableWidgetItem(rt_text))

        # Start rest timer
        self._start_rest_timer()

        # Grab focus so Return key works immediately
        self.setFocus()

    def _update_speed_chart(
        self,
        result: RunResult,
        speed_result: SpeedRunResult | None,
        settled_letters: set[str] | None = None,
    ) -> None:
        """Plot rolling reaction time over keystroke position.

        Three lines:
        - **Green** ("All"): all valid keystrokes.
        - **Blue** ("Settled"): only keystrokes for *settled_letters*
          (letters with >= 2000 historical keystrokes, best third by
          accuracy).
        - **Cyan** ("Space"): spacebar keystrokes only.

        Red scatter dots mark positions with cognitive errors (on the
        "All" line).  In speed mode a dashed horizontal line shows the
        target RT.
        """
        self._speed_chart.clear()
        warmup = self.config.warmup_keystrokes
        settled = settled_letters or set()

        # ── Collect keystrokes into three parallel streams ──
        all_pos: list[int] = []
        all_rt: list[float] = []
        settled_pos: list[int] = []
        settled_rt: list[float] = []
        space_pos: list[int] = []
        space_rt: list[float] = []
        error_set: set[int] = set()

        for ks in result.keystrokes:
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
            self._speed_group.hide()
            return
        self._speed_group.show()

        # ── Helper: compute rolling mean from a stream ──
        window = self._rt_window_spin.value()

        def rolling(
            positions: list[int], rts: list[float]
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
        legend = self._speed_chart.addLegend(
            offset=(-10, 10), labelTextSize="9pt"
        )
        legend.setBrush(pg.mkBrush(30, 30, 30, 180))

        y_max = 0.0

        # ── Green: all keystrokes ──
        x_all, y_all = rolling(all_pos, all_rt)
        self._speed_chart.plot(
            x_all, y_all, pen=pg.mkPen(COLOR_SUCCESS, width=2), name="All"
        )
        y_max = max(y_max, float(y_all.max()))

        # ── Blue: settled letters ──
        if len(settled_rt) >= 2:
            x_set, y_set = rolling(settled_pos, settled_rt)
            self._speed_chart.plot(
                x_set, y_set, pen=pg.mkPen("#44aaff", width=2), name="Settled"
            )
            y_max = max(y_max, float(y_set.max()))

        # ── Cyan: spacebar ──
        if len(space_rt) >= 2:
            x_sp, y_sp = rolling(space_pos, space_rt)
            self._speed_chart.plot(
                x_sp, y_sp, pen=pg.mkPen("#44cccc", width=2), name="Space"
            )
            y_max = max(y_max, float(y_sp.max()))

        # ── Error markers (red dots on the "All" line) ──
        err_x: list[int] = []
        err_y: list[float] = []
        for xi, yi in zip(x_all.tolist(), y_all.tolist()):
            if int(xi) in error_set:
                err_x.append(int(xi))
                err_y.append(float(yi))

        if err_x:
            self._speed_chart.plot(
                np.array(err_x, dtype=np.float64),
                np.array(err_y, dtype=np.float64),
                pen=None,
                symbol="o",
                symbolSize=7,
                symbolBrush=COLOR_ERROR,
                symbolPen=None,
            )

        # ── Target RT line (speed mode) ──
        if speed_result is not None and speed_result.target_wpm > 0:
            target_rt = 12000.0 / speed_result.target_wpm
            self._speed_chart.addLine(
                y=target_rt,
                pen=pg.mkPen(
                    COLOR_TEXT_SECONDARY,
                    width=1,
                    style=Qt.PenStyle.DashLine,
                ),
            )

        # ── Y range ──
        if y_max > 0:
            self._speed_chart.getViewBox().setYRange(
                0, y_max * 1.15, padding=0
            )

    def _on_rt_window_changed(self) -> None:
        """Redraw the speed chart with the new rolling window size."""
        if self._last_result is not None:
            self._update_speed_chart(
                self._last_result,
                self._last_speed_result,
                self._last_settled,
            )

    def _start_rest_timer(self) -> None:
        self._rest_remaining = self._rest_seconds
        self._update_rest_display()
        self._continue_btn.setEnabled(True)  # Always enabled — rest is a suggestion
        self._rest_timer.start()

    def _on_rest_tick(self) -> None:
        self._rest_remaining = max(0, self._rest_remaining - 1)
        self._update_rest_display()
        if self._rest_remaining <= 0:
            self._rest_timer.stop()

    def _update_rest_display(self) -> None:
        if self._rest_remaining > 0:
            self._rest_label.setText(
                f"Suggested rest: {self._rest_remaining}s"
            )
            self._rest_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        else:
            self._rest_label.setText("Rest complete")
            self._rest_label.setStyleSheet(f"color: {COLOR_SUCCESS};")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        """Allow continuing to the next run by pressing Return/Enter."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_continue()
        else:
            super().keyPressEvent(event)

    @property
    def rest_remaining(self) -> int:
        """Seconds remaining in the rest suggestion countdown."""
        return self._rest_remaining

    def _on_continue(self) -> None:
        self._rest_timer.stop()
        self.continue_clicked.emit()
