"""Tests for error classification logic."""

from typing_trainer.core.error_classifier import ErrorClassifier
from typing_trainer.models.letter_state import ErrorType


class TestCorrectKeystrokes:
    def test_correct_single_keystroke(self):
        classifier = ErrorClassifier()
        result = classifier.classify("a", "a", 1000, 0)
        assert result.error_type == ErrorType.CORRECT
        assert not result.is_same_key

    def test_correct_sequence(self):
        classifier = ErrorClassifier()
        r1 = classifier.classify("h", "h", 1000, 0)
        r2 = classifier.classify("e", "e", 1200, 1)
        r3 = classifier.classify("l", "l", 1400, 2)
        assert r1.error_type == ErrorType.CORRECT
        assert r2.error_type == ErrorType.CORRECT
        assert r3.error_type == ErrorType.CORRECT


class TestCognitiveErrors:
    def test_wrong_key(self):
        classifier = ErrorClassifier()
        result = classifier.classify("a", "s", 1000, 0)
        assert result.error_type == ErrorType.COGNITIVE_ERROR

    def test_wrong_key_not_same_as_previous(self):
        classifier = ErrorClassifier()
        classifier.classify("h", "h", 1000, 0)
        result = classifier.classify("e", "r", 1200, 1)
        assert result.error_type == ErrorType.COGNITIVE_ERROR
        assert not result.is_same_key


class TestMotorOverflow:
    def test_same_key_within_window(self):
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        # First press: correct 'l'
        classifier.classify("l", "l", 1000, 0)
        # Second press: same key within 80ms -> motor overflow
        result = classifier.classify("o", "l", 1050, 1)
        assert result.error_type == ErrorType.MOTOR_OVERFLOW
        assert result.is_same_key
        assert result.same_key_interval_ms == 50

    def test_same_key_outside_window(self):
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        classifier.classify("l", "l", 1000, 0)
        # Same key but after 100ms -> cognitive error (wrong key)
        result = classifier.classify("o", "l", 1100, 1)
        assert result.error_type == ErrorType.COGNITIVE_ERROR
        assert result.is_same_key
        assert result.same_key_interval_ms == 100

    def test_same_key_correct_within_window(self):
        """Same key pressed twice within window, and second press is also
        the expected character (e.g., 'll' in 'hello').

        This is a legitimate double-letter, NOT motor overflow.  Fast
        typists regularly type double-letters within the overflow window.
        """
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        classifier.classify("l", "l", 1000, 0)
        # Second 'l' is expected AND within window -> CORRECT (not overflow)
        result = classifier.classify("l", "l", 1050, 1)
        assert result.error_type == ErrorType.CORRECT

    def test_same_key_wrong_within_window(self):
        """Same key pressed twice within window, but second press is NOT
        the expected character -> motor overflow."""
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        classifier.classify("l", "l", 1000, 0)
        # Second 'l' when 'o' was expected, within window -> overflow
        result = classifier.classify("o", "l", 1050, 1)
        assert result.error_type == ErrorType.MOTOR_OVERFLOW

    def test_same_key_correct_outside_window(self):
        """Same key pressed twice outside window, and it's correct (e.g., 'll')."""
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        classifier.classify("l", "l", 1000, 0)
        result = classifier.classify("l", "l", 1200, 1)
        assert result.error_type == ErrorType.CORRECT
        assert result.is_same_key

    def test_motor_overflow_does_not_update_prev(self):
        """After a motor overflow, the 'previous' keystroke should still be
        the one before the overflow, not the overflow itself."""
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        # 'l' at t=1000
        classifier.classify("l", "l", 1000, 0)
        # overflow 'l' at t=1050 (should NOT update prev)
        classifier.classify("o", "l", 1050, 1)
        # Now type 'l' again at t=1200 — interval from t=1000, not t=1050
        result = classifier.classify("l", "l", 1200, 2)
        assert result.is_same_key
        assert result.same_key_interval_ms == 200  # 1200 - 1000
        assert result.error_type == ErrorType.CORRECT


class TestSameKeyLogging:
    def test_same_key_intervals_logged(self):
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        classifier.classify("l", "l", 1000, 0)
        # Second 'l' expected and actual match -> correct, not overflow
        classifier.classify("l", "l", 1050, 1)
        classifier.classify("l", "l", 1200, 2)  # not overflow (outside window)

        assert len(classifier.same_key_intervals) == 2
        assert classifier.same_key_intervals[0].interval_ms == 50
        # Correct double-letter: NOT classified as overflow
        assert classifier.same_key_intervals[0].classified_as_overflow is False
        assert classifier.same_key_intervals[1].interval_ms == 150  # 1200 - 1050
        assert classifier.same_key_intervals[1].classified_as_overflow is False

    def test_same_key_intervals_overflow_logged(self):
        """When same key is wrong (actual != expected), overflow IS logged."""
        classifier = ErrorClassifier(motor_overflow_window_ms=80)
        classifier.classify("l", "l", 1000, 0)
        # Second 'l' when 'o' expected -> overflow
        classifier.classify("o", "l", 1050, 1)

        assert len(classifier.same_key_intervals) == 1
        assert classifier.same_key_intervals[0].interval_ms == 50
        assert classifier.same_key_intervals[0].classified_as_overflow is True

    def test_reset_preserves_intervals(self):
        classifier = ErrorClassifier()
        classifier.classify("a", "a", 1000, 0)
        classifier.classify("a", "a", 1050, 1)
        assert len(classifier.same_key_intervals) == 1

        classifier.reset()
        assert len(classifier.same_key_intervals) == 1  # preserved
        # But prev tracking is reset
        result = classifier.classify("a", "a", 2000, 0)
        assert not result.is_same_key  # no previous to compare to


class TestBurstRepeat:
    """Tests for burst repeat detection (key held/stuck)."""

    def test_burst_detected_after_three_same_key_errors(self):
        """3+ consecutive same wrong key: errors before count 3 kept, rest BURST_REPEAT."""
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        # Target: "abcd", user types "aaaa"
        r0 = classifier.classify("a", "a", 1000, 0)   # correct (count=1)
        r1 = classifier.classify("b", "a", 1100, 1)   # cognitive error (count=2, not burst yet)
        r2 = classifier.classify("c", "a", 1200, 2)   # count=3, burst confirmed -> BURST_REPEAT
        r3 = classifier.classify("d", "a", 1300, 3)   # burst continues

        assert r0.error_type == ErrorType.CORRECT
        assert r1.error_type == ErrorType.COGNITIVE_ERROR  # before burst confirmed
        assert r2.error_type == ErrorType.BURST_REPEAT
        assert r3.error_type == ErrorType.BURST_REPEAT

    def test_burst_not_detected_for_two_same_key(self):
        """Two consecutive same wrong key is NOT a burst (need 3+)."""
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        r0 = classifier.classify("a", "x", 1000, 0)   # error
        r1 = classifier.classify("b", "x", 1100, 1)   # error, same key but only 2

        assert r0.error_type == ErrorType.COGNITIVE_ERROR
        assert r1.error_type == ErrorType.COGNITIVE_ERROR

    def test_burst_broken_by_different_key(self):
        """Burst resets when a different key is pressed."""
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        classifier.classify("a", "x", 1000, 0)   # error
        classifier.classify("b", "x", 1100, 1)   # error
        r2 = classifier.classify("c", "y", 1200, 2)   # different key breaks burst
        r3 = classifier.classify("d", "y", 1300, 3)   # new sequence, only 2

        assert r2.error_type == ErrorType.COGNITIVE_ERROR
        assert r3.error_type == ErrorType.COGNITIVE_ERROR

    def test_burst_broken_by_slow_interval(self):
        """Burst resets when interval exceeds burst_max_interval_ms."""
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        r0 = classifier.classify("a", "x", 1000, 0)   # error
        r1 = classifier.classify("b", "x", 1100, 1)   # error
        r2 = classifier.classify("c", "x", 1700, 2)   # same key but 600ms gap

        assert r0.error_type == ErrorType.COGNITIVE_ERROR
        assert r1.error_type == ErrorType.COGNITIVE_ERROR
        assert r2.error_type == ErrorType.COGNITIVE_ERROR  # gap broke the burst

    def test_burst_with_correct_presses_interleaved(self):
        """Burst with some correct presses mixed in (target has same char).

        Like Run 37: target='issei', user types 'iiiii'.
        pos 0: target='i', typed='i' -> correct
        pos 1: target='s', typed='i' -> error (kept, first error)
        pos 2: target='s', typed='i' -> burst starts (3rd same key, 2/3 errors >= 50%)
        pos 3: target='e', typed='i' -> burst continues
        pos 4: target='i', typed='i' -> correct (not reclassified)
        """
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        r0 = classifier.classify("i", "i", 1000, 0)   # correct
        r1 = classifier.classify("s", "i", 1133, 1)   # error (kept)
        r2 = classifier.classify("s", "i", 1291, 2)   # burst repeat
        r3 = classifier.classify("e", "i", 1438, 3)   # burst repeat
        r4 = classifier.classify("i", "i", 1607, 4)   # correct (target IS 'i')

        assert r0.error_type == ErrorType.CORRECT
        assert r1.error_type == ErrorType.COGNITIVE_ERROR  # first error kept
        assert r2.error_type == ErrorType.BURST_REPEAT
        assert r3.error_type == ErrorType.BURST_REPEAT
        assert r4.error_type == ErrorType.CORRECT  # correct stays correct

    def test_burst_with_motor_overflow_mixed_in(self):
        """Burst that includes motor overflow (like Run 40).

        Motor overflow presses contribute to the burst count but are
        already classified as MOTOR_OVERFLOW.
        """
        classifier = ErrorClassifier(
            motor_overflow_window_ms=80, burst_max_interval_ms=500
        )
        # Simulate Run 40: correct 'n', then key held
        r0 = classifier.classify("n", "n", 1000, 0)   # correct
        r1 = classifier.classify("i", "n", 1500, 1)   # error (first, kept)
        r2 = classifier.classify("e", "n", 1547, 2)   # motor overflow (47ms)
        r3 = classifier.classify("e", "n", 1579, 2)   # motor overflow (79ms)
        r4 = classifier.classify("e", "n", 1610, 2)   # cognitive -> burst (110ms, >80ms)

        assert r0.error_type == ErrorType.CORRECT
        assert r1.error_type == ErrorType.COGNITIVE_ERROR  # first error kept
        assert r2.error_type == ErrorType.MOTOR_OVERFLOW
        assert r3.error_type == ErrorType.MOTOR_OVERFLOW
        # At this point burst count is 5 (correct + error + 2 motor + this one)
        # Error count: 4 (error + 2 motor + this one), 4/5 = 80% >= 50%
        assert r4.error_type == ErrorType.BURST_REPEAT

    def test_burst_not_detected_when_mostly_correct(self):
        """If >50% of same-key presses are correct, it's not a burst.

        e.g., target='aaa', user types 'aaa' — all correct, not a burst.
        """
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        r0 = classifier.classify("a", "a", 1000, 0)  # correct
        r1 = classifier.classify("a", "a", 1100, 1)  # correct
        r2 = classifier.classify("a", "a", 1200, 2)  # correct

        assert r0.error_type == ErrorType.CORRECT
        assert r1.error_type == ErrorType.CORRECT
        assert r2.error_type == ErrorType.CORRECT

    def test_burst_reset_clears_state(self):
        """After reset(), burst tracking starts fresh."""
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        classifier.classify("a", "x", 1000, 0)
        classifier.classify("b", "x", 1100, 1)

        classifier.reset()

        # New run: 2 same-key errors should not be a burst (no history)
        r0 = classifier.classify("c", "x", 2000, 0)
        r1 = classifier.classify("d", "x", 2100, 1)
        assert r0.error_type == ErrorType.COGNITIVE_ERROR
        assert r1.error_type == ErrorType.COGNITIVE_ERROR

    def test_all_errors_burst(self):
        """4 consecutive wrong same-key presses: first 2 kept, last 2 reclassified."""
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        r0 = classifier.classify("a", "n", 1000, 0)   # error (count=1)
        r1 = classifier.classify("b", "n", 1100, 1)   # error (count=2, not burst yet)
        r2 = classifier.classify("c", "n", 1200, 2)   # count=3, burst confirmed
        r3 = classifier.classify("d", "n", 1300, 3)   # burst continues

        assert r0.error_type == ErrorType.COGNITIVE_ERROR  # before burst
        assert r1.error_type == ErrorType.COGNITIVE_ERROR  # before burst
        assert r2.error_type == ErrorType.BURST_REPEAT     # 3rd, burst confirmed
        assert r3.error_type == ErrorType.BURST_REPEAT


class TestSwapDetection:
    """Tests for swap/transposition error detection."""

    def test_swap_detected(self):
        """Two consecutive cognitive errors with transposed chars."""
        classifier = ErrorClassifier()
        # Target: "en", typed: "ne"
        r0 = classifier.classify("e", "n", 1000, 0)
        r1 = classifier.classify("n", "e", 1200, 1)

        assert r0.error_type == ErrorType.COGNITIVE_ERROR
        assert r1.error_type == ErrorType.COGNITIVE_ERROR
        assert r1.is_swap is True
        assert classifier.swap_count == 1

    def test_swap_not_detected_for_non_transposition(self):
        """Two consecutive errors that are NOT transpositions."""
        classifier = ErrorClassifier()
        r0 = classifier.classify("e", "n", 1000, 0)
        r1 = classifier.classify("s", "i", 1200, 1)

        assert r1.is_swap is False
        assert classifier.swap_count == 0

    def test_swap_not_detected_after_correct(self):
        """A correct keystroke breaks the swap pattern."""
        classifier = ErrorClassifier()
        classifier.classify("e", "n", 1000, 0)  # error
        classifier.classify("n", "n", 1200, 1)  # correct
        r2 = classifier.classify("e", "n", 1400, 2)  # error

        assert r2.is_swap is False
        assert classifier.swap_count == 0

    def test_multiple_swaps_counted(self):
        """Multiple swap events in a single run."""
        classifier = ErrorClassifier()
        # First swap
        classifier.classify("e", "n", 1000, 0)
        classifier.classify("n", "e", 1200, 1)
        # Correct keystroke
        classifier.classify("s", "s", 1400, 2)
        # Second swap
        classifier.classify("i", "s", 1600, 3)
        classifier.classify("s", "i", 1800, 4)

        assert classifier.swap_count == 2

    def test_swap_reset(self):
        """Reset clears swap count and swap tracking state."""
        classifier = ErrorClassifier()
        classifier.classify("e", "n", 1000, 0)
        classifier.classify("n", "e", 1200, 1)
        assert classifier.swap_count == 1

        classifier.reset()
        assert classifier.swap_count == 0

    def test_swap_not_detected_for_burst(self):
        """Burst repeat keystrokes should NOT trigger swap detection.

        If a burst is detected, those keystrokes are BURST_REPEAT, not
        COGNITIVE_ERROR, so they shouldn't be considered for swaps.
        """
        classifier = ErrorClassifier(burst_max_interval_ms=500)
        # 3 same key 'n' -> burst
        classifier.classify("a", "n", 1000, 0)   # error (kept)
        classifier.classify("b", "n", 1100, 1)   # error
        r2 = classifier.classify("c", "n", 1200, 2)   # burst_repeat
        assert r2.error_type == ErrorType.BURST_REPEAT
        # After burst, type something that would be a "swap" of n and c
        r3 = classifier.classify("n", "c", 1400, 3)  # error, different key

        # Should NOT be a swap because previous was burst_repeat, not cognitive_error
        assert r3.is_swap is False
        assert classifier.swap_count == 0
