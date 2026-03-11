"""Data structures for run results and per-keystroke logs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from typing_trainer.models.letter_state import ErrorType, PracticeType, RunMode


@dataclass
class KeystrokeEvent:
    """A single keystroke as captured during a run."""

    position: int
    """Position in the target text (0-indexed)."""

    timestamp_ms: int
    """Absolute timestamp in milliseconds (from system clock or QKeyEvent)."""

    expected_char: str
    """The character the user was supposed to type."""

    actual_char: str
    """The character the user actually typed."""

    error_type: ErrorType = ErrorType.CORRECT
    """Classification of this keystroke."""

    reaction_time_ms: int | None = None
    """Time since previous keystroke (ms). None for the first keystroke."""

    prev_char: str | None = None
    """The previous character (for bigram analysis). None for the first keystroke."""

    is_backspace: bool = False
    """Whether this was a backspace keypress."""


@dataclass
class PerLetterResult:
    """Per-letter statistics from a single run."""

    letter: str
    total_attempts: int = 0
    cognitive_errors: int = 0
    mean_reaction_time_ms: float | None = None
    reaction_times: list[int] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        """Cognitive error rate for this letter."""
        if self.total_attempts == 0:
            return 0.0
        return self.cognitive_errors / self.total_attempts


@dataclass
class RunResult:
    """Complete result of a single typing run."""

    # Identification
    run_id: int | None = None
    session_id: int | None = None

    # Timing
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Configuration
    mode: RunMode = RunMode.RELEARNING
    practice_type: PracticeType = PracticeType.RANDOM_STRINGS
    target_text: str = ""
    target_length: int = 0

    # Aggregate stats
    total_keystrokes: int = 0
    """Total keystrokes processed (excluding motor overflow, burst repeat,
    and backspace)."""

    cognitive_errors: int = 0
    motor_overflow_errors: int = 0
    burst_repeat_count: int = 0
    """Key-hold/stuck-key repeats excluded from accuracy."""
    backspace_count: int = 0
    swap_count: int = 0
    """Adjacent letter transpositions (diagnostic only, still counted as errors)."""

    # Outcome
    completed: bool = False
    """True if the user reached the end of the target text."""

    failed: bool = False
    """True if the run was aborted due to accuracy dropping below threshold."""

    fail_threshold_used: float = 0.0
    """The fail threshold that was active for this run."""

    # Derived
    accuracy: float = 1.0
    """accuracy = (correct - cognitive_errors) / correct, excluding motor overflow."""

    wpm: float = 0.0
    """Net words per minute (1 word = 5 characters, errors subtracted)."""

    # Per-letter breakdown
    per_letter: dict[str, PerLetterResult] = field(default_factory=dict)

    # Raw keystroke log
    keystrokes: list[KeystrokeEvent] = field(default_factory=list)

    def compute_accuracy(self) -> float:
        """Recompute accuracy from keystroke data."""
        if self.total_keystrokes == 0:
            return 1.0
        correct = self.total_keystrokes - self.cognitive_errors
        return correct / self.total_keystrokes

    def compute_wpm(self) -> float:
        """Compute net words per minute from timing data.

        Net WPM subtracts cognitive errors from the total keystrokes,
        so only correctly typed characters contribute to the speed
        metric.  One "word" = 5 characters (standard convention).
        """
        if self.start_time is None or self.end_time is None:
            return 0.0
        duration_seconds = (self.end_time - self.start_time).total_seconds()
        if duration_seconds <= 0:
            return 0.0
        correct_chars = self.total_keystrokes - self.cognitive_errors
        chars_per_second = correct_chars / duration_seconds
        return (chars_per_second / 5.0) * 60.0
