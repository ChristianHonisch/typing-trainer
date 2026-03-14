"""Session dashboard: session info, spaced repetition alerts, advancement progress."""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.core.letter_manager import (
    AdvancementCheck,
    DegradationWarning,
    PerLetterProgress,
)
from typing_trainer.core.spaced_repetition import ReviewStatus
from typing_trainer.models.session import Session
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_WARNING,
    app_font,
    make_selectable,
)


class SessionDashboard(QWidget):
    """Displays current session status and spaced repetition info."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Session info
        session_group = QGroupBox("Current Session")
        session_group.setFont(app_font(11))
        session_layout = QVBoxLayout(session_group)
        self._session_label = QLabel("No active session")
        self._session_label.setFont(app_font(11))
        self._session_label.setWordWrap(True)
        make_selectable(self._session_label)
        session_layout.addWidget(self._session_label)
        layout.addWidget(session_group)

        # Advancement progress
        advance_group = QGroupBox("Next Letter")
        advance_group.setFont(app_font(11))
        advance_layout = QVBoxLayout(advance_group)
        self._advance_label = QLabel("")
        self._advance_label.setFont(app_font(11))
        self._advance_label.setWordWrap(True)
        make_selectable(self._advance_label)
        advance_layout.addWidget(self._advance_label)
        layout.addWidget(advance_group)

        # Review alerts
        review_group = QGroupBox("Review Status")
        review_group.setFont(app_font(11))
        review_layout = QVBoxLayout(review_group)
        self._review_label = QLabel("No reviews due")
        self._review_label.setFont(app_font(11))
        self._review_label.setWordWrap(True)
        make_selectable(self._review_label)
        review_layout.addWidget(self._review_label)
        layout.addWidget(review_group)

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
        """Format a duration in seconds as ``Xm Ys`` or ``Xs``."""
        if seconds >= 60:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds}s"

    def update_session_info(
        self,
        session: Session | None,
        session_active_s: int = 0,
        session_elapsed_s: int = 0,
        today_s: int = 0,
    ) -> None:
        """Update the session info display.

        Args:
            session: The current session (or None).
            session_active_s: Active typing time this session (sum of
                run durations), in seconds.
            session_elapsed_s: Wall-clock time since session start, in
                seconds.
            today_s: Total active typing time today (all sessions), in
                seconds.
        """
        if session is None:
            if today_s > 0:
                self._session_label.setText(
                    f"No active session\nToday: {self._format_duration(today_s)}"
                )
            else:
                self._session_label.setText("No active session")
            return

        lines: list[str] = []
        lines.append(f"Runs completed: {session.run_count}")
        lines.append(f"Keystrokes: {session.total_cognitive_keystrokes}")
        if session.run_count > 0:
            lines.append(f"Accuracy: {session.aggregate_accuracy:.1%}")
        active = self._format_duration(session_active_s)
        elapsed = self._format_duration(session_elapsed_s)
        lines.append(f"Active: {active} (elapsed: {elapsed})")
        lines.append(f"Today: {self._format_duration(today_s)}")

        self._session_label.setText("\n".join(lines))

    def update_advancement(
        self,
        check: AdvancementCheck,
        error_window: dict[str, list[bool]] | None = None,
    ) -> None:
        """Update the advancement progress display."""
        if check.next_letter is None:
            self._advance_label.setText("All letters are active!")
            self._advance_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
            return

        # Build rich-text display with structured criteria
        parts: list[str] = []
        parts.append(f"Next letter: <b>'{check.next_letter}'</b>")
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
            # Find the specific blockers
            blockers: list[str] = []
            if not ks_ok:
                blockers.append(f"{ks_need - ks} more keystrokes needed")
            for p in check.per_letter_progress:
                if p.has_enough_data and not p.meets_accuracy:
                    need_text = ""
                    if error_window and p.letter in error_window:
                        need_text = self._compute_need_text(
                            error_window[p.letter],
                            p.window_size,
                            p.required_accuracy,
                        )
                    blockers.append(
                        f"'{p.letter}' accuracy {p.accuracy:.1%}"
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
    def _compute_need_text(
        sequence: list[bool], window: int, required_accuracy: float,
    ) -> str:
        """Compute 'need N keystrokes' text from an error window sequence.

        Args:
            sequence: Boolean list (True=error), oldest-first.
            window: Rolling window size.
            required_accuracy: Accuracy threshold (e.g. 0.95).

        Returns:
            Formatted string like ``" (need 42 keystrokes)"`` or ``""``
            if the letter already meets the threshold.
        """
        max_errors = math.floor(window * (1.0 - required_accuracy))
        error_positions = [i for i, is_err in enumerate(sequence) if is_err]
        n_errors = len(error_positions)
        if n_errors <= max_errors:
            return ""
        excess = n_errors - max_errors
        last_excess_pos = error_positions[excess - 1]
        seq_len = len(sequence)
        if seq_len >= window:
            keystrokes_needed = last_excess_pos + 1
        else:
            grow_room = window - seq_len
            keystrokes_needed = max(0, last_excess_pos + 1 - grow_room)
        return f" (need {keystrokes_needed} keystrokes)"

    @staticmethod
    def _format_letter_progress(
        p: PerLetterProgress,
        error_window: dict[str, list[bool]] | None = None,
    ) -> str:
        """Format a single letter's accuracy progress line."""
        if p.keystrokes_in_window == 0:
            color = COLOR_WARNING
            detail = "no data"
        elif not p.has_enough_data:
            color = COLOR_WARNING
            detail = f"{p.accuracy:.1%} ({p.keystrokes_in_window}/{p.window_size})"
        elif p.meets_accuracy:
            color = COLOR_SUCCESS
            detail = f"{p.accuracy:.1%}"
        else:
            color = COLOR_ERROR
            need_info = ""
            if error_window and p.letter in error_window:
                need_info = SessionDashboard._compute_need_text(
                    error_window[p.letter], p.window_size, p.required_accuracy,
                )
            detail = f"{p.accuracy:.1%} &lt; {p.required_accuracy:.0%}{need_info}"

        data_info = f"({p.keystrokes_in_window}/{p.window_size})"
        return (
            f'&nbsp;&nbsp;<span style="color:{color};">'
            f"{p.letter}: {detail} {data_info}</span>"
        )

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
                f"  '{s.letter}' — stability {s.current_stability:.2f}, "
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
