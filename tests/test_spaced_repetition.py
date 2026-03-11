"""Tests for spaced repetition / stability decay."""

import math
from datetime import datetime, timedelta

from typing_trainer.config import Config
from typing_trainer.core.spaced_repetition import SpacedRepetition
from typing_trainer.models.letter_state import LetterState, LetterStats


class TestStabilityDecay:
    def test_no_decay_if_just_practiced(self):
        config = Config()
        sr = SpacedRepetition(config)
        now = datetime(2026, 1, 1, 12, 0, 0)
        stats = LetterStats(
            letter="e",
            state=LetterState.CONSOLIDATING,
            stability_score=1.0,
            last_practiced=now,
        )
        stability = sr.compute_current_stability(stats, now=now)
        assert stability == 1.0

    def test_decay_after_half_life_consolidating(self):
        config = Config(half_life_consolidating_hours=24.0)
        sr = SpacedRepetition(config)
        practiced = datetime(2026, 1, 1, 12, 0, 0)
        now = practiced + timedelta(hours=24)
        stats = LetterStats(
            letter="e",
            state=LetterState.CONSOLIDATING,
            stability_score=1.0,
            last_practiced=practiced,
        )
        stability = sr.compute_current_stability(stats, now=now)
        assert abs(stability - 0.5) < 0.01  # Should be ~0.5 after one half-life

    def test_decay_after_half_life_stable(self):
        config = Config(half_life_stable_hours=72.0)
        sr = SpacedRepetition(config)
        practiced = datetime(2026, 1, 1, 12, 0, 0)
        now = practiced + timedelta(hours=72)
        stats = LetterStats(
            letter="e",
            state=LetterState.STABLE,
            stability_score=1.0,
            last_practiced=practiced,
        )
        stability = sr.compute_current_stability(stats, now=now)
        assert abs(stability - 0.5) < 0.01

    def test_decay_proportional_to_initial(self):
        config = Config(half_life_consolidating_hours=24.0)
        sr = SpacedRepetition(config)
        practiced = datetime(2026, 1, 1, 12, 0, 0)
        now = practiced + timedelta(hours=24)
        stats = LetterStats(
            letter="e",
            state=LetterState.CONSOLIDATING,
            stability_score=0.8,
            last_practiced=practiced,
        )
        stability = sr.compute_current_stability(stats, now=now)
        assert abs(stability - 0.4) < 0.01  # 0.8 * 0.5

    def test_no_last_practiced_returns_zero(self):
        config = Config()
        sr = SpacedRepetition(config)
        stats = LetterStats(letter="e", last_practiced=None)
        stability = sr.compute_current_stability(stats)
        assert stability == 0.0


class TestReviewStatus:
    def test_due_letters_identified(self):
        config = Config(
            half_life_consolidating_hours=24.0,
            stability_revert_threshold=0.5,
        )
        sr = SpacedRepetition(config)
        now = datetime(2026, 1, 3, 12, 0, 0)

        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.CONSOLIDATING,
                stability_score=1.0,
                last_practiced=datetime(2026, 1, 1, 12, 0, 0),  # 48h ago
            ),
            "n": LetterStats(
                letter="n",
                state=LetterState.CONSOLIDATING,
                stability_score=1.0,
                last_practiced=datetime(2026, 1, 3, 11, 0, 0),  # 1h ago
            ),
        }

        due = sr.get_due_letters(active, now=now)
        assert "e" in due  # 48h with 24h half-life -> stability ~0.25
        assert "n" not in due  # 1h -> stability ~0.97

    def test_review_status_sorted_by_urgency(self):
        config = Config(half_life_consolidating_hours=24.0)
        sr = SpacedRepetition(config)
        now = datetime(2026, 1, 3, 12, 0, 0)

        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.CONSOLIDATING,
                stability_score=1.0,
                last_practiced=datetime(2026, 1, 1, 12, 0, 0),  # oldest
            ),
            "n": LetterStats(
                letter="n",
                state=LetterState.CONSOLIDATING,
                stability_score=1.0,
                last_practiced=datetime(2026, 1, 2, 12, 0, 0),  # middle
            ),
            "i": LetterStats(
                letter="i",
                state=LetterState.CONSOLIDATING,
                stability_score=1.0,
                last_practiced=datetime(2026, 1, 3, 11, 0, 0),  # newest
            ),
        }

        statuses = sr.get_review_status(active, now=now)
        assert statuses[0].letter == "e"  # lowest stability first
        assert statuses[-1].letter == "i"  # highest stability last


class TestTimeDecay:
    def test_apply_time_decay_reverts_letters(self):
        config = Config(
            half_life_consolidating_hours=24.0,
            stability_revert_threshold=0.5,
        )
        sr = SpacedRepetition(config)
        now = datetime(2026, 1, 3, 12, 0, 0)

        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=1.0,
                last_practiced=datetime(2026, 1, 1, 12, 0, 0),  # 48h ago
            ),
        }
        # Stable with 24h half-life (uses consolidating half-life after revert,
        # but the check uses the current state which is STABLE with 72h half-life)
        # Wait — stable has 72h half-life. 48h -> stability = e^(-ln2 * 48/72) ≈ 0.63
        # So this won't revert with 72h half-life. Let's use a longer gap.

        active["e"].last_practiced = datetime(2025, 12, 25, 12, 0, 0)  # 9 days ago
        # 216h with 72h half-life -> e^(-ln2 * 216/72) = e^(-ln2 * 3) = 0.125
        active, reverted = sr.apply_time_decay(active, now=now)
        assert "e" in reverted
        assert active["e"].state == LetterState.CONSOLIDATING
