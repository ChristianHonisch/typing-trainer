"""Post-run statistics display with rest suggestion timer.

Shows:
- Aggregate stats (keystrokes, accuracy, WPM, errors)
- Per-letter error rates
- Per-letter mean reaction times
- Delta vs previous run
- 30-second rest suggestion countdown
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.config import Config
from typing_trainer.core.speed_manager import SpeedRunResult
from typing_trainer.models.run_result import RunResult
from typing_trainer.ui.theme import (
    COLOR_BTN_DISABLED_BG,
    COLOR_BTN_DISABLED_TEXT,
    COLOR_BTN_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
    make_selectable,
)


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
