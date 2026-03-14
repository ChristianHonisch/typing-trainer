"""Tests for the mastery system.

Covers mastery score computation, state transitions (STABLE -> MASTERED,
MASTERED -> DEGRADED), mastery decay, training weight adjustments,
and mastery increment logic.
"""

from datetime import datetime, timedelta

from typing_trainer.config import Config
from typing_trainer.core.letter_manager import LetterManager
from typing_trainer.core.spaced_repetition import SpacedRepetition
from typing_trainer.models.letter_state import LetterState, LetterStats
from typing_trainer.models.run_result import PerLetterResult, RunResult
from typing_trainer.models.session import Session
from typing_trainer.storage.database import Database
from typing_trainer.storage.repository import Repository


# ── Helpers ───────────────────────────────────────────────────────────


def make_session(
    per_letter_errors: dict[str, float] | None = None,
    keystrokes: int = 350,
) -> Session:
    """Create a session with per-letter error data."""
    session = Session(start_time=datetime.now())

    run = RunResult(
        total_keystrokes=keystrokes,
        cognitive_errors=0,
        accuracy=1.0,
    )

    if per_letter_errors:
        per_letter_count = keystrokes // max(len(per_letter_errors), 1)
        for letter, error_rate in per_letter_errors.items():
            attempts = per_letter_count
            errors = int(attempts * error_rate)
            run.per_letter[letter] = PerLetterResult(
                letter=letter,
                total_attempts=attempts,
                cognitive_errors=errors,
            )

    session.runs.append(run)
    return session


def make_stable_letter(
    letter: str,
    mastery_score: float = 0.0,
    mastery_qualifying_keystrokes: int = 0,
    sessions_in_state: int = 10,
    rolling_error_rate: float = 0.02,
    rolling_keystroke_count: int = 999,
) -> LetterStats:
    """Create a STABLE letter with configurable mastery."""
    return LetterStats(
        letter=letter,
        state=LetterState.STABLE,
        stability_score=0.9,
        last_practiced=datetime.now(),
        error_rate_latest=rolling_error_rate,
        sessions_in_current_state=sessions_in_state,
        sessions_since_introduced=20,
        accuracy_history=[0.97, 0.96, 0.98],
        mastery_score=mastery_score,
        mastery_qualifying_keystrokes=mastery_qualifying_keystrokes,
        rolling_error_rate=rolling_error_rate,
        rolling_keystroke_count=rolling_keystroke_count,
    )


def make_mastered_letter(
    letter: str,
    mastery_score: float = 0.9,
    rolling_error_rate: float = 0.02,
) -> LetterStats:
    """Create a MASTERED letter."""
    return LetterStats(
        letter=letter,
        state=LetterState.MASTERED,
        stability_score=0.9,
        last_practiced=datetime.now(),
        error_rate_latest=rolling_error_rate,
        sessions_in_current_state=5,
        sessions_since_introduced=80,
        accuracy_history=[0.97, 0.96, 0.98],
        mastery_score=mastery_score,
        mastery_qualifying_keystrokes=1200,
        rolling_error_rate=rolling_error_rate,
        rolling_keystroke_count=999,
    )


# ── Training Weight ───────────────────────────────────────────────────


class TestMasteredTrainingWeight:
    def test_mastered_base_weight_is_lower(self):
        """MASTERED letter gets base weight 0.5, not 1.0."""
        stats = make_mastered_letter("e")
        weight = stats.training_weight(mastered=0.5)
        # base=0.5, state_bonus=0.0, accuracy_gap=0 (error 0.02 < 0.05),
        # volume_deficit=0 (count=999)
        assert weight == 0.5

    def test_stable_base_weight_is_1(self):
        """STABLE (settled) letter gets base weight 1.0."""
        stats = make_stable_letter("e", sessions_in_state=15)
        weight = stats.training_weight(mastered=0.5)
        # base=1.0, no state bonus (settled), no accuracy gap, no volume deficit
        assert weight == 1.0

    def test_mastered_with_accuracy_gap(self):
        """MASTERED letter with high error rate gets accuracy gap bonus."""
        stats = make_mastered_letter("e", rolling_error_rate=0.10)
        stats.rolling_error_rate = 0.10
        weight = stats.training_weight(mastered=0.5)
        # base=0.5, state_bonus=0.0, accuracy_gap=(0.10 - 0.05)*50 = 2.5
        assert abs(weight - 3.0) < 0.01

    def test_mastered_effect_on_share(self):
        """With mastered letters, introducing letter gets more share."""
        config = Config()
        # 3 mastered (0.5 each), 1 introducing (1.0 + 3.0 = 4.0)
        mastered_a = make_mastered_letter("a")
        mastered_b = make_mastered_letter("b")
        mastered_c = make_mastered_letter("c")
        introducing = LetterStats(
            letter="d",
            state=LetterState.INTRODUCING,
            rolling_keystroke_count=999,
        )

        weights = [
            mastered_a.training_weight(mastered=config.weight_mastered),
            mastered_b.training_weight(mastered=config.weight_mastered),
            mastered_c.training_weight(mastered=config.weight_mastered),
            introducing.training_weight(mastered=config.weight_mastered),
        ]
        total = sum(weights)
        intro_share = weights[3] / total
        # 4.0 / (0.5*3 + 4.0) = 4.0 / 5.5 = 72.7%
        # (capped by max_letter_share in practice, but raw weight is clear)
        assert intro_share > 0.70


# ── Mastery Decay ────────────────────────────────────────────────────


class TestMasteryDecay:
    def test_no_decay_if_just_practiced(self):
        """No mastery decay if last_practiced is now."""
        config = Config()
        sr = SpacedRepetition(config)
        stats = make_mastered_letter("e", mastery_score=0.9)
        stats.last_practiced = datetime.now()
        decayed = sr.compute_mastery_decay(stats)
        assert abs(decayed - 0.9) < 0.001

    def test_decay_after_14_days_at_low_mastery(self):
        """At mastery=0, half-life is 14 days. After 14 days, score halves."""
        config = Config()
        sr = SpacedRepetition(config)
        stats = LetterStats(
            letter="e",
            state=LetterState.STABLE,
            mastery_score=0.01,  # Near zero for half-life ≈ 14 days
            last_practiced=datetime.now() - timedelta(days=14),
        )
        decayed = sr.compute_mastery_decay(stats)
        # Half-life = 14 + 0.01*(90-14) ≈ 14.76 days
        # After 14 days: 0.01 * 2^(-14/14.76) ≈ 0.01 * 0.513 ≈ 0.00513
        assert decayed < 0.006
        assert decayed > 0.004

    def test_decay_after_90_days_at_full_mastery(self):
        """At mastery=1.0, half-life is 90 days. After 90 days, score halves."""
        config = Config()
        sr = SpacedRepetition(config)
        stats = LetterStats(
            letter="e",
            state=LetterState.MASTERED,
            mastery_score=1.0,
            last_practiced=datetime.now() - timedelta(days=90),
        )
        decayed = sr.compute_mastery_decay(stats)
        assert abs(decayed - 0.5) < 0.01

    def test_mastered_reverts_to_stable_on_decay(self):
        """MASTERED letter reverts to STABLE if mastery drops below threshold."""
        config = Config(mastery_threshold=0.8)
        sr = SpacedRepetition(config)
        # Mastery 0.85, half-life ≈ 14 + 0.85*76 = 78.6 days
        # After 30 days: 0.85 * 2^(-30/78.6) ≈ 0.85 * 0.769 ≈ 0.654
        stats = make_mastered_letter("e", mastery_score=0.85)
        stats.last_practiced = datetime.now() - timedelta(days=30)

        active = {"e": stats}
        active, reverted = sr.apply_time_decay(active)

        assert "e" in reverted
        assert stats.state == LetterState.STABLE
        assert stats.mastery_score < 0.8

    def test_mastered_stays_if_mastery_above_threshold(self):
        """MASTERED letter stays MASTERED if mastery is still above threshold."""
        config = Config(mastery_threshold=0.8)
        sr = SpacedRepetition(config)
        stats = make_mastered_letter("e", mastery_score=0.95)
        stats.last_practiced = datetime.now() - timedelta(days=1)

        active = {"e": stats}
        active, reverted = sr.apply_time_decay(active)

        assert "e" not in reverted
        assert stats.state == LetterState.MASTERED
        assert stats.mastery_score > 0.8

    def test_zero_mastery_no_decay(self):
        """Letters with mastery=0 don't undergo mastery decay."""
        config = Config()
        sr = SpacedRepetition(config)
        stats = make_stable_letter("e", mastery_score=0.0)
        stats.last_practiced = datetime.now() - timedelta(days=30)
        decayed = sr.compute_mastery_decay(stats)
        assert decayed == 0.0


# ── State Transitions ────────────────────────────────────────────────


class TestMasteryStateTransitions:
    def test_stable_to_mastered(self):
        """STABLE letter with mastery >= threshold transitions to MASTERED."""
        config = Config(mastery_threshold=0.8)
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.85)
        new_state = manager._compute_new_state(stats)
        assert new_state == LetterState.MASTERED

    def test_stable_stays_stable_below_threshold(self):
        """STABLE letter with mastery < threshold stays STABLE."""
        config = Config(mastery_threshold=0.8)
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.5)
        new_state = manager._compute_new_state(stats)
        assert new_state == LetterState.STABLE

    def test_mastered_to_degraded(self):
        """MASTERED letter with high error rate degrades."""
        config = Config()
        manager = LetterManager(config)
        stats = make_mastered_letter("e", rolling_error_rate=0.08)
        new_state = manager._compute_new_state(stats)
        assert new_state == LetterState.DEGRADED

    def test_mastered_stays_mastered(self):
        """MASTERED letter with low error rate stays MASTERED."""
        config = Config()
        manager = LetterManager(config)
        stats = make_mastered_letter("e", rolling_error_rate=0.02)
        new_state = manager._compute_new_state(stats)
        assert new_state == LetterState.MASTERED

    def test_degraded_recovers_to_stable_not_mastered(self):
        """DEGRADED letter recovers to CONSOLIDATING, not directly to MASTERED."""
        config = Config()
        manager = LetterManager(config)
        stats = LetterStats(
            letter="e",
            state=LetterState.DEGRADED,
            mastery_score=0.9,  # High mastery, but still recovers to CONSOLIDATING
            rolling_error_rate=0.03,  # Below entry threshold (5%)
        )
        new_state = manager._compute_new_state(stats)
        assert new_state == LetterState.CONSOLIDATING

    def test_degraded_mastery_not_reset(self):
        """Mastery score is NOT reset when a letter degrades."""
        config = Config()
        manager = LetterManager(config)
        active = {"e": make_mastered_letter("e", mastery_score=0.9, rolling_error_rate=0.08)}
        session = make_session(per_letter_errors={"e": 0.08})

        active, _ = manager.update_states_after_session(active, session)

        # State should be DEGRADED, but mastery preserved
        assert active["e"].state == LetterState.DEGRADED
        assert active["e"].mastery_score == 0.9  # NOT reset


# ── Mastery Increment ────────────────────────────────────────────────


class TestMasteryIncrement:
    def test_qualifying_letter_gains_mastery(self):
        """STABLE letter with good accuracy gains mastery from session."""
        config = Config(mastery_keystrokes_required=1500)
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.0)
        active = {"e": stats}
        session = make_session(per_letter_errors={"e": 0.02}, keystrokes=350)
        # 350 keystrokes for letter "e" in this session

        active, _ = manager.update_states_after_session(active, session)

        # delta = 350 / 1500 ≈ 0.233
        assert active["e"].mastery_score > 0.2
        assert active["e"].mastery_qualifying_keystrokes == 350

    def test_non_qualifying_letter_no_mastery(self):
        """INTRODUCING letter does not gain mastery."""
        config = Config()
        manager = LetterManager(config)
        stats = LetterStats(
            letter="e",
            state=LetterState.INTRODUCING,
            sessions_since_introduced=0,
            rolling_error_rate=0.02,
            rolling_keystroke_count=999,
        )
        active = {"e": stats}
        session = make_session(per_letter_errors={"e": 0.02})

        active, _ = manager.update_states_after_session(active, session)

        assert active["e"].mastery_score == 0.0
        assert active["e"].mastery_qualifying_keystrokes == 0

    def test_high_error_rate_no_mastery(self):
        """STABLE letter with poor accuracy doesn't gain mastery."""
        config = Config()
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.3, rolling_error_rate=0.08)
        active = {"e": stats}
        session = make_session(per_letter_errors={"e": 0.08})

        active, _ = manager.update_states_after_session(active, session)

        # Mastery should not increase (error rate > 5%)
        assert active["e"].mastery_score == 0.3

    def test_mastery_capped_at_1(self):
        """Mastery score cannot exceed 1.0."""
        config = Config(mastery_keystrokes_required=100)
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.95)
        active = {"e": stats}
        session = make_session(per_letter_errors={"e": 0.01}, keystrokes=350)

        active, _ = manager.update_states_after_session(active, session)

        assert active["e"].mastery_score == 1.0

    def test_mastery_triggers_mastered_transition(self):
        """Mastery increment crossing threshold triggers STABLE -> MASTERED."""
        config = Config(mastery_threshold=0.8, mastery_keystrokes_required=100)
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.75)
        active = {"e": stats}
        # 350 / 100 = 3.5 delta → 0.75 + 3.5 = 4.25, capped to 1.0
        session = make_session(per_letter_errors={"e": 0.01}, keystrokes=350)

        active, _ = manager.update_states_after_session(active, session)

        assert active["e"].state == LetterState.MASTERED
        assert active["e"].mastery_score == 1.0

    def test_mastered_letter_continues_gaining(self):
        """MASTERED letter continues to gain mastery from practice."""
        config = Config(mastery_keystrokes_required=1500)
        manager = LetterManager(config)
        stats = make_mastered_letter("e", mastery_score=0.85)
        active = {"e": stats}
        session = make_session(per_letter_errors={"e": 0.02}, keystrokes=350)

        active, _ = manager.update_states_after_session(active, session)

        # delta = 350 / 1500 ≈ 0.233 → 0.85 + 0.233 = 1.0 (capped)
        assert active["e"].mastery_score > 0.85

    def test_unpracticed_letter_no_mastery_change(self):
        """Letter not practiced in a session gets no mastery increment."""
        config = Config()
        manager = LetterManager(config)
        stats = make_stable_letter("e", mastery_score=0.5)
        active = {"e": stats}
        session = make_session(per_letter_errors={})  # "e" not practiced

        active, _ = manager.update_states_after_session(active, session)

        assert active["e"].mastery_score == 0.5


# ── Session Helper ───────────────────────────────────────────────────


class TestSessionPerLetterKeystrokes:
    def test_single_run(self):
        session = Session(start_time=datetime.now())
        run = RunResult(total_keystrokes=100, accuracy=1.0)
        run.per_letter["e"] = PerLetterResult(letter="e", total_attempts=40)
        run.per_letter["n"] = PerLetterResult(letter="n", total_attempts=30)
        session.runs.append(run)

        assert session.per_letter_keystrokes("e") == 40
        assert session.per_letter_keystrokes("n") == 30
        assert session.per_letter_keystrokes("x") == 0

    def test_multiple_runs(self):
        session = Session(start_time=datetime.now())
        run1 = RunResult(total_keystrokes=50, accuracy=1.0)
        run1.per_letter["e"] = PerLetterResult(letter="e", total_attempts=20)
        run2 = RunResult(total_keystrokes=50, accuracy=1.0)
        run2.per_letter["e"] = PerLetterResult(letter="e", total_attempts=15)
        session.runs.extend([run1, run2])

        assert session.per_letter_keystrokes("e") == 35


# ── Repository Round-Trip ────────────────────────────────────────────


class TestMasteryPersistence:
    def test_mastery_fields_round_trip(self, tmp_path):
        db = Database(str(tmp_path / "test.db"))
        db.initialize()
        repo = Repository(db)

        stats = LetterStats(
            letter="e",
            state=LetterState.MASTERED,
            stability_score=0.9,
            mastery_score=0.85,
            mastery_qualifying_keystrokes=1200,
        )
        repo.save_letter_state(stats)

        loaded = repo.get_letter_state("e")
        assert loaded is not None
        assert loaded.state == LetterState.MASTERED
        assert loaded.mastery_score == 0.85
        assert loaded.mastery_qualifying_keystrokes == 1200

    def test_mastery_in_get_all_letter_states(self, tmp_path):
        db = Database(str(tmp_path / "test.db"))
        db.initialize()
        repo = Repository(db)

        stats = LetterStats(
            letter="e",
            state=LetterState.MASTERED,
            mastery_score=0.92,
            mastery_qualifying_keystrokes=1400,
        )
        repo.save_letter_state(stats)

        all_states = repo.get_all_letter_states()
        assert "e" in all_states
        assert all_states["e"].mastery_score == 0.92
        assert all_states["e"].mastery_qualifying_keystrokes == 1400

    def test_mastery_defaults_for_new_letter(self, tmp_path):
        db = Database(str(tmp_path / "test.db"))
        db.initialize()
        repo = Repository(db)

        stats = LetterStats(letter="e", state=LetterState.INTRODUCING)
        repo.save_letter_state(stats)

        loaded = repo.get_letter_state("e")
        assert loaded is not None
        assert loaded.mastery_score == 0.0
        assert loaded.mastery_qualifying_keystrokes == 0


# ── Config ───────────────────────────────────────────────────────────


class TestMasteryConfig:
    def test_default_values(self):
        config = Config()
        assert config.mastery_keystrokes_required == 1500
        assert config.mastery_threshold == 0.8
        assert config.mastery_half_life_min_days == 14.0
        assert config.mastery_half_life_max_days == 90.0
        assert config.weight_mastered == 0.5
