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


class DisplayMode(enum.Enum):
    """UI detail level.

    Controls which panels, charts, and statistics are visible.
    """

    BASIC = "basic"
    """Training panel only, minimal run summary, no sidebar or analytics."""

    NERD = "nerd"
    """Sidebar, per-letter run summary, core analytics charts."""

    EXTREME_NERD = "extreme_nerd"
    """Everything visible: all analytics, intra-run speed chart."""


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
    FIX_KEYS = "fix_keys"
    """Random strings focused on error-prone letters."""


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

    # Per-session accuracy history (most recent first).
    # Legacy: previously used for CONSOLIDATING->STABLE transition (3 consecutive
    # sessions >= 95%).  Now replaced by keystroke-based rolling accuracy.
    # Still written per session and persisted for DB schema compatibility.
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

    # Wide-window rolling accuracy for high-accuracy suppression.
    # Populated at runtime from a separate DB query with a larger window
    # (e.g., 500 keystrokes vs 200 for the standard window).
    rolling_accuracy_wide: float = 1.0
    rolling_keystroke_count_wide: int = 0

    # RT-based mastery statistics.
    # Populated at runtime from DB query; not persisted.
    median_rt: float = 0.0
    """Median reaction time (ms) over the RT mastery window."""

    rt_cv: float = 0.0
    """Coefficient of variation of reaction times."""

    rt_keystroke_count: int = 0
    """Number of correct keystrokes in the RT mastery window."""

    rt_factor: float = 0.0
    """Ratio of this letter's median RT to space median RT.
    Lower is better.  < mastery_rt_factor = mastery candidate."""

    # Legacy mastery fields — kept for DB schema compatibility.
    # No longer updated; RT-based mastery is used instead.
    mastery_score: float = 0.0
    """Legacy mastery score (no longer updated)."""

    mastery_qualifying_keystrokes: int = 0
    """Legacy qualifying keystrokes (no longer updated).
    Informational — NOT used to compute mastery_score (the score is
    tracked independently, pushed up by practice, pulled down by decay).
    Freezes (does not reset) on degradation."""

    def _state_bonus(
        self,
        introducing: float = 3.0,
        degraded: float = 2.0,
        consolidating: float = 1.0,
        recently_stable: float = 1.0,
        recently_stable_keystrokes: int = 800,
    ) -> float:
        """Training weight bonus based on current letter state.

        New/struggling letters get more practice repetitions.
        Recently-stable letters get a decaying bonus based on
        per-letter keystroke count to solidify the motor pattern
        before the letter is fully settled.
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
                    recently_stable_keystrokes > 0
                    and self.rolling_keystroke_count < recently_stable_keystrokes
                ):
                    # Linear decay: full bonus at 0 keystrokes, 0 at threshold
                    return recently_stable * (
                        1.0 - self.rolling_keystroke_count / recently_stable_keystrokes
                    )
                return 0.0
            case _:
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
        recently_stable_keystrokes: int = 800,
        volume_window: int = 200,
        volume_deficit: float = 1.0,
        mastered: float = 0.5,
        high_accuracy_threshold: float = 0.98,
        high_accuracy_min_keystrokes: int = 500,
        high_accuracy_factor: float = 0.1,
    ) -> float:
        """Need-based training weight for text generation.

        Non-mastered letters get base weight 1.0; MASTERED letters get
        ``mastered`` (default 0.5) to free share for non-mastered letters.
        Bonuses are added for training need: state (new/degraded letters
        need more reps), accuracy gap (struggling letters), recently-stable
        consolidation, and volume deficit.

        A final multiplier suppresses highly accurate letters: if the
        wide-window rolling accuracy exceeds ``high_accuracy_threshold``
        and enough keystrokes have been recorded, the entire weight is
        multiplied by ``high_accuracy_factor`` (e.g. 0.1 = 10%).

        Args:
            error_threshold: Error rate above which the accuracy-gap bonus
                kicks in.  Pass ``1 - config.advancement_accuracy`` for
                config-aware weighting.
            introducing: State bonus for INTRODUCING letters.
            degraded: State bonus for DEGRADED letters.
            consolidating: State bonus for CONSOLIDATING letters.
            recently_stable: Max consolidation bonus for recently-stable
                letters.  Decays linearly over ``recently_stable_keystrokes``.
            recently_stable_keystrokes: Per-letter keystrokes in STABLE
                state before the consolidation bonus fully decays.
            volume_window: Rolling accuracy window size (keystrokes).
                Letters with fewer keystrokes get a volume deficit bonus.
            volume_deficit: Maximum volume deficit bonus.
            mastered: Base weight for MASTERED letters (replaces 1.0).
            high_accuracy_threshold: Accuracy above which suppression applies.
            high_accuracy_min_keystrokes: Min keystrokes in the wide window
                before suppression can activate.
            high_accuracy_factor: Multiply weight by this when suppressed.
        """
        base = mastered if self.state == LetterState.MASTERED else 1.0
        weight = (
            base
            + self._state_bonus(
                introducing,
                degraded,
                consolidating,
                recently_stable,
                recently_stable_keystrokes,
            )
            + self._accuracy_gap_bonus(error_threshold)
            + self._volume_deficit_bonus(volume_window, volume_deficit)
        )

        # Suppress highly accurate letters (wide-window check)
        if (
            self.rolling_keystroke_count_wide >= high_accuracy_min_keystrokes
            and self.rolling_accuracy_wide >= high_accuracy_threshold
        ):
            weight *= high_accuracy_factor

        return weight
