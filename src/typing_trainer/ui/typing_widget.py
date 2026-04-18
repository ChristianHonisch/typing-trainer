"""The core typing exercise widget.

Displays the full target text with monospace font.
Captures keystrokes with millisecond timestamps.
Shows: current cursor position, correct chars dimmed, errors in red.
Running accuracy display at the top.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QElapsedTimer, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QKeyEvent,
    QPainter,
    QPen,
    QResizeEvent,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.core.engine import TypingEngine
from typing_trainer.models.letter_state import ErrorType
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_CURSOR,
    COLOR_BG_INPUT,
    COLOR_ERROR,
    COLOR_ERROR_BG,
    COLOR_HIGHLIGHT_WEAK,
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)


class CursorOverlayTextEdit(QTextEdit):
    """QTextEdit subclass that paints a cursor highlight overlay.

    Standard QTextEdit does not render background/selection formatting
    on trailing whitespace at word-wrap boundaries.  This subclass
    works around that limitation by painting the cursor highlight as
    an overlay in paintEvent, after the normal text has been rendered.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._highlight_pos: int = -1
        self._highlight_char: str = ""
        self._highlight_error: bool = False

    def set_cursor_highlight(self, pos: int, char: str) -> None:
        """Set which character position to highlight as the cursor.

        Args:
            pos: Document character position (-1 to disable).
            char: The character at that position (used for display).
        """
        self._highlight_pos = pos
        self._highlight_char = char
        vp = self.viewport()
        assert vp is not None
        vp.update()

    def set_cursor_error(self, error: bool) -> None:
        """Set the cursor highlight to error (red) or normal (grey).

        Used by error handling modes to indicate a rejected keystroke.
        """
        self._highlight_error = error
        vp = self.viewport()
        assert vp is not None
        vp.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Paint normal text, then overlay the cursor highlight."""
        super().paintEvent(event)

        if self._highlight_pos < 0:
            return

        # Create a QTextCursor at the highlight position to get its
        # pixel location within the viewport.
        tc = self.textCursor()
        tc.setPosition(self._highlight_pos)
        cursor_rect = self.cursorRect(tc)

        # Compute character cell width from font metrics.
        font = self.currentFont()
        fm = QFontMetricsF(font)
        char_width = fm.horizontalAdvance("M")  # monospace: all chars same width

        # Build the highlight rectangle.
        x = float(cursor_rect.x())
        y = float(cursor_rect.y())
        h = float(cursor_rect.height())
        highlight_rect = QRectF(x, y, char_width, h)

        painter = QPainter(self.viewport())
        try:
            # Draw background — red when a keystroke was rejected
            bg_color = COLOR_ERROR if self._highlight_error else COLOR_BG_CURSOR
            painter.fillRect(highlight_rect, QColor(bg_color))

            # Draw the character (or middle-dot for space)
            display_char = (
                "\u00b7" if self._highlight_char == " " else self._highlight_char
            )
            painter.setFont(font)
            painter.setPen(QPen(QColor(COLOR_TEXT_BRIGHT)))
            painter.drawText(highlight_rect, Qt.AlignmentFlag.AlignCenter, display_char)
        finally:
            painter.end()


class TypingWidget(QWidget):
    """Widget for a single typing run.

    Signals:
        run_finished: emitted when the run is complete or failed.
    """

    run_finished = pyqtSignal()
    run_aborted = pyqtSignal()

    def __init__(
        self,
        engine: TypingEngine,
        highlight_letters: set[str] | frozenset[str] = frozenset(),
        single_letter_mode: bool = False,
        show_prev_result: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self._highlight_letters: frozenset[str] = frozenset(highlight_letters)
        self._single_letter_mode = single_letter_mode
        self._show_prev_result = show_prev_result
        self._timer = QElapsedTimer()
        self._abort_pending = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Top bar: accuracy and progress
        top_bar = QHBoxLayout()

        self._accuracy_label = QLabel("Accuracy: 100.0%")
        self._accuracy_label.setFont(app_font(14))
        top_bar.addWidget(self._accuracy_label)

        top_bar.addStretch()

        self._progress_label = QLabel("0 / 0")
        self._progress_label.setFont(app_font(14))
        top_bar.addWidget(self._progress_label)

        top_bar.addStretch()

        self._mode_label = QLabel("")
        self._mode_label.setFont(app_font(11))
        self._mode_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        top_bar.addWidget(self._mode_label)

        layout.addLayout(top_bar)

        # Text display (custom subclass for cursor overlay)
        self._text_display = CursorOverlayTextEdit()
        self._text_display.setReadOnly(True)
        self._text_display.setFont(app_font(18))
        self._text_display.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_MUTED};
                border: none;
                padding: 20px;
                line-height: 1.8;
            }}
            """
        )
        self._text_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Center the text display at 2/3 width: stretch(1) | text(4) | stretch(1)
        text_row = QHBoxLayout()
        text_row.setContentsMargins(0, 0, 0, 0)
        text_row.addStretch(1)
        text_row.addWidget(self._text_display, stretch=4)
        text_row.addStretch(1)
        layout.addLayout(text_row, stretch=1)

        # Status bar with abort button
        status_bar = QHBoxLayout()

        self._status_label = QLabel("")
        self._status_label.setFont(app_font(11))
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_bar.addWidget(self._status_label, stretch=1)

        self._abort_btn = QPushButton("Abort")
        self._abort_btn.setFont(app_font(11))
        self._abort_btn.setFixedWidth(80)
        self._abort_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_ERROR};
                color: {COLOR_TEXT_BRIGHT};
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ALERT};
            }}
            """
        )
        self._abort_btn.clicked.connect(self._on_abort_confirmed)
        self._abort_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._abort_btn.hide()
        status_bar.addWidget(self._abort_btn)

        layout.addLayout(status_bar)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def start_run(self) -> None:
        """Initialize the display for the current engine run."""
        self._timer.start()
        self._render_text()
        self._update_stats()
        # Map internal mode/practice to user-facing preset names
        _PRESET_NAMES = {
            ("relearning", "random_strings"): "Learn Keys",
            ("relearning", "fix_keys"): "Fix Keys",
            ("speed", "random_words"): "Build Speed",
            ("transition", "bigram_words"): "Smooth Pairs",
        }
        key = (self.engine.state.mode.value, self.engine.state.practice_type.value)
        preset_name = _PRESET_NAMES.get(key)
        if preset_name is not None:
            self._mode_label.setText(preset_name)
        else:
            mode_text = self.engine.state.mode.value.replace("_", " ").title()
            practice_text = self.engine.state.practice_type.value.replace("_", " ")
            self._mode_label.setText(f"{mode_text} | {practice_text}")
        self._status_label.setText("Start typing...")
        self.setFocus()

    def _render_text(self) -> None:
        """Render the target text with color coding.

        In single-letter mode, only the current character is shown in
        large centered font.  Otherwise, the full target text is
        rendered with per-character color coding and a cursor overlay.
        """
        if self._single_letter_mode:
            self._render_single_letter()
            return

        self._text_display.clear()
        cursor = self._text_display.textCursor()

        target = self.engine.state.target_text
        pos = self.engine.state.cursor_position
        first_inputs = self.engine.state.first_inputs

        # Resolve font family once for the char format
        font_family = app_font(18).family()

        for i, char in enumerate(target):
            fmt = QTextCharFormat()
            fmt.setFontFamily(font_family)
            fmt.setFontPointSize(18)

            if i < pos:
                if i in first_inputs:
                    actual, error_type = first_inputs[i]
                    if error_type == ErrorType.COGNITIVE_ERROR:
                        # Error: show what the user typed in red
                        fmt.setForeground(QColor(COLOR_ERROR))
                        fmt.setBackground(QColor(COLOR_ERROR_BG))
                        char = actual
                        # Prevent erroneous spaces from creating new
                        # word-wrap points that rearrange the text.
                        if actual == " ":
                            char = "\u00a0"  # non-breaking space
                    else:
                        # Correct: dimmed
                        fmt.setForeground(QColor(COLOR_SUCCESS))
                else:
                    # Correct (no first_input record means it was correct)
                    fmt.setForeground(QColor(COLOR_SUCCESS))
            else:
                # Upcoming (including cursor position).
                # Positions the user already typed but backspaced over
                # retain their error/correct state so the user can see
                # what they previously entered.
                if i in first_inputs:
                    actual, error_type = first_inputs[i]
                    if error_type == ErrorType.COGNITIVE_ERROR:
                        fmt.setForeground(QColor(COLOR_ERROR))
                        fmt.setBackground(QColor(COLOR_ERROR_BG))
                        char = actual
                        if actual == " ":
                            char = "\u00a0"
                    else:
                        fmt.setForeground(QColor(COLOR_SUCCESS))
                elif char in self._highlight_letters:
                    # Weak letter: pale yellow for attention
                    fmt.setForeground(QColor(COLOR_HIGHLIGHT_WEAK))
                else:
                    # Normal upcoming: dim grey
                    fmt.setForeground(QColor(COLOR_TEXT_MUTED))

            cursor.insertText(char, fmt)

        self._text_display.setTextCursor(cursor)

        # Defer vertical centering to after Qt completes the layout pass
        QTimer.singleShot(0, self._apply_vertical_centering)

        # Set the overlay cursor highlight position.
        if pos < len(target):
            self._text_display.set_cursor_highlight(pos, target[pos])
        else:
            self._text_display.set_cursor_highlight(-1, "")

    def _render_single_letter(self) -> None:
        """Render only the current character in large centered font.

        Optionally shows the result of the previous keystroke above
        the main letter (green checkmark or red expected->actual).
        """
        self._text_display.clear()
        cursor = self._text_display.textCursor()

        target = self.engine.state.target_text
        pos = self.engine.state.cursor_position
        first_inputs = self.engine.state.first_inputs
        font_family = app_font(18).family()

        # Center-align the text block
        block_fmt = QTextBlockFormat()
        block_fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cursor.setBlockFormat(block_fmt)

        # Previous keystroke result (optional)
        # In correction-gated modes the cursor can stay on the same
        # position after an error, so prefer the current position when
        # it already has a recorded attempt.
        result_idx: int | None = None
        if pos in first_inputs:
            result_idx = pos
        elif pos > 0:
            result_idx = pos - 1

        if self._show_prev_result and result_idx is not None:
            prev_fmt = QTextCharFormat()
            prev_fmt.setFontFamily(font_family)
            prev_fmt.setFontPointSize(24)

            if result_idx in first_inputs:
                actual, error_type = first_inputs[result_idx]
                if error_type == ErrorType.COGNITIVE_ERROR:
                    expected_ch = target[result_idx]
                    exp_display = "\u00b7" if expected_ch == " " else expected_ch
                    act_display = "\u00b7" if actual == " " else actual
                    prev_fmt.setForeground(QColor(COLOR_ERROR))
                    cursor.insertText(f"{exp_display}\u2192{act_display}", prev_fmt)
                else:
                    prev_fmt.setForeground(QColor(COLOR_SUCCESS))
                    cursor.insertText("\u2713", prev_fmt)
            else:
                prev_fmt.setForeground(QColor(COLOR_SUCCESS))
                cursor.insertText("\u2713", prev_fmt)

            cursor.insertText("\n")

        # Main letter
        if pos < len(target):
            char = target[pos]
            display = "\u00b7" if char == " " else char

            main_fmt = QTextCharFormat()
            main_fmt.setFontFamily(font_family)
            main_fmt.setFontPointSize(72)
            color = (
                COLOR_HIGHLIGHT_WEAK
                if char in self._highlight_letters
                else COLOR_TEXT_BRIGHT
            )
            main_fmt.setForeground(QColor(color))
            cursor.insertText(display, main_fmt)

        self._text_display.setTextCursor(cursor)

        # No cursor overlay needed in single-letter mode
        self._text_display.set_cursor_highlight(-1, "")

        QTimer.singleShot(0, self._apply_vertical_centering)

    def _apply_vertical_centering(self) -> None:
        """Center text vertically using viewport margins."""
        doc = self._text_display.document()
        if doc is None:
            return

        # Reset viewport margins to measure natural doc height
        self._text_display.setViewportMargins(0, 0, 0, 0)

        viewport = self._text_display.viewport()
        if viewport is None:
            return

        doc.adjustSize()
        doc_height = doc.size().height()
        # Restore document width — adjustSize() shrinks it to content width,
        # which breaks AlignCenter horizontal centering.
        doc.setTextWidth(viewport.width())

        widget_height = self._text_display.height()

        top_margin = max(0, int((widget_height - doc_height) / 2))
        self._text_display.setViewportMargins(0, top_margin, 0, 0)

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # type: ignore[override]
        """Re-center text vertically when the widget is resized."""
        super().resizeEvent(event)
        if hasattr(self, "_text_display"):
            self._apply_vertical_centering()

    def _update_stats(self) -> None:
        """Update the accuracy and progress displays."""
        state = self.engine.state
        accuracy = state.accuracy * 100
        total = state.total_scored_keystrokes
        target_len = len(state.target_text)
        pos = state.cursor_position

        # Color accuracy based on proximity to fail threshold
        threshold = state.fail_threshold * 100
        if accuracy >= threshold + 2:
            color = COLOR_SUCCESS
        elif accuracy >= threshold:
            color = COLOR_WARNING
        else:
            color = COLOR_ERROR

        # Floor-truncate so the display never exceeds the raw value
        # (avoids showing "95.0%" when actual is 94.98%).
        acc_display = math.floor(accuracy * 10) / 10
        self._accuracy_label.setText(f"Accuracy: {acc_display:.1f}%")
        self._accuracy_label.setStyleSheet(f"color: {color};")
        self._progress_label.setText(f"{pos} / {target_len}")

    def _on_abort_confirmed(self) -> None:
        """Handle confirmed abort (button click or second Escape)."""
        self._abort_pending = False
        self._abort_btn.hide()
        self.run_aborted.emit()

    def _dismiss_abort(self) -> None:
        """Dismiss the abort confirmation and resume typing."""
        self._abort_pending = False
        self._abort_btn.hide()
        self._status_label.setText("")
        self._status_label.setStyleSheet("")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        """Handle key press events during the typing run."""
        if self.engine.state.is_finished:
            return

        key = event.key()
        text = event.text()

        # --- Abort confirmation flow ---
        if key == Qt.Key.Key_Escape:
            if self._abort_pending:
                self._on_abort_confirmed()
            else:
                self._abort_pending = True
                self._status_label.setText(
                    "Press Escape again to abort, any other key to resume"
                )
                self._status_label.setStyleSheet(f"color: {COLOR_ALERT};")
                self._abort_btn.show()
            return

        # Any non-Escape key dismisses the abort confirmation
        if self._abort_pending:
            self._dismiss_abort()
            # Fall through to process the key normally

        # Get timestamp in milliseconds
        timestamp_ms = self._timer.elapsed()

        # Handle backspace
        if key == Qt.Key.Key_Backspace:
            self.engine.process_keystroke("\b", timestamp_ms)
            self._text_display.set_cursor_error(False)
            self._render_text()
            self._update_stats()
            return

        # Ignore modifier-only keys, tab, etc.
        if not text or key in (
            Qt.Key.Key_Shift,
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            return

        # Process the character
        pos_before = self.engine.state.cursor_position
        char = text[0]
        result = self.engine.process_keystroke(char, timestamp_ms)

        # Visual feedback: turn cursor box red when keystroke was rejected
        # (force_correct: cursor didn't advance) or blocked (force_backspace:
        # correction gate returned None, or error just set correction pos).
        cursor_stuck = self.engine.state.cursor_position == pos_before
        error_feedback = (
            result is None  # rejected by correction gate
            or (
                cursor_stuck
                and result is not None
                and result.error_type == ErrorType.COGNITIVE_ERROR
            )
            or self.engine.state.error_correction_pos is not None
        )
        self._text_display.set_cursor_error(error_feedback)

        self._render_text()
        self._update_stats()

        # Check if run ended
        if self.engine.state.is_finished:
            if self.engine.state.is_failed:
                self._status_label.setText(
                    "Run FAILED - accuracy dropped below threshold"
                )
                self._status_label.setStyleSheet(
                    f"color: {COLOR_ERROR}; font-weight: bold;"
                )
            else:
                self._status_label.setText("Run complete!")
                self._status_label.setStyleSheet(
                    f"color: {COLOR_SUCCESS}; font-weight: bold;"
                )
            self.run_finished.emit()
