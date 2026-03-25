"""Letter set management: introduction, advancement, regression, state transitions.

Manages the active letter set and determines when new letters should be
introduced based on accuracy criteria across sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from typing_trainer.config import Config
from typing_trainer.models.keyboard_layout import KeyboardLayout, load_keyboard
from typing_trainer.models.letter_state import LetterState, LetterStats, RunMode
from typing_trainer.models.session import Session


@dataclass
class PerLetterProgress:
    """Per-letter accuracy progress toward advancement."""

    letter: str
    accuracy: float = 1.0
    keystrokes_in_window: int = 0
    window_size: int = 200
    required_accuracy: float = 0.95
    meets_accuracy: bool = True
    has_enough_data: bool = False


@dataclass
class AdvancementCheck:
    """Result of checking whether a new letter can be introduced."""

    can_advance: bool = False
    reasons: list[str] = field(default_factory=list)
    next_letter: str | None = None

    # Progress toward advancement
    keystrokes_since_introduction: int = 0
    keystrokes_needed: int = 500
    per_letter_progress: list[PerLetterProgress] = field(default_factory=list)
    per_letter_issues: list[str] = field(default_factory=list)


@dataclass
class DegradationWarning:
    """Warning about a letter that has degraded."""

    letter: str
    current_error_rate: float
    sessions_below_threshold: int


class LetterManager:
    """Manages the active letter set and state transitions.

    State machine per letter:
        introducing -> consolidating -> stable -> mastered
                                         ↑          ↓
                                         ← degraded ←
    """

    def __init__(
        self,
        config: Config,
        keyboard_layout: KeyboardLayout | None = None,
    ) -> None:
        self.config = config
        self.keyboard_layout = keyboard_layout or load_keyboard(config.keyboard_layout)
        self._introduction_order: list[str] | None = None

    @property
    def introduction_order(self) -> list[str]:
        """Get the letter introduction order for the current language."""
        if self._introduction_order is None:
            self._introduction_order = self.keyboard_layout.get_introduction_order(
                self.config.language
            )
        return self._introduction_order

    def set_introduction_order(self, order: list[str]) -> None:
        """Override the introduction order (user customization)."""
        self._introduction_order = list(order)

    def get_next_letter(self, active_letters: dict[str, LetterStats]) -> str | None:
        """Get the next letter to introduce, or None if all are active."""
        active_set = set(active_letters.keys())
        for letter in self.introduction_order:
            if letter not in active_set:
                return letter
        return None

    def initialize_first_letters(self, count: int = 2) -> dict[str, LetterStats]:
        """Create the initial active letter set for a new user.

        Starts with the N most frequent letters.
        """
        letters: dict[str, LetterStats] = {}
        for letter in self.introduction_order[:count]:
            letters[letter] = LetterStats(
                letter=letter,
                state=LetterState.INTRODUCING,
                sessions_since_introduced=0,
                sessions_in_current_state=0,
                last_practiced=datetime.now(),
            )
        return letters

    def initialize_all_letters(self) -> dict[str, LetterStats]:
        """Create active letter set with ALL letters in STABLE state.

        For users who already know the key positions and want to skip
        the Learn Keys phase.  All letters from the introduction order
        plus space are created as STABLE.
        """
        now = datetime.now()
        letters: dict[str, LetterStats] = {}
        for letter in self.introduction_order:
            letters[letter] = LetterStats(
                letter=letter,
                state=LetterState.STABLE,
                sessions_since_introduced=0,
                sessions_in_current_state=0,
                last_practiced=now,
            )
        # Space is always included
        if " " not in letters:
            letters[" "] = LetterStats(
                letter=" ",
                state=LetterState.STABLE,
                sessions_since_introduced=0,
                sessions_in_current_state=0,
                last_practiced=now,
            )
        return letters

    def check_advancement(
        self,
        active_letters: dict[str, LetterStats],
        rolling_accuracy: dict[str, tuple[float, int]],
        total_keystrokes: int,
    ) -> AdvancementCheck:
        """Check whether conditions are met to introduce a new letter.

        Criteria (all must be met simultaneously):
        1. Per-letter accuracy >= advancement_accuracy in rolling window for each letter
        2. Each letter has enough keystrokes in the window (>= advancement_accuracy_window)
        3. Total keystrokes since last introduction >= advancement_min_keystrokes

        Args:
            active_letters: Current active letter set.
            rolling_accuracy: Per-letter (accuracy, keystrokes_in_window) from DB.
            total_keystrokes: Total cognitive keystrokes across all runs.
        """
        window = self.config.advancement_accuracy_window
        result = AdvancementCheck(
            keystrokes_needed=self.config.advancement_min_keystrokes,
        )

        next_letter = self.get_next_letter(active_letters)
        if next_letter is None:
            result.reasons.append("All letters are already active.")
            return result
        result.next_letter = next_letter

        # Find the most recently introduced letter to compute keystrokes since
        max_ks_at_intro = max(
            (s.keystrokes_at_introduction for s in active_letters.values()),
            default=0,
        )
        result.keystrokes_since_introduction = max(
            0, total_keystrokes - max_ks_at_intro
        )

        # Check 1: Total keystrokes since last introduction
        volume_ok = (
            result.keystrokes_since_introduction
            >= self.config.advancement_min_keystrokes
        )
        if not volume_ok:
            remaining = (
                self.config.advancement_min_keystrokes
                - result.keystrokes_since_introduction
            )
            result.reasons.append(f"Need {remaining} more keystrokes.")

        # Check 2: Per-letter rolling accuracy
        all_letters_ok = True
        for letter, stats in sorted(active_letters.items()):
            acc, ks_count = rolling_accuracy.get(letter, (1.0, 0))
            has_enough = ks_count >= window
            meets_acc = acc >= self.config.advancement_accuracy

            progress = PerLetterProgress(
                letter=letter,
                accuracy=acc,
                keystrokes_in_window=ks_count,
                window_size=window,
                required_accuracy=self.config.advancement_accuracy,
                meets_accuracy=meets_acc,
                has_enough_data=has_enough,
            )
            result.per_letter_progress.append(progress)

            if not has_enough:
                all_letters_ok = False
            elif not meets_acc:
                all_letters_ok = False
                result.per_letter_issues.append(
                    f"'{letter}': {acc:.1%} (need {self.config.advancement_accuracy:.0%})"
                )

        if not all_letters_ok and not result.per_letter_issues:
            # Not enough data yet for some letters
            insufficient = [
                p.letter for p in result.per_letter_progress if not p.has_enough_data
            ]
            if insufficient:
                result.reasons.append(
                    f"Need more practice for: {', '.join(insufficient)}"
                )

        if result.per_letter_issues:
            result.reasons.append(
                "Accuracy too low for: " + ", ".join(result.per_letter_issues)
            )

        result.can_advance = (
            volume_ok and all_letters_ok and len(result.per_letter_issues) == 0
        )
        return result

    def introduce_letter(
        self,
        letter: str,
        active_letters: dict[str, LetterStats],
        total_keystrokes: int = 0,
    ) -> dict[str, LetterStats]:
        """Add a new letter to the active set.

        Args:
            letter: The letter to introduce.
            active_letters: Current active letter set.
            total_keystrokes: Current total keystrokes (used as baseline
                for advancement progress tracking).

        Returns updated active_letters dict.
        """
        active_letters[letter] = LetterStats(
            letter=letter,
            state=LetterState.INTRODUCING,
            sessions_since_introduced=0,
            sessions_in_current_state=0,
            last_practiced=datetime.now(),
            keystrokes_at_introduction=total_keystrokes,
        )
        return active_letters

    def recheck_all_states(
        self,
        active_letters: dict[str, LetterStats],
        space_median_rt: float = 0.0,
    ) -> bool:
        """Recheck letter states based on rolling error rates and RT stats.

        This is a lightweight per-run state recheck.  It runs the same
        state machine as ``update_states_after_session`` but does NOT
        modify session counters, accuracy history, or stability score
        — those remain session-boundary-only operations.

        Additionally performs RT-based mastery transitions:
        - STABLE -> MASTERED when RT criteria are met
        - MASTERED -> STABLE when RT degrades above threshold

        Requires ``rolling_error_rate`` and RT fields (``median_rt``,
        ``rt_cv``, ``rt_keystroke_count``, ``rt_factor``) to be
        populated on each :class:`LetterStats` before calling.

        Returns ``True`` if any state changed (caller should persist).
        """
        changed = False
        for stats in active_letters.values():
            new_state = self._compute_new_state(stats)
            if new_state != stats.state:
                stats.sessions_in_current_state = 0
                stats.state = new_state
                changed = True

        # RT-based mastery transitions (only if we have space data)
        if space_median_rt > 0:
            rt_changes = self._check_rt_transitions(active_letters, space_median_rt)
            if rt_changes:
                changed = True

        return changed

    def _check_rt_transitions(
        self,
        active_letters: dict[str, LetterStats],
        space_median_rt: float,
    ) -> bool:
        """Check RT-based STABLE->MASTERED and MASTERED->STABLE transitions.

        Returns ``True`` if any state changed.
        """
        changed = False
        error_threshold = 1.0 - self.config.advancement_accuracy

        for stats in active_letters.values():
            if stats.rt_keystroke_count < self.config.mastery_min_keystrokes:
                continue  # not enough data

            # STABLE -> MASTERED
            if (
                stats.state == LetterState.STABLE
                and stats.rt_factor > 0
                and stats.rt_factor < self.config.mastery_rt_factor
                and stats.rt_cv < self.config.mastery_cv_threshold
                and stats.rolling_error_rate <= error_threshold
            ):
                stats.state = LetterState.MASTERED
                stats.sessions_in_current_state = 0
                changed = True

            # MASTERED -> STABLE (RT degradation)
            elif (
                stats.state == LetterState.MASTERED
                and stats.rt_factor > 0
                and stats.rt_factor > self.config.stable_rt_factor
            ):
                stats.state = LetterState.STABLE
                stats.sessions_in_current_state = 0
                changed = True

        return changed

    def update_states_after_session(
        self,
        active_letters: dict[str, LetterStats],
        session: Session,
    ) -> tuple[dict[str, LetterStats], list[DegradationWarning]]:
        """Update letter states based on a completed session.

        Returns (updated_letters, warnings).
        """
        warnings: list[DegradationWarning] = []
        per_letter_errors = session.per_letter_error_rate()

        for letter, stats in active_letters.items():
            # Update basic tracking
            stats.sessions_since_introduced += 1
            stats.sessions_in_current_state += 1
            stats.last_practiced = datetime.now()

            # Update error rate from this session
            if letter in per_letter_errors:
                stats.error_rate_latest = per_letter_errors[letter]
            else:
                # Letter wasn't practiced in this session — keep old error rate
                pass

            # Update accuracy history (prepend most recent)
            session_letter_accuracy = 1.0 - stats.error_rate_latest
            stats.accuracy_history.insert(0, session_letter_accuracy)
            # Keep only last 10 sessions of history
            stats.accuracy_history = stats.accuracy_history[:10]

            # State transitions
            new_state = self._compute_new_state(stats)

            if (
                stats.state in (LetterState.STABLE, LetterState.MASTERED)
                and new_state == LetterState.DEGRADED
            ):
                warnings.append(
                    DegradationWarning(
                        letter=letter,
                        current_error_rate=stats.error_rate_latest,
                        sessions_below_threshold=1,
                    )
                )

            if new_state != stats.state:
                stats.sessions_in_current_state = 0
                stats.state = new_state

            # Update stability score — only for letters actually practiced
            # this session.  Letters not practiced keep their current score
            # (time decay handles absence separately).
            was_practiced = letter in per_letter_errors
            if was_practiced:
                if session_letter_accuracy >= self.config.advancement_accuracy:
                    stats.stability_score = min(1.0, stats.stability_score + 0.2)
                else:
                    stats.stability_score = max(0.0, stats.stability_score - 0.1)
                    # Revert STABLE to CONSOLIDATING if stability dropped
                    # below the review threshold — the motor pattern is no
                    # longer reliably encoded.
                    if (
                        stats.stability_score < self.config.stability_revert_threshold
                        and stats.state == LetterState.STABLE
                    ):
                        stats.state = LetterState.CONSOLIDATING
                        stats.sessions_in_current_state = 0

            # Mastery transitions are now RT-based and handled by
            # _check_rt_transitions() in recheck_all_states().
            # The old mastery_score increment logic has been removed.

        return active_letters, warnings

    def _compute_new_state(self, stats: LetterStats) -> LetterState:
        """Determine the new state for a letter based on its history."""
        match stats.state:
            case LetterState.INTRODUCING:
                # Require both minimum sessions AND adequate accuracy.
                # A letter struggling at >5% error rate stays INTRODUCING
                # (keeping lenient fail thresholds and higher practice weight)
                # until the user demonstrates competence.
                error_threshold = 1.0 - self.config.advancement_accuracy
                if (
                    stats.sessions_since_introduced >= 2
                    and stats.rolling_error_rate <= error_threshold
                ):
                    return LetterState.CONSOLIDATING
                return LetterState.INTRODUCING

            case LetterState.CONSOLIDATING:
                if self._is_stable(stats):
                    return LetterState.STABLE
                return LetterState.CONSOLIDATING

            case LetterState.STABLE:
                if self._is_degraded(stats):
                    return LetterState.DEGRADED
                # STABLE -> MASTERED is now RT-based, handled by
                # _check_rt_transitions() in recheck_all_states().
                return LetterState.STABLE

            case LetterState.MASTERED:
                # Same degradation trigger as STABLE
                if self._is_degraded(stats):
                    return LetterState.DEGRADED
                return LetterState.MASTERED

            case LetterState.DEGRADED:
                # Recovery goes through CONSOLIDATING rather than jumping
                # straight to STABLE.  The letter must then pass the normal
                # consolidation check (3 consecutive sessions >= threshold)
                # before reaching STABLE again.  This provides a structural
                # stability guarantee instead of a threshold-based hysteresis
                # gap, and keeps the UI consistent (a letter at exactly 95%
                # shows as CONSOLIDATING everywhere, not green in one place
                # and red in another).
                entry_threshold = 1.0 - self.config.advancement_accuracy
                if stats.rolling_error_rate <= entry_threshold:
                    return LetterState.CONSOLIDATING
                return LetterState.DEGRADED

            case _:
                return stats.state

    def _is_stable(self, stats: LetterStats) -> bool:
        """Check if a consolidating letter qualifies as stable.

        Stable = rolling accuracy >= threshold over a full keystroke
        window.  This is purely volume-based: the letter must have at
        least ``advancement_accuracy_window`` keystrokes in its rolling
        window, all meeting the accuracy criterion.

        Previous implementation checked ``accuracy_history`` (per-session
        accuracy over the last 3 sessions), which was sensitive to
        session size variability.
        """
        error_threshold = 1.0 - self.config.advancement_accuracy
        return (
            stats.rolling_keystroke_count >= self.config.advancement_accuracy_window
            and stats.rolling_error_rate <= error_threshold
        )

    def _is_degraded(self, stats: LetterStats) -> bool:
        """Check if a stable letter has degraded.

        Uses the rolling error rate (last 200 keystrokes) rather than
        per-session accuracy history, for consistency with the
        advancement system and robustness against small-sample sessions.
        """
        threshold = 1.0 - self.config.advancement_accuracy
        return stats.rolling_error_rate > threshold

    def get_fail_threshold(
        self,
        active_letters: dict[str, LetterStats],
        mode: RunMode,
    ) -> float:
        """Compute the fail threshold for the current run.

        Uses the progressive threshold for newly introduced letters.
        """
        if mode == RunMode.SPEED:
            return self.config.fail_threshold_speed

        if mode == RunMode.TRANSITION:
            return self.config.fail_threshold_transition

        # Check if any letter is in the introducing state
        introducing_letters = [
            s for s in active_letters.values() if s.state == LetterState.INTRODUCING
        ]

        if not introducing_letters:
            return self.config.fail_threshold_relearning

        # Use the most lenient threshold among introducing letters
        min_sessions = min(s.sessions_since_introduced for s in introducing_letters)

        if min_sessions == 0:
            return self.config.fail_threshold_introducing_s1
        elif min_sessions == 1:
            return self.config.fail_threshold_introducing_s2
        else:
            return self.config.fail_threshold_relearning

    def get_degradation_warnings(
        self, active_letters: dict[str, LetterStats]
    ) -> list[DegradationWarning]:
        """Get current degradation warnings for display."""
        warnings: list[DegradationWarning] = []
        for stats in active_letters.values():
            if stats.state == LetterState.DEGRADED:
                warnings.append(
                    DegradationWarning(
                        letter=stats.letter,
                        current_error_rate=stats.rolling_error_rate,
                        sessions_below_threshold=stats.sessions_in_current_state,
                    )
                )
        return warnings
