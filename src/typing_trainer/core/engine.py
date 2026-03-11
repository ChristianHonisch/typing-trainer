"""Core typing engine: processes keystrokes and tracks run state.

The engine receives keystroke events one at a time and maintains:
- Current position in the target text
- First-input-per-position tracking (accuracy is based on first attempt)
- Running accuracy (excluding motor overflow)
- Fail threshold checking
- Per-keystroke log with timing and bigram data
- Per-letter statistics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from typing_trainer.config import Config
from typing_trainer.core.error_classifier import ErrorClassifier
from typing_trainer.models.letter_state import ErrorType, PracticeType, RunMode
from typing_trainer.models.run_result import (
    KeystrokeEvent,
    PerLetterResult,
    RunResult,
)


@dataclass
class EngineState:
    """Internal state of the typing engine during a run."""

    target_text: str = ""
    mode: RunMode = RunMode.RELEARNING
    practice_type: PracticeType = PracticeType.RANDOM_STRINGS
    fail_threshold: float = 0.90

    # Position tracking
    cursor_position: int = 0
    """Next expected position in the target text."""

    # First-input tracking: maps position -> (actual_char, error_type)
    # Only the first input at each position counts for accuracy.
    first_inputs: dict[int, tuple[str, ErrorType]] = field(default_factory=dict)

    # Counters (based on first inputs only, excluding motor overflow and burst repeat)
    total_scored_keystrokes: int = 0
    cognitive_errors: int = 0
    motor_overflow_count: int = 0
    burst_repeat_count: int = 0
    backspace_count: int = 0
    swap_count: int = 0

    # Keystroke log (all keystrokes, including backspace and corrections)
    keystroke_log: list[KeystrokeEvent] = field(default_factory=list)

    # Per-letter stats
    per_letter: dict[str, PerLetterResult] = field(default_factory=dict)

    # Timing
    start_time: datetime | None = None
    end_time: datetime | None = None
    prev_timestamp_ms: int | None = None
    prev_char: str | None = None

    # Outcome
    is_finished: bool = False
    is_failed: bool = False

    @property
    def accuracy(self) -> float:
        """Current running accuracy (cognitive errors only)."""
        if self.total_scored_keystrokes == 0:
            return 1.0
        correct = self.total_scored_keystrokes - self.cognitive_errors
        return correct / self.total_scored_keystrokes

    @property
    def remaining(self) -> int:
        """Characters remaining in the target text."""
        return len(self.target_text) - self.cursor_position

    @property
    def is_complete(self) -> bool:
        """Whether the user has typed all characters."""
        return self.cursor_position >= len(self.target_text)


class TypingEngine:
    """Processes keystrokes for a single typing run.

    Usage:
        engine = TypingEngine(config)
        engine.start_run(target_text, mode, practice_type, fail_threshold)
        while not engine.state.is_finished:
            result = engine.process_keystroke(char, timestamp_ms)
        run_result = engine.finish_run()
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.classifier = ErrorClassifier(
            motor_overflow_window_ms=config.motor_overflow_window_ms,
            burst_max_interval_ms=config.burst_max_interval_ms,
        )
        self.state = EngineState()

    def start_run(
        self,
        target_text: str,
        mode: RunMode = RunMode.RELEARNING,
        practice_type: PracticeType = PracticeType.RANDOM_STRINGS,
        fail_threshold: float | None = None,
    ) -> None:
        """Initialize a new typing run.

        Args:
            target_text: The text the user must type.
            mode: Relearning or speed mode.
            practice_type: Type of practice content.
            fail_threshold: Override for the fail threshold. If None,
                uses mode default from config.
        """
        if fail_threshold is None:
            if mode == RunMode.SPEED:
                fail_threshold = self.config.fail_threshold_speed
            elif mode == RunMode.TRANSITION:
                fail_threshold = self.config.fail_threshold_transition
            else:
                fail_threshold = self.config.fail_threshold_relearning

        self.classifier.reset()
        self.state = EngineState(
            target_text=target_text,
            mode=mode,
            practice_type=practice_type,
            fail_threshold=fail_threshold,
            start_time=None,
        )

        # Handle empty text edge case
        if self.state.is_complete:
            self.state.is_finished = True

    def process_keystroke(
        self, actual_char: str, timestamp_ms: int
    ) -> KeystrokeEvent | None:
        """Process a single keystroke.

        Args:
            actual_char: The character the user typed. Use '\\b' for backspace.
            timestamp_ms: Timestamp in milliseconds.

        Returns:
            KeystrokeEvent describing what happened, or None if the run is
            already finished.
        """
        if self.state.is_finished:
            return None

        # Start timing on first keystroke
        if self.state.start_time is None:
            self.state.start_time = datetime.now()

        # Handle backspace
        if actual_char == "\b":
            return self._handle_backspace(timestamp_ms)

        # Get expected character
        if self.state.cursor_position >= len(self.state.target_text):
            return None
        expected_char = self.state.target_text[self.state.cursor_position]

        # Compute reaction time
        reaction_time_ms: int | None = None
        if self.state.prev_timestamp_ms is not None:
            reaction_time_ms = timestamp_ms - self.state.prev_timestamp_ms

        # Classify the keystroke
        classification = self.classifier.classify(
            expected_char=expected_char,
            actual_char=actual_char,
            timestamp_ms=timestamp_ms,
            position=self.state.cursor_position,
        )

        # Handle motor overflow: logged but doesn't advance position
        if classification.error_type == ErrorType.MOTOR_OVERFLOW:
            self.state.motor_overflow_count += 1
            event = KeystrokeEvent(
                position=self.state.cursor_position,
                timestamp_ms=timestamp_ms,
                expected_char=expected_char,
                actual_char=actual_char,
                error_type=ErrorType.MOTOR_OVERFLOW,
                reaction_time_ms=reaction_time_ms,
                prev_char=self.state.prev_char,
            )
            self.state.keystroke_log.append(event)
            # Don't advance position, don't update prev tracking
            return event

        # Handle burst repeat: same as motor overflow (excluded from accuracy)
        if classification.error_type == ErrorType.BURST_REPEAT:
            self.state.burst_repeat_count += 1
            event = KeystrokeEvent(
                position=self.state.cursor_position,
                timestamp_ms=timestamp_ms,
                expected_char=expected_char,
                actual_char=actual_char,
                error_type=ErrorType.BURST_REPEAT,
                reaction_time_ms=reaction_time_ms,
                prev_char=self.state.prev_char,
            )
            self.state.keystroke_log.append(event)
            # Don't advance position, don't update prev tracking
            return event

        # Track swap errors (diagnostic only, still counted as cognitive errors)
        if classification.is_swap:
            self.state.swap_count += 1

        # Track first input at this position
        pos = self.state.cursor_position
        is_first_input = pos not in self.state.first_inputs
        is_warmup = pos < self.config.warmup_keystrokes

        if is_first_input:
            self.state.first_inputs[pos] = (actual_char, classification.error_type)

            if not is_warmup:
                # Warmup keystrokes are logged but excluded from accuracy,
                # per-letter stats, and the fail threshold.  Position analysis
                # shows elevated error rates at run start (~3.5%) compared to
                # the productive zone (~1.7%).
                self.state.total_scored_keystrokes += 1

                if classification.error_type == ErrorType.COGNITIVE_ERROR:
                    self.state.cognitive_errors += 1

                # Update per-letter stats (based on first input only)
                self._update_per_letter(
                    expected_char, classification.error_type, reaction_time_ms
                )

        # Create keystroke event
        event = KeystrokeEvent(
            position=pos,
            timestamp_ms=timestamp_ms,
            expected_char=expected_char,
            actual_char=actual_char,
            error_type=classification.error_type,
            reaction_time_ms=reaction_time_ms,
            prev_char=self.state.prev_char,
        )
        self.state.keystroke_log.append(event)

        # Advance cursor
        self.state.cursor_position += 1
        self.state.prev_timestamp_ms = timestamp_ms
        self.state.prev_char = actual_char

        # Check fail threshold (only after accumulating enough errors)
        if (
            is_first_input
            and self.state.cognitive_errors >= self.config.fail_threshold_min_errors
            and self.state.accuracy < self.state.fail_threshold
        ):
            self.state.is_failed = True
            self.state.is_finished = True

        # Check completion
        if self.state.is_complete:
            self.state.is_finished = True

        return event

    def _handle_backspace(self, timestamp_ms: int) -> KeystrokeEvent | None:
        """Handle a backspace keypress.

        In relearning mode: backspace is disabled (ignored).
        In speed mode: moves cursor back one position.
        """
        self.state.backspace_count += 1

        if self.state.mode == RunMode.RELEARNING:
            # Backspace disabled in relearning — log but don't move cursor
            # (Backspace is enabled in speed and transition modes.)
            event = KeystrokeEvent(
                position=self.state.cursor_position,
                timestamp_ms=timestamp_ms,
                expected_char=(
                    self.state.target_text[self.state.cursor_position]
                    if self.state.cursor_position < len(self.state.target_text)
                    else ""
                ),
                actual_char="\b",
                error_type=ErrorType.CORRECT,  # Not an error, just logged
                is_backspace=True,
            )
            self.state.keystroke_log.append(event)
            return event

        # Speed mode: move cursor back
        if self.state.cursor_position > 0:
            self.state.cursor_position -= 1

        event = KeystrokeEvent(
            position=self.state.cursor_position,
            timestamp_ms=timestamp_ms,
            expected_char=(
                self.state.target_text[self.state.cursor_position]
                if self.state.cursor_position < len(self.state.target_text)
                else ""
            ),
            actual_char="\b",
            error_type=ErrorType.CORRECT,
            is_backspace=True,
        )
        self.state.keystroke_log.append(event)
        return event

    def _update_per_letter(
        self,
        expected_char: str,
        error_type: ErrorType,
        reaction_time_ms: int | None,
    ) -> None:
        """Update per-letter statistics for a first-input keystroke."""
        char = expected_char.lower()
        if char not in self.state.per_letter:
            self.state.per_letter[char] = PerLetterResult(letter=char)

        stats = self.state.per_letter[char]
        stats.total_attempts += 1

        if error_type == ErrorType.COGNITIVE_ERROR:
            stats.cognitive_errors += 1

        if reaction_time_ms is not None:
            stats.reaction_times.append(reaction_time_ms)

    def finish_run(self) -> RunResult:
        """Finalize the run and return the complete result.

        Should be called after the run is finished (completed or failed).
        """
        self.state.end_time = datetime.now()
        self.state.is_finished = True

        # Compute per-letter mean reaction times
        for stats in self.state.per_letter.values():
            if stats.reaction_times:
                stats.mean_reaction_time_ms = sum(stats.reaction_times) / len(
                    stats.reaction_times
                )

        result = RunResult(
            start_time=self.state.start_time,
            end_time=self.state.end_time,
            mode=self.state.mode,
            practice_type=self.state.practice_type,
            target_text=self.state.target_text,
            target_length=len(self.state.target_text),
            total_keystrokes=self.state.total_scored_keystrokes,
            cognitive_errors=self.state.cognitive_errors,
            motor_overflow_errors=self.state.motor_overflow_count,
            burst_repeat_count=self.state.burst_repeat_count,
            backspace_count=self.state.backspace_count,
            swap_count=self.state.swap_count,
            completed=self.state.is_complete,
            failed=self.state.is_failed,
            fail_threshold_used=self.state.fail_threshold,
            accuracy=self.state.accuracy,
            per_letter=dict(self.state.per_letter),
            keystrokes=list(self.state.keystroke_log),
        )
        result.wpm = result.compute_wpm()
        return result
