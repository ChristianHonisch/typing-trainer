"""Tests for the core typing engine."""

from typing_trainer.config import Config
from typing_trainer.core.engine import TypingEngine
from typing_trainer.models.letter_state import ErrorType, PracticeType, RunMode


def make_engine(
    fail_threshold: float = 0.90,
    mode: RunMode = RunMode.RELEARNING,
    motor_overflow_window_ms: int = 80,
) -> TypingEngine:
    config = Config(
        motor_overflow_window_ms=motor_overflow_window_ms,
        warmup_keystrokes=0,  # disable warmup for unit tests
    )
    engine = TypingEngine(config)
    return engine


class TestBasicTyping:
    def test_correct_typing_full_text(self):
        engine = make_engine()
        engine.start_run("hello", mode=RunMode.RELEARNING)

        for i, char in enumerate("hello"):
            event = engine.process_keystroke(char, 1000 + i * 200)
            assert event is not None
            assert event.error_type == ErrorType.CORRECT

        assert engine.state.is_complete
        assert engine.state.is_finished
        assert engine.state.accuracy == 1.0
        assert engine.state.cognitive_errors == 0

    def test_single_error(self):
        engine = make_engine()
        engine.start_run("abc")

        engine.process_keystroke("a", 1000)  # correct
        engine.process_keystroke("x", 1200)  # error
        engine.process_keystroke("c", 1400)  # correct

        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 1
        assert engine.state.accuracy == 2 / 3

    def test_empty_text(self):
        engine = make_engine()
        engine.start_run("")
        assert engine.state.is_complete
        assert engine.state.is_finished

    def test_accuracy_computation(self):
        engine = make_engine()
        engine.start_run("abcde")

        engine.process_keystroke("a", 1000)  # correct
        engine.process_keystroke("x", 1200)  # error
        engine.process_keystroke("c", 1400)  # correct
        engine.process_keystroke("d", 1600)  # correct
        engine.process_keystroke("e", 1800)  # correct

        assert engine.state.total_scored_keystrokes == 5
        assert engine.state.cognitive_errors == 1
        assert engine.state.accuracy == 4 / 5


class TestFailThreshold:
    """Tests for fail threshold behavior (requires fail_threshold_enabled=True)."""

    def _make_engine(self) -> TypingEngine:
        """Create an engine with fail threshold enabled for testing."""
        config = Config(
            motor_overflow_window_ms=80,
            warmup_keystrokes=0,
            fail_threshold_enabled=True,
        )
        return TypingEngine(config)

    def test_run_fails_when_accuracy_below_threshold(self):
        engine = self._make_engine()
        text = "abcdefghijklmnopqrstuvwxyz"
        engine.start_run(text, fail_threshold=0.90)

        # Type some correct, then accumulate 5 errors with accuracy < 90%.
        # 5 correct + 4 wrong = 55.6%, then 5th error triggers fail check
        for i, char in enumerate(text[:5]):
            engine.process_keystroke(char, 1000 + i * 100)
        # 4 errors (below min_errors=5, no fail yet)
        engine.process_keystroke("0", 1500)
        engine.process_keystroke("1", 1600)
        engine.process_keystroke("2", 1700)
        engine.process_keystroke("3", 1800)
        assert not engine.state.is_failed
        # 5th error: accuracy = 5/10 = 50% < 90% -> fail
        engine.process_keystroke("4", 1900)

        assert engine.state.is_failed
        assert engine.state.is_finished

    def test_run_does_not_fail_below_min_errors(self):
        engine = self._make_engine()
        text = "abcdefghijklmnopqrst"  # 20 chars
        engine.start_run(text, fail_threshold=0.90)

        # 4 errors in 4 keystrokes = 0% accuracy, but only 4 errors
        # (below min_errors=5) so no abort
        engine.process_keystroke("0", 1000)
        engine.process_keystroke("1", 1100)
        engine.process_keystroke("2", 1200)
        engine.process_keystroke("3", 1300)

        assert engine.state.cognitive_errors == 4
        assert not engine.state.is_failed
        assert not engine.state.is_finished

    def test_no_fail_when_accuracy_above_threshold_at_min_errors(self):
        """5 errors but accuracy still >= threshold -> no fail."""
        engine = self._make_engine()
        text = "a" * 100
        engine.start_run(text, fail_threshold=0.90)

        # 50 correct + 5 wrong = 90.9% accuracy >= 90% -> no fail
        for i in range(50):
            engine.process_keystroke("a", 1000 + i * 100)
        wrong_keys = ["v", "w", "x", "y", "z"]
        for i, key in enumerate(wrong_keys):
            engine.process_keystroke(key, 6000 + i * 100)

        assert engine.state.cognitive_errors == 5
        assert not engine.state.is_failed

    def test_progressive_fail_threshold(self):
        """Test that a lower fail threshold (70%) allows more errors."""
        engine = self._make_engine()
        text = "a" * 20
        engine.start_run(text, fail_threshold=0.70)

        # 7 correct + 5 wrong = 58.3% < 70% -> should fail on 5th error
        wrong_keys = ["v", "w", "x", "y", "z"]
        for i in range(7):
            engine.process_keystroke("a", 1000 + i * 100)
        for i in range(4):
            engine.process_keystroke(wrong_keys[i], 1700 + i * 100)
        assert not engine.state.is_failed  # only 4 errors
        engine.process_keystroke(wrong_keys[4], 2100)  # 5th error

        assert engine.state.is_failed

    def test_low_threshold_tolerates_more_errors(self):
        """With a 70% threshold and many correct, 5 errors still pass."""
        engine = self._make_engine()
        text = "a" * 30
        engine.start_run(text, fail_threshold=0.70)

        # 15 correct + 5 wrong = 75% >= 70% -> no fail
        for i in range(15):
            engine.process_keystroke("a", 1000 + i * 100)
        wrong_keys = ["v", "w", "x", "y", "z"]
        for i, key in enumerate(wrong_keys):
            engine.process_keystroke(key, 2500 + i * 100)

        assert engine.state.cognitive_errors == 5
        assert not engine.state.is_failed
        assert engine.state.accuracy == 15 / 20

    def test_disabled_by_default(self):
        """With fail_threshold_enabled=False (default), runs never abort."""
        engine = make_engine()
        text = "abcdefghijklmnopqrstuvwxyz"
        engine.start_run(text, fail_threshold=0.90)

        # 5 correct + 5 errors = 50% accuracy, well below 90%
        for i, char in enumerate(text[:5]):
            engine.process_keystroke(char, 1000 + i * 100)
        for i in range(5):
            engine.process_keystroke(str(i), 1500 + i * 100)

        assert engine.state.cognitive_errors == 5
        assert not engine.state.is_failed
        assert not engine.state.is_finished


class TestMotorOverflow:
    def test_motor_overflow_excluded_from_accuracy(self):
        engine = make_engine(motor_overflow_window_ms=80)
        engine.start_run("abc")

        engine.process_keystroke("a", 1000)  # correct
        engine.process_keystroke("a", 1050)  # motor overflow (same key, <80ms)
        engine.process_keystroke("b", 1200)  # correct
        engine.process_keystroke("c", 1400)  # correct

        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 0
        assert engine.state.motor_overflow_count == 1
        assert engine.state.accuracy == 1.0

    def test_motor_overflow_does_not_advance_cursor(self):
        engine = make_engine(motor_overflow_window_ms=80)
        engine.start_run("ab")

        engine.process_keystroke("a", 1000)  # correct, pos 0 -> 1
        assert engine.state.cursor_position == 1

        engine.process_keystroke("a", 1050)  # overflow, stays at pos 1
        assert engine.state.cursor_position == 1

        engine.process_keystroke("b", 1200)  # correct, pos 1 -> 2
        assert engine.state.cursor_position == 2
        assert engine.state.is_complete


class TestBackspace:
    def test_backspace_disabled_in_relearning(self):
        engine = make_engine()
        engine.start_run("abc", mode=RunMode.RELEARNING)

        engine.process_keystroke("a", 1000)
        assert engine.state.cursor_position == 1

        engine.process_keystroke("\b", 1100)  # backspace
        assert engine.state.cursor_position == 1  # unchanged
        assert engine.state.backspace_count == 1

    def test_backspace_works_in_speed_mode(self):
        engine = make_engine()
        engine.start_run("abc", mode=RunMode.SPEED)

        engine.process_keystroke("a", 1000)
        assert engine.state.cursor_position == 1

        engine.process_keystroke("\b", 1100)
        assert engine.state.cursor_position == 0
        assert engine.state.backspace_count == 1

    def test_backspace_at_start_does_not_go_negative(self):
        engine = make_engine()
        engine.start_run("abc", mode=RunMode.SPEED)

        engine.process_keystroke("\b", 1000)
        assert engine.state.cursor_position == 0

    def test_accuracy_based_on_first_input(self):
        """In speed mode, correcting with backspace doesn't change accuracy."""
        engine = make_engine()
        engine.start_run("abc", mode=RunMode.SPEED)

        engine.process_keystroke("a", 1000)  # correct
        engine.process_keystroke("x", 1200)  # error at pos 1
        engine.process_keystroke("\b", 1300)  # backspace to pos 1
        engine.process_keystroke("b", 1400)  # retype pos 1 (already scored)
        engine.process_keystroke("c", 1600)  # correct

        # Scoring unchanged — accuracy reflects the original error
        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 1
        assert engine.state.accuracy == 2 / 3

    def test_first_inputs_updated_on_retype(self):
        """After backspace + retype, first_inputs reflects the correction."""
        engine = make_engine()
        engine.start_run("abc", mode=RunMode.SPEED)

        engine.process_keystroke("a", 1000)  # correct
        engine.process_keystroke("x", 1200)  # error at pos 1

        # Before backspace: first_inputs[1] has the error
        actual, error_type = engine.state.first_inputs[1]
        assert actual == "x"
        assert error_type == ErrorType.COGNITIVE_ERROR

        engine.process_keystroke("\b", 1300)  # backspace to pos 1
        engine.process_keystroke("b", 1400)  # retype pos 1 correctly

        # After correction: first_inputs[1] reflects the new input
        actual, error_type = engine.state.first_inputs[1]
        assert actual == "b"
        assert error_type == ErrorType.CORRECT

        # But scoring is still based on the original first input
        assert engine.state.cognitive_errors == 1
        assert engine.state.total_scored_keystrokes == 2  # pos 0 and 1

    def test_backspace_retype_multiple_corrections(self):
        """Multiple backspace corrections all update first_inputs."""
        engine = make_engine()
        engine.start_run("abcd", mode=RunMode.SPEED)

        engine.process_keystroke("a", 1000)
        engine.process_keystroke("x", 1200)  # error at pos 1
        engine.process_keystroke("y", 1400)  # error at pos 2
        engine.process_keystroke("\b", 1500)  # back to pos 2
        engine.process_keystroke("\b", 1600)  # back to pos 1
        engine.process_keystroke("b", 1700)  # correct pos 1
        engine.process_keystroke("c", 1800)  # correct pos 2
        engine.process_keystroke("d", 1900)  # correct pos 3

        # Both corrections reflected in first_inputs
        assert engine.state.first_inputs[1] == ("b", ErrorType.CORRECT)
        assert engine.state.first_inputs[2] == ("c", ErrorType.CORRECT)

        # Scoring: 2 errors from original first inputs at pos 1, 2
        assert engine.state.cognitive_errors == 2
        assert engine.state.total_scored_keystrokes == 4


class TestPerLetterStats:
    def test_per_letter_tracking(self):
        engine = make_engine()
        engine.start_run("aaba")

        engine.process_keystroke("a", 1000)
        engine.process_keystroke("a", 1200)
        engine.process_keystroke("b", 1400)
        engine.process_keystroke("a", 1600)

        assert "a" in engine.state.per_letter
        assert "b" in engine.state.per_letter
        assert engine.state.per_letter["a"].total_attempts == 3
        assert engine.state.per_letter["b"].total_attempts == 1

    def test_per_letter_error_rate(self):
        engine = make_engine()
        engine.start_run("aaa")

        engine.process_keystroke("a", 1000)  # correct
        engine.process_keystroke("x", 1200)  # error on 'a'
        engine.process_keystroke("a", 1400)  # correct

        stats = engine.state.per_letter["a"]
        assert stats.total_attempts == 3
        assert stats.cognitive_errors == 1
        assert stats.error_rate == 1 / 3


class TestReactionTime:
    def test_reaction_time_computed(self):
        engine = make_engine()
        engine.start_run("abc")

        e1 = engine.process_keystroke("a", 1000)
        e2 = engine.process_keystroke("b", 1250)
        e3 = engine.process_keystroke("c", 1500)

        assert e1 is not None
        assert e2 is not None
        assert e3 is not None
        assert e1.reaction_time_ms is None  # first keystroke
        assert e2.reaction_time_ms == 250
        assert e3.reaction_time_ms == 250

    def test_per_letter_reaction_times(self):
        engine = make_engine()
        engine.start_run("aba")

        engine.process_keystroke("a", 1000)
        engine.process_keystroke("b", 1200)
        engine.process_keystroke("a", 1500)

        assert engine.state.per_letter["a"].reaction_times == [300]
        assert engine.state.per_letter["b"].reaction_times == [200]


class TestFinishRun:
    def test_finish_run_returns_result(self):
        engine = make_engine()
        engine.start_run("ab", mode=RunMode.RELEARNING)

        engine.process_keystroke("a", 1000)
        engine.process_keystroke("b", 1200)

        result = engine.finish_run()
        assert result.completed is True
        assert result.failed is False
        assert result.total_keystrokes == 2
        assert result.cognitive_errors == 0
        assert result.accuracy == 1.0
        assert result.mode == RunMode.RELEARNING
        assert result.target_text == "ab"
        assert len(result.keystrokes) == 2

    def test_finish_run_on_failure(self):
        config = Config(
            motor_overflow_window_ms=80,
            warmup_keystrokes=0,
            fail_threshold_enabled=True,
        )
        engine = TypingEngine(config)
        text = "a" * 30
        engine.start_run(text, fail_threshold=0.90)

        # 5 correct + 5 wrong = 50% < 90% -> fails on 5th error
        for i in range(5):
            engine.process_keystroke("a", 1000 + i * 100)
        wrong_keys = ["v", "w", "x", "y", "z"]
        for i, key in enumerate(wrong_keys):
            engine.process_keystroke(key, 1500 + i * 100)

        result = engine.finish_run()
        assert result.failed is True
        assert result.completed is False


class TestIgnoreAfterFinished:
    def test_keystrokes_ignored_after_completion(self):
        engine = make_engine()
        engine.start_run("a")

        engine.process_keystroke("a", 1000)
        assert engine.state.is_finished

        result = engine.process_keystroke("b", 1200)
        assert result is None


class TestDeferredStartTime:
    def test_start_time_not_set_before_first_keystroke(self):
        engine = make_engine()
        engine.start_run("abc")

        assert engine.state.start_time is None

    def test_start_time_set_on_first_keystroke(self):
        engine = make_engine()
        engine.start_run("abc")

        engine.process_keystroke("a", 100)
        assert engine.state.start_time is not None


class TestBurstRepeat:
    def test_burst_repeat_excluded_from_accuracy(self):
        """Burst repeat presses don't count toward accuracy or total keystrokes."""
        config = Config(
            motor_overflow_window_ms=80, burst_max_interval_ms=500, warmup_keystrokes=0
        )
        engine = TypingEngine(config)
        # Target: "abcde", user types correct 'a', then holds 'n'
        engine.start_run("abcde")

        engine.process_keystroke("a", 1000)  # correct (pos 0)
        engine.process_keystroke("n", 1100)  # cognitive error at pos 1 (count=1)
        engine.process_keystroke("n", 1200)  # cognitive error at pos 2 (count=2)
        engine.process_keystroke("n", 1300)  # burst_repeat at pos 3 (count=3)
        engine.process_keystroke("n", 1400)  # burst_repeat at pos 3 (count=4)

        # Only 3 scored keystrokes: correct 'a' + 2 cognitive errors before burst
        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 2
        assert engine.state.burst_repeat_count == 2
        # Accuracy: (3 - 2) / 3 = 33.3%
        assert abs(engine.state.accuracy - 1 / 3) < 0.01

    def test_burst_repeat_does_not_advance_cursor(self):
        """Burst repeat presses stay at the same position (like motor overflow)."""
        config = Config(
            motor_overflow_window_ms=80, burst_max_interval_ms=500, warmup_keystrokes=0
        )
        engine = TypingEngine(config)
        engine.start_run("abcde")

        engine.process_keystroke("a", 1000)  # correct, pos 0 -> 1
        engine.process_keystroke("n", 1100)  # error, pos 1 -> 2
        engine.process_keystroke("n", 1200)  # error, pos 2 -> 3
        engine.process_keystroke("n", 1300)  # burst, stays at pos 3
        assert engine.state.cursor_position == 3

        engine.process_keystroke("n", 1400)  # burst, stays at pos 3
        assert engine.state.cursor_position == 3

    def test_burst_count_in_run_result(self):
        """RunResult includes burst_repeat_count."""
        config = Config(
            motor_overflow_window_ms=80, burst_max_interval_ms=500, warmup_keystrokes=0
        )
        engine = TypingEngine(config)
        engine.start_run("abc")

        engine.process_keystroke("x", 1000)  # error (count=1)
        engine.process_keystroke("x", 1100)  # error (count=2)
        engine.process_keystroke("x", 1200)  # burst (count=3)

        result = engine.finish_run()
        assert result.burst_repeat_count == 1
        assert result.cognitive_errors == 2


class TestSwapCount:
    def test_swap_count_in_run_result(self):
        """RunResult includes swap_count for transposition errors."""
        config = Config(warmup_keystrokes=0)
        engine = TypingEngine(config)
        engine.start_run("ensi")

        engine.process_keystroke("n", 1000)  # error: expected 'e', typed 'n'
        engine.process_keystroke("e", 1200)  # error: expected 'n', typed 'e' -> SWAP
        engine.process_keystroke("s", 1400)  # correct
        engine.process_keystroke("i", 1600)  # correct

        result = engine.finish_run()
        assert result.swap_count == 1
        assert result.cognitive_errors == 2  # swaps still count as errors


class TestWarmup:
    def test_warmup_errors_excluded_from_accuracy(self):
        """Errors in the warmup zone don't count toward accuracy."""
        config = Config(warmup_keystrokes=3)
        engine = TypingEngine(config)
        engine.start_run("abcdef")

        # First 3 keystrokes are warmup — all errors
        engine.process_keystroke("x", 1000)  # pos 0: warmup error
        engine.process_keystroke("y", 1200)  # pos 1: warmup error
        engine.process_keystroke("z", 1400)  # pos 2: warmup error
        # Post-warmup: 3 correct
        engine.process_keystroke("d", 1600)  # pos 3: correct (scored)
        engine.process_keystroke("e", 1800)  # pos 4: correct (scored)
        engine.process_keystroke("f", 2000)  # pos 5: correct (scored)

        # Only 3 scored keystrokes (positions 3-5), 0 errors among them
        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 0
        assert engine.state.accuracy == 1.0

    def test_warmup_correct_also_excluded(self):
        """Correct keystrokes in warmup zone are also excluded from scoring."""
        config = Config(warmup_keystrokes=3)
        engine = TypingEngine(config)
        engine.start_run("abcdef")

        # First 3 correct — still warmup
        engine.process_keystroke("a", 1000)
        engine.process_keystroke("b", 1200)
        engine.process_keystroke("c", 1400)
        # Post-warmup: 1 error + 2 correct
        engine.process_keystroke("x", 1600)  # error at pos 3
        engine.process_keystroke("e", 1800)
        engine.process_keystroke("f", 2000)

        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 1
        assert engine.state.accuracy == 2 / 3

    def test_warmup_does_not_affect_per_letter_stats(self):
        """Per-letter stats should exclude warmup keystrokes."""
        config = Config(warmup_keystrokes=2)
        engine = TypingEngine(config)
        engine.start_run("aab")

        engine.process_keystroke("x", 1000)  # pos 0: warmup error on 'a'
        engine.process_keystroke("a", 1200)  # pos 1: warmup correct on 'a'
        engine.process_keystroke("b", 1400)  # pos 2: scored correct on 'b'

        # 'a' appears only in warmup — should have no per-letter entry
        assert "a" not in engine.state.per_letter
        assert "b" in engine.state.per_letter
        assert engine.state.per_letter["b"].total_attempts == 1

    def test_warmup_does_not_prevent_fail_threshold(self):
        """Errors after warmup should still trigger the fail threshold."""
        config = Config(
            warmup_keystrokes=2,
            fail_threshold_min_errors=5,
            fail_threshold_enabled=True,
        )
        engine = TypingEngine(config)
        text = "a" * 20
        engine.start_run(text, fail_threshold=0.90)

        # 2 warmup keystrokes (not scored)
        engine.process_keystroke("a", 1000)
        engine.process_keystroke("a", 1100)
        # 3 correct + 5 errors post-warmup: accuracy = 3/8 = 37.5%
        for i in range(3):
            engine.process_keystroke("a", 1200 + i * 100)
        wrong_keys = ["v", "w", "x", "y", "z"]
        for i, key in enumerate(wrong_keys):
            engine.process_keystroke(key, 1500 + i * 100)

        assert engine.state.cognitive_errors == 5
        assert engine.state.is_failed

    def test_warmup_zero_disables_exclusion(self):
        """warmup_keystrokes=0 means all keystrokes are scored."""
        config = Config(warmup_keystrokes=0)
        engine = TypingEngine(config)
        engine.start_run("abc")

        engine.process_keystroke("x", 1000)  # error at pos 0
        engine.process_keystroke("b", 1200)
        engine.process_keystroke("c", 1400)

        assert engine.state.total_scored_keystrokes == 3
        assert engine.state.cognitive_errors == 1

    def test_warmup_keystrokes_still_logged(self):
        """Warmup keystrokes should still appear in the keystroke log."""
        config = Config(warmup_keystrokes=2)
        engine = TypingEngine(config)
        engine.start_run("abc")

        engine.process_keystroke("x", 1000)  # warmup error
        engine.process_keystroke("b", 1200)  # warmup correct
        engine.process_keystroke("c", 1400)  # scored correct

        result = engine.finish_run()
        assert len(result.keystrokes) == 3  # all 3 logged
        assert result.total_keystrokes == 1  # only 1 scored


class TestCapitalization:
    """Tests for require_capitalization config option."""

    def test_require_capitalization_enabled(self):
        """With require_capitalization=True, case must match."""
        config = Config(warmup_keystrokes=0, require_capitalization=True)
        engine = TypingEngine(config)
        engine.start_run("Haus", mode=RunMode.SPEED)

        engine.process_keystroke("h", 1000)  # wrong: lowercase when uppercase expected
        assert engine.state.cognitive_errors == 1

    def test_require_capitalization_disabled(self):
        """With require_capitalization=False, case is ignored."""
        config = Config(warmup_keystrokes=0, require_capitalization=False)
        engine = TypingEngine(config)
        engine.start_run("Haus", mode=RunMode.SPEED)

        engine.process_keystroke("h", 1000)  # accepted: case ignored
        assert engine.state.cognitive_errors == 0

        engine.process_keystroke("a", 1200)
        engine.process_keystroke("u", 1400)
        engine.process_keystroke("s", 1600)

        assert engine.state.total_scored_keystrokes == 4
        assert engine.state.cognitive_errors == 0
        assert engine.state.accuracy == 1.0

    def test_capitalization_per_letter_normalizes_to_lowercase(self):
        """Per-letter stats track lowercase regardless of target case."""
        config = Config(warmup_keystrokes=0, require_capitalization=True)
        engine = TypingEngine(config)
        engine.start_run("Haus", mode=RunMode.SPEED)

        engine.process_keystroke("H", 1000)
        engine.process_keystroke("a", 1200)
        engine.process_keystroke("u", 1400)
        engine.process_keystroke("s", 1600)

        # Per-letter stats use lowercase keys
        assert "h" in engine.state.per_letter
        assert "H" not in engine.state.per_letter
        assert engine.state.per_letter["h"].total_attempts == 1

    def test_wrong_letter_still_error_when_capitalization_disabled(self):
        """Case is ignored but wrong base letter is still an error."""
        config = Config(warmup_keystrokes=0, require_capitalization=False)
        engine = TypingEngine(config)
        engine.start_run("Haus", mode=RunMode.SPEED)

        engine.process_keystroke("x", 1000)  # wrong letter entirely
        assert engine.state.cognitive_errors == 1
