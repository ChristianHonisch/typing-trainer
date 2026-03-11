"""Error classification: motor overflow, burst repeat, cognitive error.

Motor overflow: same key pressed twice within the motor_overflow_window (default 80ms).
This is an unintentional double-tap, not a cognitive mistake.

Burst repeat: same key pressed 3+ times consecutively (each within burst_max_interval_ms),
with >50% of presses being errors. The first error is kept; subsequent errors are
reclassified as BURST_REPEAT and excluded from accuracy.

Swap detection: two consecutive cognitive errors where expected/actual chars are
transposed (e.g., typed "ne" when target was "en"). Tracked as a diagnostic metric
but does NOT change accuracy treatment — both errors still count.

All same-key intervals are logged regardless of classification for later
per-user calibration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from typing_trainer.models.letter_state import ErrorType


@dataclass
class SameKeyInterval:
    """Record of a same-key event for calibration analysis."""

    char: str
    interval_ms: int
    classified_as_overflow: bool
    position: int


@dataclass
class ClassificationResult:
    """Result of classifying a single keystroke."""

    error_type: ErrorType
    is_same_key: bool = False
    same_key_interval_ms: int | None = None
    is_swap: bool = False
    """True if this keystroke is part of a transposition (swap) error pair."""


class ErrorClassifier:
    """Classifies keystrokes as correct, cognitive error, motor overflow, or burst repeat.

    Stateful: tracks previous keystrokes to detect motor overflow, burst
    repeats, and swap errors.
    """

    def __init__(
        self,
        motor_overflow_window_ms: int = 80,
        burst_max_interval_ms: int = 500,
    ) -> None:
        self.motor_overflow_window_ms = motor_overflow_window_ms
        self.burst_max_interval_ms = burst_max_interval_ms
        self._prev_actual_char: str | None = None
        self._prev_timestamp_ms: int | None = None

        # All same-key intervals for calibration analysis
        self.same_key_intervals: list[SameKeyInterval] = []

        # --- Burst tracking ---
        # Tracks consecutive same-actual-char sequences (including motor overflow).
        # When a burst is detected (>=3 same char, >=50% errors), subsequent
        # cognitive errors are reclassified as BURST_REPEAT.
        self._burst_char: str | None = None
        self._burst_count: int = 0
        self._burst_error_count: int = 0

        # --- Swap tracking ---
        # Previous keystroke info for swap detection (only for non-overflow,
        # non-burst, non-backspace keystrokes that advance the cursor).
        self._prev_expected_for_swap: str | None = None
        self._prev_actual_for_swap: str | None = None
        self._prev_was_cognitive_error: bool = False
        self.swap_count: int = 0

    def classify(
        self,
        expected_char: str,
        actual_char: str,
        timestamp_ms: int,
        position: int,
    ) -> ClassificationResult:
        """Classify a single keystroke.

        Args:
            expected_char: The character the user was supposed to type.
            actual_char: The character the user actually typed.
            timestamp_ms: Timestamp of this keystroke in milliseconds.
            position: Position in the target text.

        Returns:
            ClassificationResult with the error type and same-key info.
        """
        is_same_key = (
            self._prev_actual_char is not None
            and actual_char == self._prev_actual_char
        )
        same_key_interval_ms: int | None = None

        if is_same_key and self._prev_timestamp_ms is not None:
            same_key_interval_ms = timestamp_ms - self._prev_timestamp_ms

            # Log for calibration.
            # A same-key repeat is only overflow if it's fast AND the
            # expected char differs (legitimate double-letters are exempt).
            classified_as_overflow = (
                same_key_interval_ms < self.motor_overflow_window_ms
                and actual_char != expected_char
            )
            self.same_key_intervals.append(
                SameKeyInterval(
                    char=actual_char,
                    interval_ms=same_key_interval_ms,
                    classified_as_overflow=classified_as_overflow,
                    position=position,
                )
            )

            if classified_as_overflow and actual_char != expected_char:
                # Motor overflow: same key repeated rapidly, but NOT the
                # expected character.  If the expected char matches the
                # actual char, this is a legitimate double-letter (e.g.
                # "ss" in "essen") typed quickly, not an accidental
                # double-tap.
                self._extend_burst(actual_char, timestamp_ms, is_error=True)
                return ClassificationResult(
                    error_type=ErrorType.MOTOR_OVERFLOW,
                    is_same_key=True,
                    same_key_interval_ms=same_key_interval_ms,
                )

        # Base classification (correct or cognitive error)
        if actual_char == expected_char:
            base_error_type = ErrorType.CORRECT
        else:
            base_error_type = ErrorType.COGNITIVE_ERROR

        # --- Burst detection ---
        is_error = base_error_type == ErrorType.COGNITIVE_ERROR
        interval_ms = same_key_interval_ms  # None if not same key
        in_burst = self._update_burst(actual_char, timestamp_ms, interval_ms, is_error)

        if in_burst and base_error_type == ErrorType.COGNITIVE_ERROR:
            base_error_type = ErrorType.BURST_REPEAT

        # --- Swap detection ---
        is_swap = False
        if base_error_type == ErrorType.COGNITIVE_ERROR and self._prev_was_cognitive_error:
            # Check if expected/actual are transposed with previous keystroke
            if (
                self._prev_expected_for_swap is not None
                and self._prev_actual_for_swap is not None
                and expected_char == self._prev_actual_for_swap
                and actual_char == self._prev_expected_for_swap
            ):
                is_swap = True
                self.swap_count += 1

        # Update prev tracking for motor overflow detection
        self._prev_actual_char = actual_char
        self._prev_timestamp_ms = timestamp_ms

        # Update swap tracking (only for keystrokes that advance cursor)
        self._prev_expected_for_swap = expected_char
        self._prev_actual_for_swap = actual_char
        self._prev_was_cognitive_error = base_error_type == ErrorType.COGNITIVE_ERROR

        return ClassificationResult(
            error_type=base_error_type,
            is_same_key=is_same_key,
            same_key_interval_ms=same_key_interval_ms,
            is_swap=is_swap,
        )

    def _update_burst(
        self,
        actual_char: str,
        timestamp_ms: int,
        interval_ms: int | None,
        is_error: bool,
    ) -> bool:
        """Update burst tracking state and determine if this keystroke should
        be reclassified as BURST_REPEAT.

        This is called for keystrokes that are NOT motor overflow (i.e., they
        advance the cursor). Motor overflow presses call _extend_burst() instead.

        Returns True if this keystroke should be reclassified as BURST_REPEAT.
        """
        if actual_char == self._burst_char:
            # Same char continues — check timing
            if interval_ms is not None and interval_ms > self.burst_max_interval_ms:
                # Too slow — reset burst
                self._reset_burst(actual_char, is_error)
                return False
            # Extend the burst
            self._burst_count += 1
            if is_error:
                self._burst_error_count += 1
        else:
            # Different char — reset burst
            self._reset_burst(actual_char, is_error)
            return False

        # Check if burst criteria are met: >=3 consecutive same key, >=50% errors.
        # Once confirmed, all errors from this point on are BURST_REPEAT.
        # Errors before count 3 are already classified and naturally kept.
        if self._burst_count >= 3 and self._is_burst_active() and is_error:
            return True
        return False

    def _extend_burst(
        self, actual_char: str, timestamp_ms: int, is_error: bool
    ) -> None:
        """Extend the burst sequence for motor overflow presses.

        Motor overflow presses count toward the burst sequence but are already
        classified as MOTOR_OVERFLOW, so they don't need reclassification.
        """
        if actual_char == self._burst_char:
            self._burst_count += 1
            if is_error:
                self._burst_error_count += 1
        else:
            self._reset_burst(actual_char, is_error)

    def _reset_burst(self, new_char: str, is_error: bool) -> None:
        """Reset burst tracking to start a new potential burst sequence."""
        self._burst_char = new_char
        self._burst_count = 1
        self._burst_error_count = 1 if is_error else 0

    def _is_burst_active(self) -> bool:
        """Check if the current sequence qualifies as a burst.

        A burst requires >=50% of presses in the sequence to be errors.
        """
        if self._burst_count == 0:
            return False
        return self._burst_error_count / self._burst_count >= 0.5

    def reset(self) -> None:
        """Reset state for a new run. Preserves same_key_intervals for analysis."""
        self._prev_actual_char = None
        self._prev_timestamp_ms = None
        self._burst_char = None
        self._burst_count = 0
        self._burst_error_count = 0
        self._prev_expected_for_swap = None
        self._prev_actual_for_swap = None
        self._prev_was_cognitive_error = False
        self.swap_count = 0
