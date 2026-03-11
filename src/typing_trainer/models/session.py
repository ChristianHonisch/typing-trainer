"""Session tracking and aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from typing_trainer.models.run_result import RunResult


@dataclass
class Session:
    """A session is one sitting at the keyboard.

    Ends when the user closes the app or is inactive for > session_timeout.
    Contains one or more runs.
    """

    session_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    language: str = "de"
    layout: str = "qwertz"

    runs: list[RunResult] = field(default_factory=list)
    last_activity: datetime | None = None

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """Check if the session has timed out due to inactivity."""
        if self.last_activity is None:
            return False
        elapsed = datetime.now() - self.last_activity
        return elapsed > timedelta(minutes=timeout_minutes)

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now()

    def add_run(self, run: RunResult) -> None:
        """Add a completed run to this session."""
        self.runs.append(run)
        self.touch()

    @property
    def total_cognitive_keystrokes(self) -> int:
        """Total cognitive keystrokes across all runs in this session.

        This is the count used for the 300-keystroke advancement criterion.
        Motor overflow keystrokes are excluded.
        """
        return sum(r.total_keystrokes for r in self.runs)

    @property
    def aggregate_accuracy(self) -> float:
        """Weighted accuracy across all runs in this session."""
        total_keystrokes = sum(r.total_keystrokes for r in self.runs)
        if total_keystrokes == 0:
            return 1.0
        total_errors = sum(r.cognitive_errors for r in self.runs)
        return (total_keystrokes - total_errors) / total_keystrokes

    @property
    def run_count(self) -> int:
        return len(self.runs)

    def per_letter_error_rate(self) -> dict[str, float]:
        """Aggregate per-letter error rate across all runs in this session."""
        letter_attempts: dict[str, int] = {}
        letter_errors: dict[str, int] = {}

        for run in self.runs:
            for letter, stats in run.per_letter.items():
                letter_attempts[letter] = (
                    letter_attempts.get(letter, 0) + stats.total_attempts
                )
                letter_errors[letter] = (
                    letter_errors.get(letter, 0) + stats.cognitive_errors
                )

        result: dict[str, float] = {}
        for letter in letter_attempts:
            if letter_attempts[letter] > 0:
                result[letter] = letter_errors[letter] / letter_attempts[letter]
            else:
                result[letter] = 0.0
        return result

    def per_letter_keystrokes(self, letter: str) -> int:
        """Total scored keystrokes for a specific letter across all runs.

        Counts first-input keystrokes (correct + cognitive_error) as tracked
        by PerLetterResult.total_attempts.  Does not include motor overflow,
        burst repeat, or backspace keystrokes.
        """
        total = 0
        for run in self.runs:
            if letter in run.per_letter:
                total += run.per_letter[letter].total_attempts
        return total
