"""Tests for letter management and state transitions."""

from datetime import datetime

from typing_trainer.config import Config
from typing_trainer.core.letter_manager import LetterManager
from typing_trainer.models.letter_state import LetterState, LetterStats, RunMode
from typing_trainer.models.run_result import PerLetterResult, RunResult
from typing_trainer.models.session import Session


def make_session(
    accuracy: float = 0.96,
    keystrokes: int = 350,
    per_letter_errors: dict[str, float] | None = None,
) -> Session:
    """Create a session with the given aggregate stats."""
    session = Session(start_time=datetime.now())

    run = RunResult(
        total_keystrokes=keystrokes,
        cognitive_errors=int(keystrokes * (1 - accuracy)),
        accuracy=accuracy,
    )

    if per_letter_errors:
        for letter, error_rate in per_letter_errors.items():
            attempts = keystrokes // len(per_letter_errors)
            run.per_letter[letter] = PerLetterResult(
                letter=letter,
                total_attempts=attempts,
                cognitive_errors=int(attempts * error_rate),
            )

    session.runs.append(run)
    return session


class TestInitialization:
    def test_initialize_first_letters_de(self):
        config = Config(language="de")
        manager = LetterManager(config)
        letters = manager.initialize_first_letters(count=2)
        assert len(letters) == 2
        assert "e" in letters  # most frequent in German
        assert "n" in letters  # second most frequent
        assert letters["e"].state == LetterState.INTRODUCING

    def test_initialize_first_letters_en(self):
        config = Config(language="en")
        manager = LetterManager(config)
        letters = manager.initialize_first_letters(count=3)
        assert "e" in letters
        assert "n" in letters
        assert "i" in letters

    def test_get_next_letter(self):
        config = Config(language="de")
        manager = LetterManager(config)
        active = {"e": LetterStats(letter="e"), "n": LetterStats(letter="n")}
        next_letter = manager.get_next_letter(active)
        assert next_letter == "i"  # third most frequent in German


class TestAdvancement:
    """Tests for the rolling-window advancement system.

    Advancement criteria:
    1. Per-letter accuracy >= 95% in rolling window (200 keystrokes per letter)
    2. Each letter has enough data (>= window size)
    3. Total keystrokes since last introduction >= 500
    """

    def test_advancement_succeeds(self):
        config = Config(
            advancement_accuracy=0.95,
            advancement_min_keystrokes=500,
            advancement_accuracy_window=200,
        )
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", state=LetterState.STABLE, keystrokes_at_introduction=0),
            "n": LetterStats(letter="n", state=LetterState.STABLE, keystrokes_at_introduction=0),
        }
        rolling = {
            "e": (0.97, 200),
            "n": (0.96, 200),
        }
        check = manager.check_advancement(active, rolling, total_keystrokes=600)
        assert check.can_advance is True
        assert check.next_letter == "i"

    def test_advancement_fails_insufficient_keystrokes(self):
        config = Config(advancement_min_keystrokes=500)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", keystrokes_at_introduction=0),
        }
        rolling = {"e": (0.97, 200)}
        check = manager.check_advancement(active, rolling, total_keystrokes=300)
        assert check.can_advance is False
        assert "more keystrokes" in check.reasons[0]

    def test_advancement_fails_low_accuracy(self):
        config = Config(advancement_accuracy=0.95, advancement_min_keystrokes=500)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", keystrokes_at_introduction=0),
        }
        rolling = {"e": (0.92, 200)}  # below 95%
        check = manager.check_advancement(active, rolling, total_keystrokes=600)
        assert check.can_advance is False
        assert len(check.per_letter_issues) > 0

    def test_advancement_fails_insufficient_data(self):
        config = Config(advancement_accuracy_window=200, advancement_min_keystrokes=500)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", keystrokes_at_introduction=0),
        }
        rolling = {"e": (0.97, 100)}  # only 100 keystrokes, need 200
        check = manager.check_advancement(active, rolling, total_keystrokes=600)
        assert check.can_advance is False
        assert "more practice" in check.reasons[0].lower()

    def test_advancement_tracks_keystrokes_since_introduction(self):
        config = Config(advancement_min_keystrokes=500)
        manager = LetterManager(config)
        # Last letter was introduced when total was 1000
        active = {
            "e": LetterStats(letter="e", keystrokes_at_introduction=0),
            "n": LetterStats(letter="n", keystrokes_at_introduction=1000),
        }
        rolling = {"e": (0.97, 200), "n": (0.96, 200)}
        # Total is 1400 -> only 400 since 'n' was introduced
        check = manager.check_advancement(active, rolling, total_keystrokes=1400)
        assert check.can_advance is False
        assert check.keystrokes_since_introduction == 400

    def test_advancement_per_letter_progress(self):
        config = Config(advancement_accuracy_window=200)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", keystrokes_at_introduction=0),
            "n": LetterStats(letter="n", keystrokes_at_introduction=0),
        }
        rolling = {"e": (0.97, 200), "n": (0.93, 200)}
        check = manager.check_advancement(active, rolling, total_keystrokes=600)
        assert len(check.per_letter_progress) == 2
        # e meets accuracy, n does not
        e_prog = next(p for p in check.per_letter_progress if p.letter == "e")
        n_prog = next(p for p in check.per_letter_progress if p.letter == "n")
        assert e_prog.meets_accuracy is True
        assert n_prog.meets_accuracy is False

    def test_all_letters_active(self):
        config = Config(language="de")
        manager = LetterManager(config)
        active = {ch: LetterStats(letter=ch) for ch in "abcdefghijklmnopqrstuvwxyz"}
        check = manager.check_advancement(active, {}, total_keystrokes=10000)
        assert check.next_letter is None
        assert check.can_advance is False


class TestStateTransitions:
    def test_introducing_to_consolidating(self):
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.INTRODUCING,
                sessions_since_introduced=1,
                rolling_error_rate=0.03,  # below 5% -> passes accuracy gate
            )
        }

        session = make_session(accuracy=0.96, per_letter_errors={"e": 0.03})
        active, warnings = manager.update_states_after_session(active, session)

        # sessions_since_introduced is now 2 AND rolling accuracy OK -> consolidating
        assert active["e"].state == LetterState.CONSOLIDATING

    def test_introducing_stays_when_struggling(self):
        """A letter with 2+ sessions but high error rate stays INTRODUCING."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.INTRODUCING,
                sessions_since_introduced=1,
                rolling_error_rate=0.12,  # 12% error — well above 5%
            )
        }

        session = make_session(accuracy=0.88, per_letter_errors={"e": 0.12})
        active, warnings = manager.update_states_after_session(active, session)

        # sessions_since_introduced is 2 but rolling accuracy too low
        assert active["e"].state == LetterState.INTRODUCING

    def test_introducing_promotes_at_threshold_boundary(self):
        """A letter exactly at the error threshold should promote."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.INTRODUCING,
                sessions_since_introduced=1,
                rolling_error_rate=0.05,  # exactly 5% = threshold
            )
        }

        session = make_session(accuracy=0.95, per_letter_errors={"e": 0.05})
        active, warnings = manager.update_states_after_session(active, session)

        # Exactly at threshold -> should promote (<=, not <)
        assert active["e"].state == LetterState.CONSOLIDATING

    def test_consolidating_to_stable(self):
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.CONSOLIDATING,
                sessions_since_introduced=5,
                accuracy_history=[0.96, 0.97],  # 2 good sessions already
            )
        }

        session = make_session(accuracy=0.96, per_letter_errors={"e": 0.03})
        active, warnings = manager.update_states_after_session(active, session)

        # Now has 3 sessions above threshold -> stable
        assert active["e"].state == LetterState.STABLE

    def test_stable_to_degraded(self):
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                sessions_since_introduced=10,
                rolling_error_rate=0.08,  # 8% > 5% threshold
            )
        }

        session = make_session(accuracy=0.88, per_letter_errors={"e": 0.12})
        active, warnings = manager.update_states_after_session(active, session)

        # Rolling error rate above threshold -> degraded
        assert active["e"].state == LetterState.DEGRADED
        assert len(warnings) > 0

    def test_stable_not_degraded_when_rolling_ok(self):
        """A stable letter with good rolling accuracy should NOT degrade,
        even if the current session had a bad per-session accuracy."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=0.9,
                sessions_since_introduced=10,
                rolling_error_rate=0.035,  # 3.5% — below 5% threshold
            )
        }

        # Bad session accuracy, but rolling window is fine.
        # Stability drops 0.9 -> 0.8 (still above 0.5 revert threshold).
        session = make_session(accuracy=0.88, per_letter_errors={"e": 0.12})
        active, warnings = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.STABLE
        assert len(warnings) == 0

    def test_stable_degraded_at_boundary(self):
        """Exactly at the threshold (5.0% error rate) should NOT degrade
        — degradation requires strictly above threshold."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                sessions_since_introduced=10,
                rolling_error_rate=0.05,  # exactly 5% — at threshold, not above
            )
        }

        session = make_session(accuracy=0.95, per_letter_errors={"e": 0.05})
        active, warnings = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.STABLE

    def test_degraded_to_consolidating(self):
        """A degraded letter with error rate below threshold recovers to
        CONSOLIDATING (not STABLE), requiring the normal consolidation
        period before reaching STABLE again."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                sessions_since_introduced=10,
                rolling_error_rate=0.03,  # 3% — below 5% threshold
            )
        }

        session = make_session(accuracy=0.96, per_letter_errors={"e": 0.03})
        active, warnings = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.CONSOLIDATING

    def test_degraded_to_consolidating_at_threshold(self):
        """A degraded letter exactly at the 5% threshold recovers to
        CONSOLIDATING (error_rate <= threshold)."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                sessions_since_introduced=10,
                rolling_error_rate=0.05,  # exactly 5% = entry threshold
            )
        }

        session = make_session(accuracy=0.95, per_letter_errors={"e": 0.05})
        active, warnings = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.CONSOLIDATING

    def test_degraded_stays_above_threshold(self):
        """A degraded letter with error rate above 5% stays DEGRADED."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                sessions_since_introduced=10,
                rolling_error_rate=0.051,  # just above 5%
            )
        }

        session = make_session(accuracy=0.949, per_letter_errors={"e": 0.051})
        active, warnings = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.DEGRADED

    def test_degraded_full_recovery_path(self):
        """DEGRADED -> CONSOLIDATING -> STABLE full recovery after 3 sessions."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                sessions_since_introduced=10,
                rolling_error_rate=0.03,
            )
        }

        # Session 1: recovers to CONSOLIDATING
        session1 = make_session(accuracy=0.97, per_letter_errors={"e": 0.03})
        active, _ = manager.update_states_after_session(active, session1)
        assert active["e"].state == LetterState.CONSOLIDATING

        # Sessions 2-4: 3 good sessions -> STABLE
        for _ in range(3):
            active["e"].rolling_error_rate = 0.03
            session = make_session(accuracy=0.97, per_letter_errors={"e": 0.03})
            active, _ = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.STABLE

    def test_degraded_stays_degraded(self):
        """A degraded letter with rolling error rate still above threshold
        should stay degraded."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                sessions_since_introduced=10,
                rolling_error_rate=0.07,  # 7% — still above 5%
            )
        }

        session = make_session(accuracy=0.93, per_letter_errors={"e": 0.07})
        active, warnings = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.DEGRADED


class TestStabilityPenalty:
    """Tests for stability_score +0.2/-0.1 on good/bad sessions."""

    def test_bad_session_decrements_stability(self):
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=0.7,
                rolling_error_rate=0.03,
            ),
        }
        session = make_session(accuracy=0.90, per_letter_errors={"e": 0.10})
        active, _ = manager.update_states_after_session(active, session)
        assert abs(active["e"].stability_score - 0.6) < 1e-9

    def test_good_session_increments_stability(self):
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=0.7,
                rolling_error_rate=0.02,
            ),
        }
        session = make_session(accuracy=0.97, per_letter_errors={"e": 0.03})
        active, _ = manager.update_states_after_session(active, session)
        assert abs(active["e"].stability_score - 0.9) < 1e-9

    def test_stability_floor_at_zero(self):
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.CONSOLIDATING,
                stability_score=0.05,
                rolling_error_rate=0.03,
            ),
        }
        session = make_session(accuracy=0.85, per_letter_errors={"e": 0.15})
        active, _ = manager.update_states_after_session(active, session)
        assert active["e"].stability_score == 0.0

    def test_stable_reverts_to_consolidating_below_threshold(self):
        config = Config(
            advancement_accuracy=0.95,
            stability_revert_threshold=0.5,
        )
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=0.5,
                rolling_error_rate=0.03,  # below degradation threshold
            ),
        }
        session = make_session(accuracy=0.90, per_letter_errors={"e": 0.10})
        active, _ = manager.update_states_after_session(active, session)
        # 0.5 - 0.1 = 0.4 < 0.5 threshold
        assert abs(active["e"].stability_score - 0.4) < 1e-9
        assert active["e"].state == LetterState.CONSOLIDATING
        assert active["e"].sessions_in_current_state == 0

    def test_no_revert_when_stability_stays_above_threshold(self):
        config = Config(
            advancement_accuracy=0.95,
            stability_revert_threshold=0.5,
        )
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=0.7,
                rolling_error_rate=0.03,
            ),
        }
        session = make_session(accuracy=0.90, per_letter_errors={"e": 0.10})
        active, _ = manager.update_states_after_session(active, session)
        # 0.7 - 0.1 = 0.6 >= 0.5 threshold — stays STABLE
        assert abs(active["e"].stability_score - 0.6) < 1e-9
        assert active["e"].state == LetterState.STABLE

    def test_no_penalty_when_letter_not_practiced(self):
        """Letters not typed in the session keep their stability unchanged."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                stability_score=0.7,
                rolling_error_rate=0.02,
            ),
            "n": LetterStats(
                letter="n",
                state=LetterState.STABLE,
                stability_score=0.8,
                rolling_error_rate=0.02,
            ),
        }
        # Only 'e' was practiced, 'n' was not
        session = make_session(accuracy=0.90, per_letter_errors={"e": 0.10})
        active, _ = manager.update_states_after_session(active, session)
        assert abs(active["e"].stability_score - 0.6) < 1e-9  # penalized
        assert abs(active["n"].stability_score - 0.8) < 1e-9  # unchanged


class TestFailThreshold:
    def test_standard_relearning_threshold(self):
        config = Config(fail_threshold_relearning=0.90)
        manager = LetterManager(config)
        active = {"e": LetterStats(letter="e", state=LetterState.CONSOLIDATING)}

        threshold = manager.get_fail_threshold(active, RunMode.RELEARNING)
        assert threshold == 0.90

    def test_speed_threshold(self):
        config = Config(fail_threshold_speed=0.95)
        manager = LetterManager(config)
        active = {"e": LetterStats(letter="e", state=LetterState.STABLE)}

        threshold = manager.get_fail_threshold(active, RunMode.SPEED)
        assert threshold == 0.95

    def test_introducing_s1_threshold(self):
        config = Config(fail_threshold_introducing_s1=0.70)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", state=LetterState.STABLE),
            "n": LetterStats(
                letter="n",
                state=LetterState.INTRODUCING,
                sessions_since_introduced=0,
            ),
        }

        threshold = manager.get_fail_threshold(active, RunMode.RELEARNING)
        assert threshold == 0.70

    def test_introducing_s2_threshold(self):
        config = Config(fail_threshold_introducing_s2=0.80)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(letter="e", state=LetterState.STABLE),
            "n": LetterStats(
                letter="n",
                state=LetterState.INTRODUCING,
                sessions_since_introduced=1,
            ),
        }

        threshold = manager.get_fail_threshold(active, RunMode.RELEARNING)
        assert threshold == 0.80


class TestRecheckAllStates:
    """Tests for LetterManager.recheck_all_states()."""

    def test_no_change_returns_false(self):
        """No state changes → returns False."""
        manager = LetterManager(Config())
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                rolling_error_rate=0.02,
                sessions_since_introduced=5,
                accuracy_history=[0.98, 0.97, 0.96],
            ),
        }
        assert manager.recheck_all_states(active) is False
        assert active["e"].state == LetterState.STABLE

    def test_stable_degrades_on_high_error(self):
        """STABLE → DEGRADED when rolling_error_rate > 5%."""
        manager = LetterManager(Config())
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                rolling_error_rate=0.08,
                sessions_since_introduced=5,
                sessions_in_current_state=3,
                accuracy_history=[0.98, 0.97, 0.96],
            ),
        }
        assert manager.recheck_all_states(active) is True
        assert active["e"].state == LetterState.DEGRADED
        assert active["e"].sessions_in_current_state == 0

    def test_mastered_degrades_on_high_error(self):
        """MASTERED → DEGRADED when rolling_error_rate > 5%."""
        manager = LetterManager(Config())
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.MASTERED,
                rolling_error_rate=0.06,
                mastery_score=0.9,
                sessions_since_introduced=50,
                sessions_in_current_state=10,
                accuracy_history=[0.98] * 5,
            ),
        }
        assert manager.recheck_all_states(active) is True
        assert active["e"].state == LetterState.DEGRADED

    def test_degraded_recovers_to_consolidating(self):
        """DEGRADED -> CONSOLIDATING when rolling_error_rate <= entry threshold."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                rolling_error_rate=0.03,
                sessions_since_introduced=5,
                sessions_in_current_state=2,
            ),
        }
        assert manager.recheck_all_states(active) is True
        assert active["e"].state == LetterState.CONSOLIDATING

    def test_degraded_recovers_at_exact_threshold(self):
        """DEGRADED -> CONSOLIDATING when rolling_error_rate == 5%."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                rolling_error_rate=0.05,
                sessions_since_introduced=5,
            ),
        }
        assert manager.recheck_all_states(active) is True
        assert active["e"].state == LetterState.CONSOLIDATING

    def test_degraded_stays_if_not_recovered(self):
        """DEGRADED stays DEGRADED if error rate still above threshold."""
        config = Config(advancement_accuracy=0.95)
        manager = LetterManager(config)
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.DEGRADED,
                rolling_error_rate=0.051,
                sessions_since_introduced=5,
            ),
        }
        assert manager.recheck_all_states(active) is False
        assert active["e"].state == LetterState.DEGRADED

    def test_introducing_stays_introducing(self):
        """INTRODUCING should not promote mid-session (needs session count)."""
        manager = LetterManager(Config())
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.INTRODUCING,
                rolling_error_rate=0.02,
                sessions_since_introduced=0,
            ),
        }
        assert manager.recheck_all_states(active) is False
        assert active["e"].state == LetterState.INTRODUCING

    def test_multiple_letters_mixed(self):
        """Multiple letters with different transitions."""
        manager = LetterManager(Config())
        active = {
            "e": LetterStats(
                letter="e",
                state=LetterState.STABLE,
                rolling_error_rate=0.08,
                sessions_since_introduced=5,
                accuracy_history=[0.98, 0.97, 0.96],
            ),
            "n": LetterStats(
                letter="n",
                state=LetterState.STABLE,
                rolling_error_rate=0.02,
                sessions_since_introduced=5,
                accuracy_history=[0.98, 0.97, 0.96],
            ),
        }
        assert manager.recheck_all_states(active) is True
        assert active["e"].state == LetterState.DEGRADED
        assert active["n"].state == LetterState.STABLE
