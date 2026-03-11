"""Tests for speed training management."""

from datetime import datetime

from typing_trainer.config import Config
from typing_trainer.core.speed_manager import SpeedManager
from typing_trainer.models.letter_state import LetterState, LetterStats, PracticeType, RunMode
from typing_trainer.models.run_result import PerLetterResult, RunResult
from typing_trainer.models.session import Session


def make_run(
    accuracy: float = 0.96,
    wpm: float = 35.0,
    completed: bool = True,
    failed: bool = False,
    mode: RunMode = RunMode.SPEED,
    per_letter_rts: dict[str, list[int]] | None = None,
) -> RunResult:
    result = RunResult(
        start_time=datetime(2026, 1, 1, 10, 0, 0),
        end_time=datetime(2026, 1, 1, 10, 1, 0),
        mode=mode,
        practice_type=PracticeType.RANDOM_WORDS,
        target_text="test",
        target_length=100,
        total_keystrokes=100,
        cognitive_errors=int(100 * (1 - accuracy)),
        accuracy=accuracy,
        wpm=wpm,
        completed=completed,
        failed=failed,
    )
    if per_letter_rts:
        for letter, rts in per_letter_rts.items():
            mean_rt = sum(rts) / len(rts) if rts else None
            result.per_letter[letter] = PerLetterResult(
                letter=letter,
                total_attempts=len(rts),
                reaction_times=rts,
                mean_reaction_time_ms=mean_rt,
            )
    return result


class TestSpeedEntryConditions:
    def test_available_when_all_stable_and_enough_sessions(self):
        config = Config(advancement_accuracy=0.95)
        mgr = SpeedManager(config)

        active = {
            "e": LetterStats(letter="e", state=LetterState.STABLE),
            "n": LetterStats(letter="n", state=LetterState.STABLE),
        }
        sessions = []
        for i in range(5):
            s = Session(start_time=datetime(2026, 1, i + 1, 10, 0, 0))
            run = RunResult(total_keystrokes=300, cognitive_errors=10, accuracy=0.967)
            s.runs.append(run)
            sessions.append(s)

        check = mgr.check_entry_conditions(active, sessions)
        assert check.available is True
        assert check.all_stable is True
        assert check.qualifying_sessions == 5

    def test_not_available_when_letter_not_stable(self):
        config = Config()
        mgr = SpeedManager(config)

        active = {
            "e": LetterStats(letter="e", state=LetterState.STABLE),
            "n": LetterStats(letter="n", state=LetterState.CONSOLIDATING),
        }
        check = mgr.check_entry_conditions(active, [])
        assert check.available is False
        assert check.all_stable is False

    def test_not_available_with_insufficient_sessions(self):
        config = Config(advancement_accuracy=0.95)
        mgr = SpeedManager(config)

        active = {
            "e": LetterStats(letter="e", state=LetterState.STABLE),
        }
        sessions = []
        for i in range(3):
            s = Session(start_time=datetime(2026, 1, i + 1, 10, 0, 0))
            run = RunResult(total_keystrokes=300, cognitive_errors=5, accuracy=0.983)
            s.runs.append(run)
            sessions.append(s)

        check = mgr.check_entry_conditions(active, sessions)
        assert check.available is False
        assert check.qualifying_sessions == 3


class TestSpeedRunProcessing:
    def test_passed_run_increases_target(self):
        config = Config(speed_increment=2, fail_threshold_speed=0.95)
        mgr = SpeedManager(config)
        mgr.target_wpm = 30.0

        result = make_run(accuracy=0.96, wpm=32.0, completed=True, failed=False)
        speed_result = mgr.process_speed_run(result)

        assert speed_result.passed is True
        assert speed_result.new_target_wpm == 32.0
        assert mgr.target_wpm == 32.0

    def test_failed_run_decreases_target(self):
        config = Config(speed_decrement=4, fail_threshold_speed=0.95)
        mgr = SpeedManager(config)
        mgr.target_wpm = 30.0

        result = make_run(accuracy=0.93, wpm=28.0, completed=True, failed=False)
        speed_result = mgr.process_speed_run(result)

        assert speed_result.passed is False
        assert speed_result.new_target_wpm == 26.0
        assert mgr.target_wpm == 26.0

    def test_aborted_run_decreases_target(self):
        config = Config(speed_decrement=4)
        mgr = SpeedManager(config)
        mgr.target_wpm = 40.0

        result = make_run(accuracy=0.85, completed=False, failed=True)
        speed_result = mgr.process_speed_run(result)

        assert speed_result.passed is False
        assert speed_result.new_target_wpm == 36.0

    def test_target_has_minimum(self):
        config = Config(speed_decrement=1)
        mgr = SpeedManager(config)
        mgr.target_wpm = 10.0

        result = make_run(accuracy=0.90, completed=True, failed=False)
        speed_result = mgr.process_speed_run(result)

        assert speed_result.new_target_wpm == 10.0  # doesn't go below 10

    def test_best_wpm_updated(self):
        config = Config()
        mgr = SpeedManager(config)
        mgr.best_wpm = 30.0

        result = make_run(accuracy=0.97, wpm=35.0, completed=True)
        mgr.process_speed_run(result)
        assert mgr.best_wpm == 35.0

    def test_best_wpm_not_updated_on_failure(self):
        config = Config()
        mgr = SpeedManager(config)
        mgr.best_wpm = 30.0

        result = make_run(accuracy=0.93, wpm=35.0, completed=True)
        mgr.process_speed_run(result)
        assert mgr.best_wpm == 30.0


class TestSpeedDiagnostics:
    def test_bottleneck_detection(self):
        config = Config()
        mgr = SpeedManager(config)

        # Create a run with varied per-key reaction times
        result = make_run(
            accuracy=0.97,
            wpm=40.0,
            per_letter_rts={
                "e": [100, 110, 105, 95, 100],  # fast
                "n": [100, 120, 110, 115, 100],  # medium
                "s": [300, 280, 310, 290, 295],  # slow -> bottleneck
            },
        )

        speed_result = mgr.process_speed_run(result)
        assert speed_result.run_median_rt_ms > 0

        bottlenecks = [d for d in speed_result.per_key_diagnostics if d.is_bottleneck]
        assert any(d.letter == "s" for d in bottlenecks)

    def test_no_bottlenecks_when_uniform(self):
        config = Config()
        mgr = SpeedManager(config)

        result = make_run(
            accuracy=0.97,
            wpm=40.0,
            per_letter_rts={
                "e": [100, 110, 105],
                "n": [100, 120, 110],
            },
        )

        speed_result = mgr.process_speed_run(result)
        bottlenecks = [d for d in speed_result.per_key_diagnostics if d.is_bottleneck]
        assert len(bottlenecks) == 0

    def test_diagnostics_sorted_slowest_first(self):
        config = Config()
        mgr = SpeedManager(config)

        result = make_run(
            accuracy=0.97,
            wpm=40.0,
            per_letter_rts={
                "e": [100, 100],
                "n": [200, 200],
                "s": [300, 300],
            },
        )

        speed_result = mgr.process_speed_run(result)
        letters = [d.letter for d in speed_result.per_key_diagnostics]
        assert letters == ["s", "n", "e"]
