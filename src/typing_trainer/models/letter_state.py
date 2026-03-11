"""Letter state tracking for the active letter set."""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from datetime import datetime


class LetterState(enum.Enum):
    """State of a letter in the active set.

    Lifecycle: introducing -> consolidating -> stable -> mastered
                                                ↑          ↓
                                                ← degraded ←
    """

    INTRODUCING = "introducing"
    """Added in the current session or the previous one."""

    CONSOLIDATING = "consolidating"
    """Present for >= 2 sessions, not yet stable."""

    STABLE = "stable"
    """Accuracy >= 95% across last 3 sessions."""

    MASTERED = "mastered"
    """Motor pattern deeply encoded through sustained distributed practice.

    Entered when mastery_score >= mastery_threshold (default 0.8).
    Gets reduced base training weight (0.5) to free share for others.
    Reverts to DEGRADED on same trigger as STABLE (rolling error > 5%).
    mastery_score is NOT reset on degradation — it decays naturally."""

    DEGRADED = "degraded"
    """Was stable/mastered, now below threshold."""


class ErrorType(enum.Enum):
    """Classification of a single keystroke."""

    CORRECT = "correct"
    COGNITIVE_ERROR = "cognitive_error"
    MOTOR_OVERFLOW = "motor_overflow"
    BURST_REPEAT = "burst_repeat"
    """Same key held/stuck: 3+ consecutive same actual_char within burst interval,
    with >50% being errors. Excluded from accuracy like motor overflow."""


class RunMode(enum.Enum):
    """Mode of a typing run."""

    RELEARNING = "relearning"
    SPEED = "speed"
    TRANSITION = "transition"
    """Bigram transition training — targets specific letter transitions
    that are error-prone or slow.  Uses real words containing target
    bigrams interleaved with normal words (contextual interference)."""


class PracticeType(enum.Enum):
    """Type of practice content."""

    RANDOM_STRINGS = "random_strings"
    RANDOM_WORDS = "random_words"
    SENTENCES = "sentences"
    BIGRAM_WORDS = "bigram_words"
    """Real words selected to contain target bigram transitions,
    interleaved with normal words for contextual interference."""


@dataclass
class LetterStats:
    """Per-letter statistics tracked across sessions.

    This is the in-memory representation. Storage maps to/from this.
    """

    letter: str
    state: LetterState = LetterState.INTRODUCING
    stability_score: float = 0.3
    """Spaced-repetition stability.  New letters start at 0.3 (below the
    0.5 review threshold) so they are immediately flagged for practice.
    After one good session (+0.2 -> 0.5) the letter crosses the review
    threshold; after two good sessions (0.7) it is solidly above it.
    """
    last_practiced: datetime | None = None
    error_rate_latest: float = 0.0
    sessions_in_current_state: int = 0
    sessions_since_introduced: int = 0

    # Per-session accuracy history (most recent first, kept for state transitions)
    accuracy_history: list[float] = field(default_factory=list)

    # Total keystrokes (all runs) at the time this letter was introduced.
    # Used to compute keystrokes-since-introduction for advancement.
    keystrokes_at_introduction: int = 0

    # Rolling error rate from the last N keystrokes (same window as advancement).
    # Populated at runtime from DB query; not persisted directly.
    rolling_error_rate: float = 0.0

    # Longer-window rolling error rate (2000 keystrokes) for display in the
    # letter overview table.  Populated at runtime; not persisted.
    rolling_error_rate_long: float = 0.0

    # Number of keystrokes in the rolling accuracy window for this letter.
    # Populated at runtime from DB query; not persisted.
    rolling_keystroke_count: int = 0

    # Mastery: long-term motor pattern encoding (0.0–1.0).
    # Builds slowly via qualifying keystrokes, decays over time.
    mastery_score: float = 0.0
    """Long-term mastery score. Builds via qualifying keystrokes when
    STABLE/MASTERED with rolling accuracy >= advancement_accuracy.
    STABLE -> MASTERED at mastery_threshold (default 0.8)."""

    mastery_qualifying_keystrokes: int = 0
    """Lifetime total of qualifying keystrokes for this letter.
    Informational — NOT used to compute mastery_score (the score is
    tracked independently, pushed up by practice, pulled down by decay).
    Freezes (does not reset) on degradation."""

    def _state_bonus(
        self,
        introducing: float = 3.0,
        degraded: float = 2.0,
        consolidating: float = 1.0,
        recently_stable: float = 1.0,
        recently_stable_sessions: int = 10,
    ) -> float:
        """Training weight bonus based on current letter state.

        New/struggling letters get more practice repetitions.
        Recently-stable letters get a decaying bonus to solidify
        the motor pattern before the letter is fully settled.
        MASTERED letters get no state bonus (their reduced base weight
        in training_weight() already reflects their status).
        """
        match self.state:
            case LetterState.INTRODUCING:
                return introducing
            case LetterState.DEGRADED:
                return degraded
            case LetterState.CONSOLIDATING:
                return consolidating
            case LetterState.MASTERED:
                return 0.0
            case LetterState.STABLE:
                if (
                    recently_stable_sessions > 0
                    and self.sessions_in_current_state < recently_stable_sessions
                ):
                    # Linear decay: full bonus at 0 sessions, 0 at threshold
                    return recently_stable * (
                        1.0
                        - self.sessions_in_current_state
                        / recently_stable_sessions
                    )
                return 0.0

    def _accuracy_gap_bonus(self, error_threshold: float = 0.05) -> float:
        """Training weight bonus based on how far below target accuracy.

        Letters with higher error rates get proportionally more practice.
        Formula: max(0, rolling_error_rate - error_threshold) * 50

        Args:
            error_threshold: Error rate above which the bonus kicks in.
                Derived from ``1 - advancement_accuracy`` by callers that
                have access to Config; defaults to 0.05 (95% accuracy).

        Examples (at default threshold 0.05):
                  90% accuracy (0.10 error) -> 2.5 bonus
                  85% accuracy (0.15 error) -> 5.0 bonus
                  80% accuracy (0.20 error) -> 7.5 bonus
        """
        return max(0.0, (self.rolling_error_rate - error_threshold) * 50)

    def _volume_deficit_bonus(
        self,
        window: int = 200,
        weight: float = 1.0,
    ) -> float:
        """Training weight bonus for letters that lack keystroke volume.

        Letters whose rolling keystroke count has not yet filled the
        advancement accuracy window need extra practice so they can
        produce reliable accuracy data (and stop blocking the next
        letter introduction).

        The bonus is *flat* at ``weight`` while the count is well below
        the window, then fades out with a cosine curve centred on the
        window size:

        - Full bonus until ``window × 0.85`` (170 for window=200)
        - 0.5 × weight at exactly ``window`` (200)
        - 0 at ``window × 1.15`` (230)

        This avoids a discouraging long tail where the bonus creeps
        towards zero while the letter still genuinely needs volume.
        """
        fade_half = max(1, round(window * 0.15))
        fade_start = window - fade_half
        fade_end = window + fade_half
        count = self.rolling_keystroke_count
        if count <= fade_start:
            return weight
        if count >= fade_end:
            return 0.0
        # Cosine fade: weight at fade_start, 0 at fade_end
        t = (count - fade_start) / (fade_end - fade_start)
        return weight * 0.5 * (1.0 + math.cos(math.pi * t))

    def training_weight(
        self,
        error_threshold: float = 0.05,
        introducing: float = 3.0,
        degraded: float = 2.0,
        consolidating: float = 1.0,
        recently_stable: float = 1.0,
        recently_stable_sessions: int = 10,
        volume_window: int = 200,
        volume_deficit: float = 1.0,
        mastered: float = 0.5,
    ) -> float:
        """Need-based training weight for text generation.

        Non-mastered letters get base weight 1.0; MASTERED letters get
        ``mastered`` (default 0.5) to free share for non-mastered letters.
        Bonuses are added for training need: state (new/degraded letters
        need more reps), accuracy gap (struggling letters), recently-stable
        consolidation, and volume deficit.

        Args:
            error_threshold: Error rate above which the accuracy-gap bonus
                kicks in.  Pass ``1 - config.advancement_accuracy`` for
                config-aware weighting.
            introducing: State bonus for INTRODUCING letters.
            degraded: State bonus for DEGRADED letters.
            consolidating: State bonus for CONSOLIDATING letters.
            recently_stable: Max consolidation bonus for recently-stable
                letters.  Decays linearly over ``recently_stable_sessions``.
            recently_stable_sessions: Sessions in STABLE state before the
                consolidation bonus fully decays.
            volume_window: Rolling accuracy window size (keystrokes).
                Letters with fewer keystrokes get a volume deficit bonus.
            volume_deficit: Maximum volume deficit bonus.
            mastered: Base weight for MASTERED letters (replaces 1.0).
        """
        base = mastered if self.state == LetterState.MASTERED else 1.0
        return (
            base
            + self._state_bonus(
                introducing,
                degraded,
                consolidating,
                recently_stable,
                recently_stable_sessions,
            )
            + self._accuracy_gap_bonus(error_threshold)
            + self._volume_deficit_bonus(volume_window, volume_deficit)
        )
