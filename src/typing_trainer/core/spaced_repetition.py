"""Spaced repetition system for letter consolidation.

Each letter has a stability score that decays over time (Ebbinghaus-inspired).
Letters due for review are surfaced at session start.

Decay function (half-life model):
    stability(t) = stability_0 * (1/2)^(t / half_life)
    half_life = 24h for 'consolidating' letters
    half_life = 72h for 'stable' letters

Equivalent to: stability_0 * e^(-ln(2) * t / half_life)

If stability drops below 0.5, the letter reverts to 'consolidating'.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from typing_trainer.config import Config
from typing_trainer.models.letter_state import LetterState, LetterStats


@dataclass
class ReviewStatus:
    """Review status for a single letter."""

    letter: str
    current_stability: float
    is_due: bool
    hours_since_practice: float
    state: LetterState


class SpacedRepetition:
    """Manages stability decay and review scheduling."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def get_half_life_hours(self, state: LetterState) -> float:
        """Get the decay half-life for a letter state."""
        match state:
            case LetterState.INTRODUCING:
                return self.config.half_life_consolidating_hours
            case LetterState.CONSOLIDATING:
                return self.config.half_life_consolidating_hours
            case LetterState.STABLE:
                return self.config.half_life_stable_hours
            case LetterState.DEGRADED:
                return self.config.half_life_consolidating_hours

    def compute_current_stability(
        self,
        stats: LetterStats,
        now: datetime | None = None,
    ) -> float:
        """Compute the current stability score accounting for time decay.

        stability(t) = stability_0 * e^(-t / half_life)
        where t is hours since last practice.
        """
        if stats.last_practiced is None:
            return 0.0

        if now is None:
            now = datetime.now()

        hours_elapsed = (now - stats.last_practiced).total_seconds() / 3600.0
        if hours_elapsed <= 0:
            return stats.stability_score

        half_life = self.get_half_life_hours(stats.state)
        # Convert half-life to decay constant: lambda = ln(2) / half_life
        decay_constant = math.log(2) / half_life
        decayed = stats.stability_score * math.exp(-decay_constant * hours_elapsed)
        return max(0.0, decayed)

    def get_review_status(
        self,
        active_letters: dict[str, LetterStats],
        now: datetime | None = None,
    ) -> list[ReviewStatus]:
        """Get review status for all active letters.

        Returns list sorted by urgency (lowest stability first).
        """
        if now is None:
            now = datetime.now()

        statuses: list[ReviewStatus] = []
        for stats in active_letters.values():
            current_stability = self.compute_current_stability(stats, now)
            hours_since = 0.0
            if stats.last_practiced is not None:
                hours_since = (now - stats.last_practiced).total_seconds() / 3600.0

            statuses.append(
                ReviewStatus(
                    letter=stats.letter,
                    current_stability=current_stability,
                    is_due=current_stability < self.config.stability_revert_threshold,
                    hours_since_practice=hours_since,
                    state=stats.state,
                )
            )

        # Sort by stability ascending (most urgent first)
        statuses.sort(key=lambda s: s.current_stability)
        return statuses

    def get_due_letters(
        self,
        active_letters: dict[str, LetterStats],
        now: datetime | None = None,
    ) -> list[str]:
        """Get letters that are due for review (stability < threshold)."""
        statuses = self.get_review_status(active_letters, now)
        return [s.letter for s in statuses if s.is_due]

    def apply_time_decay(
        self,
        active_letters: dict[str, LetterStats],
        now: datetime | None = None,
    ) -> tuple[dict[str, LetterStats], list[str]]:
        """Apply time-based decay to all letters and revert any that dropped.

        Returns (updated_letters, list_of_reverted_letters).
        """
        if now is None:
            now = datetime.now()

        reverted: list[str] = []
        for stats in active_letters.values():
            current = self.compute_current_stability(stats, now)
            stats.stability_score = current

            if (
                current < self.config.stability_revert_threshold
                and stats.state == LetterState.STABLE
            ):
                stats.state = LetterState.CONSOLIDATING
                stats.sessions_in_current_state = 0
                reverted.append(stats.letter)

        return active_letters, reverted
