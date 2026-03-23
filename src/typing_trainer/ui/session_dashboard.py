"""Session dashboard: training status table, advancement progress, review alerts."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.core.letter_manager import (
    AdvancementCheck,
    DegradationWarning,
    PerLetterProgress,
)
from typing_trainer.core.spaced_repetition import ReviewStatus
from typing_trainer.models.letter_state import DisplayMode
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_DARK,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
    make_selectable,
)


@dataclass
class TrainingStatusData:
    """All data needed to populate the Training Status table."""

    session_runs: int = 0
    session_keystrokes: int = 0
    session_training_s: int = 0
    session_elapsed_s: int = 0

    today_runs: int = 0
    today_keystrokes: int = 0
    today_training_s: int = 0
    today_elapsed_s: int = 0

    total_runs: int = 0
    total_keystrokes: int = 0
    total_training_s: int = 0
    total_elapsed_s: int = 0


class SessionDashboard(QWidget):
    """Displays training status, advancement progress, and review info."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display_mode = DisplayMode.NERD
        self._setup_ui()

    def set_display_mode(self, mode: DisplayMode) -> None:
        """Store the display mode for rendering decisions."""
        self._display_mode = mode

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Training status table
        self._status_group = QGroupBox("Training Status")
        self._status_group.setFont(app_font(11))
        status_layout = QVBoxLayout(self._status_group)

        self._status_table = QTableWidget(4, 3)
        self._status_table.setFont(app_font(10))
        self._status_table.setHorizontalHeaderLabels(["Session", "Today", "Total"])
        self._status_table.setVerticalHeaderLabels(
            ["Runs", "Keystrokes", "Training", "Elapsed"]
        )
        self._status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._status_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._status_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Sizing
        h_header = self._status_table.horizontalHeader()
        assert h_header is not None
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        h_header.setFont(app_font(9))
        v_header = self._status_table.verticalHeader()
        assert v_header is not None
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v_header.setDefaultSectionSize(22)
        v_header.setFont(app_font(9))

        self._status_table.setMaximumHeight(120)

        # Style
        self._status_table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {COLOR_BG_DARK};
                color: {COLOR_TEXT_PRIMARY};
                gridline-color: {COLOR_BG_TERTIARY};
                border: none;
            }}
            QHeaderView::section {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_BG_TERTIARY};
                padding: 2px 4px;
            }}
            QTableWidget::item {{
                padding: 2px 4px;
            }}
            """
        )

        # Initialize cells
        for row in range(4):
            for col in range(3):
                item = QTableWidgetItem("-")
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self._status_table.setItem(row, col, item)

        status_layout.addWidget(self._status_table)
        layout.addWidget(self._status_group)

        # Advancement progress
        self._advance_group = QGroupBox("Next Letter")
        self._advance_group.setFont(app_font(11))
        advance_layout = QVBoxLayout(self._advance_group)
        self._advance_label = QLabel("")
        self._advance_label.setFont(app_font(11))
        self._advance_label.setWordWrap(True)
        make_selectable(self._advance_label)
        advance_layout.addWidget(self._advance_label)
        layout.addWidget(self._advance_group)

        # Review alerts
        self._review_group = QGroupBox("Review Status")
        self._review_group.setFont(app_font(11))
        review_layout = QVBoxLayout(self._review_group)
        self._review_label = QLabel("No reviews due")
        self._review_label.setFont(app_font(11))
        self._review_label.setWordWrap(True)
        make_selectable(self._review_label)
        review_layout.addWidget(self._review_label)
        layout.addWidget(self._review_group)

        # Warnings
        self._warning_label = QLabel("")
        self._warning_label.setFont(app_font(11))
        self._warning_label.setStyleSheet(f"color: {COLOR_ERROR};")
        self._warning_label.setWordWrap(True)
        make_selectable(self._warning_label)
        self._warning_label.hide()
        layout.addWidget(self._warning_label)

        layout.addStretch()

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format a duration in seconds as ``Xh Ym`` / ``Xm Ys`` / ``Xs``."""
        if seconds >= 3600:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}h {m:02d}m"
        if seconds >= 60:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds}s"

    @staticmethod
    def _format_count(n: int) -> str:
        """Format an integer with thousands separator."""
        return f"{n:,}"

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = self._status_table.item(row, col)
        if item is not None:
            item.setText(text)

    def update_session_info(self, data: TrainingStatusData) -> None:
        """Update the training status table."""
        fmt_d = self._format_duration
        fmt_c = self._format_count

        # Row 0: Runs
        self._set_cell(0, 0, fmt_c(data.session_runs))
        self._set_cell(0, 1, fmt_c(data.today_runs))
        self._set_cell(0, 2, fmt_c(data.total_runs))

        # Row 1: Keystrokes
        self._set_cell(1, 0, fmt_c(data.session_keystrokes))
        self._set_cell(1, 1, fmt_c(data.today_keystrokes))
        self._set_cell(1, 2, fmt_c(data.total_keystrokes))

        # Row 2: Training time (active typing)
        self._set_cell(2, 0, fmt_d(data.session_training_s))
        self._set_cell(2, 1, fmt_d(data.today_training_s))
        self._set_cell(2, 2, fmt_d(data.total_training_s))

        # Row 3: Elapsed time (wall clock)
        self._set_cell(3, 0, fmt_d(data.session_elapsed_s))
        self._set_cell(3, 1, fmt_d(data.today_elapsed_s))
        self._set_cell(3, 2, fmt_d(data.total_elapsed_s))

    def update_advancement(
        self,
        check: AdvancementCheck,
        error_window: dict[str, list[bool]] | None = None,
        space_median_rt: float = 0.0,
    ) -> None:
        """Update the advancement progress display."""
        if check.next_letter is None:
            self._advance_label.setText("All letters are active!")
            self._advance_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
            return

        parts: list[str] = []
        parts.append(f"Next letter: <b>'{check.next_letter}'</b>")
        if space_median_rt > 0:
            parts.append(f"Space baseline: {space_median_rt:.0f}ms")
        parts.append("")

        # Criterion 1: Keystroke volume
        ks = check.keystrokes_since_introduction
        ks_need = check.keystrokes_needed
        ks_ok = ks >= ks_need
        ks_icon = self._pass_icon() if ks_ok else self._fail_icon()
        parts.append(f"{ks_icon} Keystrokes since last letter: {ks} / {ks_need}")
        parts.append("")

        # Criterion 2: Per-letter accuracy
        if check.per_letter_progress:
            req = check.per_letter_progress[0].required_accuracy
            all_acc_ok = all(
                p.meets_accuracy and p.has_enough_data
                for p in check.per_letter_progress
            )
            acc_icon = self._pass_icon() if all_acc_ok else self._fail_icon()
            parts.append(
                f"{acc_icon} Per-letter accuracy "
                f"(last {check.per_letter_progress[0].window_size}, "
                f"need &ge;{req:.0%}):"
            )
            for p in check.per_letter_progress:
                parts.append(self._format_letter_progress(p, error_window))

        parts.append("")
        if check.can_advance:
            parts.append(
                f'<span style="color:{COLOR_SUCCESS};"><b>Ready to advance!</b></span>'
            )
        else:
            blockers: list[str] = []
            if not ks_ok:
                blockers.append(f"{ks_need - ks} more keystrokes needed")
            for p in check.per_letter_progress:
                if p.has_enough_data and not p.meets_accuracy:
                    need_n = 0
                    if error_window and p.letter in error_window:
                        need_n = self._compute_keystrokes_needed(
                            error_window[p.letter],
                            p.window_size,
                            p.required_accuracy,
                        )
                    need_text = f" (need {need_n})" if need_n > 0 else ""
                    blockers.append(
                        f"'{p.letter}' {p.accuracy:.1%}"
                        f" < {p.required_accuracy:.0%}{need_text}"
                    )
                elif not p.has_enough_data:
                    blockers.append(
                        f"'{p.letter}' needs more data "
                        f"({p.keystrokes_in_window}/{p.window_size})"
                    )
            if blockers:
                parts.append(
                    f'<span style="color:{COLOR_WARNING};">'
                    f"Blocked: {'; '.join(blockers)}"
                    f"</span>"
                )

        self._advance_label.setTextFormat(Qt.TextFormat.RichText)
        self._advance_label.setText("<br>".join(parts))
        if check.can_advance:
            self._advance_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
        else:
            self._advance_label.setStyleSheet("")

    @staticmethod
    def _pass_icon() -> str:
        return f'<span style="color:{COLOR_SUCCESS};">\u2714</span>'

    @staticmethod
    def _fail_icon() -> str:
        return f'<span style="color:{COLOR_ERROR};">\u2718</span>'

    @staticmethod
    def _accuracy_bar(accuracy: float, threshold: float = 0.95) -> str:
        """Build an HTML accuracy bar (12 chars, 92%–100%, ~0.67%/step).

        Characters:
          ``·``  filler (grey)
          ``|``  threshold marker (bright)
          ``*``  current accuracy (green/yellow/red)
          ``<``  accuracy below 92% (red)
        """
        lo = 0.92
        hi = 1.00
        width = 12

        thresh_pos = round((threshold - lo) / (hi - lo) * (width - 1))
        if accuracy < lo:
            acc_pos = -1
        else:
            acc_pos = round((accuracy - lo) / (hi - lo) * (width - 1))
            acc_pos = max(0, min(acc_pos, width - 1))

        # Determine star color
        if accuracy >= threshold:
            star_color = COLOR_SUCCESS
        elif accuracy >= threshold - 0.02:
            star_color = COLOR_WARNING
        else:
            star_color = COLOR_ERROR

        parts: list[str] = []
        for i in range(width):
            if acc_pos == -1 and i == 0:
                parts.append(f'<span style="color:{COLOR_ERROR};">&lt;</span>')
            elif i == acc_pos and i == thresh_pos:
                # Accuracy exactly at threshold — show star
                parts.append(f'<span style="color:{star_color};">*</span>')
            elif i == acc_pos:
                parts.append(f'<span style="color:{star_color};">*</span>')
            elif i == thresh_pos:
                parts.append(f'<span style="color:{COLOR_TEXT_BRIGHT};">|</span>')
            else:
                parts.append(f'<span style="color:{COLOR_TEXT_MUTED};">\u00b7</span>')

        return "".join(parts)

    def _format_letter_progress(
        self,
        p: PerLetterProgress,
        error_window: dict[str, list[bool]] | None = None,
    ) -> str:
        """Format a single letter's accuracy progress line.

        In all modes, shows a compact bar + percentage + status.
        In EXTREME_NERD mode, appends keystroke details and error count.
        """
        # Compute need text
        need_count = 0
        if (
            p.has_enough_data
            and not p.meets_accuracy
            and error_window
            and p.letter in error_window
        ):
            need_count = self._compute_keystrokes_needed(
                error_window[p.letter],
                p.window_size,
                p.required_accuracy,
            )

        # Bar
        bar = self._accuracy_bar(p.accuracy, p.required_accuracy)

        # Status
        if p.keystrokes_in_window == 0:
            status = "no data"
        elif not p.has_enough_data:
            status = f"{p.keystrokes_in_window}/{p.window_size}ks"
        elif p.meets_accuracy:
            status = "\u2713"
        elif need_count > 0:
            status = f"needs {need_count} correct"
        else:
            status = "\u2717"

        # Percentage (one decimal place)
        pct = f"{p.accuracy:.1%}"

        # Build line
        line = (
            f'<span style="font-family:monospace;">'
            f"{p.letter} {bar} {pct} {status}"
            f"</span>"
        )
        return line

    @staticmethod
    def _compute_keystrokes_needed(
        window: list[bool],
        window_size: int,
        required_accuracy: float,
    ) -> int:
        """Compute how many correct keystrokes until accuracy meets threshold.

        Each correct keystroke shifts the rolling window forward by one
        position.  Excess errors must "fall off" the left edge of the
        window before accuracy can reach the required level.  Returns
        the number of correct keystrokes needed for the last excess
        error to exit the window.

        Returns 0 if the letter already meets the threshold.
        """
        max_errors = int(window_size * (1.0 - required_accuracy))
        error_positions = [i for i, is_err in enumerate(window) if is_err]

        if len(error_positions) <= max_errors:
            return 0

        # The error that needs to fall off is the one at the boundary:
        # if we're allowed max_errors, the (n - max_errors)th error
        # (from the end) is the last excess one that must leave.
        excess_error_idx = len(error_positions) - max_errors - 1
        excess_error_pos = error_positions[excess_error_idx]

        # Distance from the left edge of the current window
        left_edge = max(0, len(window) - window_size)

        if excess_error_pos < left_edge:
            return 0  # already outside the window

        # Each correct keystroke moves the left edge right by 1
        return excess_error_pos - left_edge + 1

    def update_review_status(self, statuses: list[ReviewStatus]) -> None:
        """Update the review status display."""
        due = [s for s in statuses if s.is_due]
        if not due:
            self._review_label.setText("No reviews due")
            self._review_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
            return

        lines: list[str] = []
        lines.append(f"{len(due)} letter(s) due for review:")
        for s in due:
            lines.append(
                f"  '{s.letter}' \u2014 stability {s.current_stability:.2f}, "
                f"last practiced {s.hours_since_practice:.0f}h ago"
            )
        self._review_label.setText("\n".join(lines))
        self._review_label.setStyleSheet(f"color: {COLOR_ALERT};")

    def update_warnings(self, warnings: list[DegradationWarning]) -> None:
        """Show degradation warnings."""
        if not warnings:
            self._warning_label.hide()
            return

        lines: list[str] = []
        for w in warnings:
            lines.append(
                f"Warning: '{w.letter}' has degraded "
                f"(error rate {w.current_error_rate:.1%}, "
                f"{w.sessions_below_threshold} sessions below threshold)"
            )
        self._warning_label.setText("\n".join(lines))
        self._warning_label.show()
