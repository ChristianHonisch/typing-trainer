"""Tests for reclassify_all_runs() in the repository.

Validates that derived columns (error_type, reaction_time_ms) and
run-level aggregates are correctly recomputed from raw keystroke data.
"""

from datetime import datetime

from typing_trainer.models.letter_state import (
    ErrorType,
    PracticeType,
    RunMode,
)
from typing_trainer.models.run_result import KeystrokeEvent, RunResult
from typing_trainer.models.session import Session
from typing_trainer.storage.database import Database
from typing_trainer.storage.repository import Repository


def _make_repo(tmp_path) -> Repository:
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    return Repository(db)


def _make_session(repo: Repository) -> int:
    session = Session(start_time=datetime(2026, 1, 1, 10, 0, 0))
    return repo.create_session(session)


def _make_run(
    repo: Repository,
    session_id: int,
    target_text: str,
    keystrokes: list[KeystrokeEvent],
) -> int:
    """Save a run with pre-built keystrokes."""
    total_scored = sum(
        1
        for ks in keystrokes
        if not ks.is_backspace
        and ks.error_type
        not in (ErrorType.MOTOR_OVERFLOW, ErrorType.BURST_REPEAT)
    )
    cognitive_errors = sum(
        1
        for ks in keystrokes
        if ks.error_type == ErrorType.COGNITIVE_ERROR
    )
    motor_overflow_errors = sum(
        1
        for ks in keystrokes
        if ks.error_type == ErrorType.MOTOR_OVERFLOW
    )
    accuracy = (
        (total_scored - cognitive_errors) / total_scored
        if total_scored > 0
        else 1.0
    )

    run = RunResult(
        start_time=datetime(2026, 1, 1, 10, 1, 0),
        end_time=datetime(2026, 1, 1, 10, 2, 0),
        mode=RunMode.RELEARNING,
        practice_type=PracticeType.RANDOM_STRINGS,
        target_text=target_text,
        target_length=len(target_text),
        total_keystrokes=total_scored,
        cognitive_errors=cognitive_errors,
        motor_overflow_errors=motor_overflow_errors,
        accuracy=accuracy,
        completed=True,
        keystrokes=keystrokes,
    )
    return repo.save_run(run, session_id)


def _read_keystrokes(repo: Repository, run_id: int):
    """Read raw keystroke rows from the DB for a run."""
    return repo.db.conn.execute(
        """SELECT id, position, timestamp_ms, expected_char, actual_char,
                  error_type, reaction_time_ms, is_backspace
           FROM keystrokes WHERE run_id = ? ORDER BY id""",
        (run_id,),
    ).fetchall()


def _read_run(repo: Repository, run_id: int):
    """Read the run row from the DB."""
    return repo.db.conn.execute(
        "SELECT * FROM runs WHERE id = ?", (run_id,)
    ).fetchone()


# ── Tests ─────────────────────────────────────────────────────────────


class TestCorrectKeystrokesUnchanged:
    """Correct keystrokes should stay correct after reclassification."""

    def test_all_correct(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1200,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=200,
            ),
            KeystrokeEvent(
                position=2,
                timestamp_ms=1400,
                expected_char="c",
                actual_char="c",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=200,
            ),
        ]
        run_id = _make_run(repo, sid, "abc", keystrokes)

        repo.reclassify_all_runs()

        rows = _read_keystrokes(repo, run_id)
        assert len(rows) == 3
        for row in rows:
            assert row["error_type"] == "correct"

        run = _read_run(repo, run_id)
        assert run["total_keystrokes"] == 3
        assert run["cognitive_errors"] == 0
        assert run["motor_overflow_errors"] == 0
        assert run["accuracy"] == 1.0


class TestMotorOverflowFalsePositive:
    """Motor overflow on legitimate double-letters should be reclassified.

    Historically, fast double-letters (e.g. "ss" typed within 80ms) were
    classified as motor overflow.  After the fix, they should be classified
    as correct (actual==expected).
    """

    def test_fast_double_letter_reclassified_to_correct(self, tmp_path):
        """Double 's' in 'ss' typed within 80ms: was motor overflow, should be correct."""
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        # Write keystrokes with OLD (wrong) classification:
        # Position 0: 's' → correct
        # Position 1: 's' → motor_overflow (wrong! it's a legitimate double-s)
        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="s",
                actual_char="s",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1050,  # 50ms later — within motor overflow window
                expected_char="s",
                actual_char="s",
                error_type=ErrorType.MOTOR_OVERFLOW,  # OLD wrong classification
                reaction_time_ms=50,
            ),
        ]
        run_id = _make_run(repo, sid, "ss", keystrokes)

        # Verify the false positive was written
        rows_before = _read_keystrokes(repo, run_id)
        assert rows_before[1]["error_type"] == "motor_overflow"

        repo.reclassify_all_runs()

        rows_after = _read_keystrokes(repo, run_id)
        assert rows_after[0]["error_type"] == "correct"
        assert rows_after[1]["error_type"] == "correct"  # Fixed!

        run = _read_run(repo, run_id)
        assert run["total_keystrokes"] == 2  # Both now scored
        assert run["cognitive_errors"] == 0
        assert run["motor_overflow_errors"] == 0
        assert run["accuracy"] == 1.0


class TestLegitimateMotorOverflow:
    """True motor overflow (actual != expected, fast repeat) should stay."""

    def test_real_motor_overflow_stays(self, tmp_path):
        """Typing 'a' then 'a' again fast when 'b' was expected."""
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,  # Same position — overflow doesn't advance
                timestamp_ms=1050,
                expected_char="b",
                actual_char="a",
                error_type=ErrorType.MOTOR_OVERFLOW,
                reaction_time_ms=50,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1300,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=300,
            ),
        ]
        run_id = _make_run(repo, sid, "ab", keystrokes)

        repo.reclassify_all_runs()

        rows = _read_keystrokes(repo, run_id)
        assert rows[0]["error_type"] == "correct"
        assert rows[1]["error_type"] == "motor_overflow"  # Stays
        assert rows[2]["error_type"] == "correct"

        run = _read_run(repo, run_id)
        assert run["motor_overflow_errors"] == 1
        assert run["total_keystrokes"] == 2  # overflow excluded
        assert run["cognitive_errors"] == 0


class TestReactionTimeRecomputed:
    """reaction_time_ms should be recomputed from timestamp_ms differences."""

    def test_rt_recomputed_from_timestamps(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        # Write keystrokes with intentionally WRONG reaction times
        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=999,  # Wrong — should be None (first keystroke)
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1300,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=999,  # Wrong — should be 300
            ),
            KeystrokeEvent(
                position=2,
                timestamp_ms=1500,
                expected_char="c",
                actual_char="c",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=999,  # Wrong — should be 200
            ),
        ]
        run_id = _make_run(repo, sid, "abc", keystrokes)

        repo.reclassify_all_runs()

        rows = _read_keystrokes(repo, run_id)
        assert rows[0]["reaction_time_ms"] is None  # First keystroke
        assert rows[1]["reaction_time_ms"] == 300
        assert rows[2]["reaction_time_ms"] == 200

    def test_rt_skips_motor_overflow_for_prev_timestamp(self, tmp_path):
        """Motor overflow doesn't advance cursor, so prev_timestamp should
        NOT be updated.  The RT of the next real keystroke should be measured
        from the last cursor-advancing keystroke."""
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            # Motor overflow at position 1 (doesn't advance)
            KeystrokeEvent(
                position=1,
                timestamp_ms=1050,
                expected_char="b",
                actual_char="a",
                error_type=ErrorType.MOTOR_OVERFLOW,
                reaction_time_ms=50,
            ),
            # Real keystroke at position 1
            KeystrokeEvent(
                position=1,
                timestamp_ms=1400,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=400,
            ),
        ]
        run_id = _make_run(repo, sid, "ab", keystrokes)

        repo.reclassify_all_runs()

        rows = _read_keystrokes(repo, run_id)
        # Motor overflow RT is computed from prev_timestamp (1000) → 50ms
        assert rows[1]["reaction_time_ms"] == 50
        # Next real keystroke: prev_timestamp is still 1000 (overflow didn't update it)
        assert rows[2]["reaction_time_ms"] == 400


class TestCognitiveErrorPreserved:
    """Genuine cognitive errors should remain as cognitive errors."""

    def test_wrong_key_stays_cognitive(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1300,
                expected_char="b",
                actual_char="x",
                error_type=ErrorType.COGNITIVE_ERROR,
                reaction_time_ms=300,
            ),
        ]
        run_id = _make_run(repo, sid, "ab", keystrokes)

        repo.reclassify_all_runs()

        rows = _read_keystrokes(repo, run_id)
        assert rows[1]["error_type"] == "cognitive_error"

        run = _read_run(repo, run_id)
        assert run["cognitive_errors"] == 1
        assert run["total_keystrokes"] == 2
        assert abs(run["accuracy"] - 0.5) < 0.01


class TestRunAggregatesUpdated:
    """Run-level aggregates should reflect reclassified keystrokes."""

    def test_aggregates_update_on_reclassification(self, tmp_path):
        """A motor overflow false positive changes totals when fixed."""
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        # 3 keystrokes for "aab"
        # Second 'a' was mis-classified as motor overflow (fast double letter)
        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1060,  # 60ms, within window
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.MOTOR_OVERFLOW,  # False positive
                reaction_time_ms=60,
            ),
            KeystrokeEvent(
                position=2,
                timestamp_ms=1300,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=240,
            ),
        ]
        run_id = _make_run(repo, sid, "aab", keystrokes)

        # Before reclassification: total_scored=2, overflow=1
        run_before = _read_run(repo, run_id)
        assert run_before["total_keystrokes"] == 2
        assert run_before["motor_overflow_errors"] == 1

        repo.reclassify_all_runs()

        # After: the false positive is now correct → total_scored=3, overflow=0
        run_after = _read_run(repo, run_id)
        assert run_after["total_keystrokes"] == 3
        assert run_after["motor_overflow_errors"] == 0
        assert run_after["cognitive_errors"] == 0
        assert run_after["accuracy"] == 1.0


class TestIdempotency:
    """Running reclassify_all_runs() twice should produce the same result."""

    def test_double_reclassification_is_stable(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1050,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.MOTOR_OVERFLOW,  # False positive
                reaction_time_ms=50,
            ),
            KeystrokeEvent(
                position=2,
                timestamp_ms=1300,
                expected_char="b",
                actual_char="x",
                error_type=ErrorType.COGNITIVE_ERROR,
                reaction_time_ms=250,
            ),
        ]
        run_id = _make_run(repo, sid, "aab", keystrokes)

        repo.reclassify_all_runs()
        rows_first = _read_keystrokes(repo, run_id)
        run_first = _read_run(repo, run_id)

        repo.reclassify_all_runs()
        rows_second = _read_keystrokes(repo, run_id)
        run_second = _read_run(repo, run_id)

        # Keystroke-level: same error_type and reaction_time_ms
        for r1, r2 in zip(rows_first, rows_second, strict=True):
            assert r1["error_type"] == r2["error_type"]
            assert r1["reaction_time_ms"] == r2["reaction_time_ms"]

        # Run-level: same aggregates
        for col in [
            "total_keystrokes",
            "cognitive_errors",
            "motor_overflow_errors",
            "burst_repeat_count",
            "swap_count",
            "accuracy",
        ]:
            assert run_first[col] == run_second[col], f"Mismatch on {col}"


class TestSwapRecomputed:
    """Swap detection should work correctly in reclassification."""

    def test_swap_detected_on_reclassify(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        # Type "ba" when "ab" was expected → swap
        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="b",
                error_type=ErrorType.COGNITIVE_ERROR,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1200,
                expected_char="b",
                actual_char="a",
                error_type=ErrorType.COGNITIVE_ERROR,
                reaction_time_ms=200,
            ),
        ]
        run_id = _make_run(repo, sid, "ab", keystrokes)

        repo.reclassify_all_runs()

        run = _read_run(repo, run_id)
        assert run["swap_count"] == 1
        assert run["cognitive_errors"] == 2  # Swaps still count as errors


class TestMultipleRuns:
    """Reclassification works across multiple runs."""

    def test_multiple_runs_reclassified(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        # Run 1: all correct
        ks1 = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
        ]
        run_id_1 = _make_run(repo, sid, "a", ks1)

        # Run 2: has false positive overflow
        ks2 = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=2000,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=2040,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.MOTOR_OVERFLOW,
                reaction_time_ms=40,
            ),
        ]
        run_id_2 = _make_run(repo, sid, "bb", ks2)

        total = repo.reclassify_all_runs()

        # Total reclassified = 1 (run1) + 2 (run2) = 3 non-backspace keystrokes
        assert total == 3

        # Run 1 unchanged
        run1 = _read_run(repo, run_id_1)
        assert run1["total_keystrokes"] == 1
        assert run1["accuracy"] == 1.0

        # Run 2: false positive fixed
        run2 = _read_run(repo, run_id_2)
        assert run2["total_keystrokes"] == 2
        assert run2["motor_overflow_errors"] == 0
        assert run2["accuracy"] == 1.0


class TestBackspaceSkipped:
    """Backspace keystrokes should be skipped during reclassification."""

    def test_backspace_not_reclassified(self, tmp_path):
        repo = _make_repo(tmp_path)
        sid = _make_session(repo)

        keystrokes = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1200,
                expected_char="b",
                actual_char="x",
                error_type=ErrorType.COGNITIVE_ERROR,
                reaction_time_ms=200,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1400,
                expected_char="b",
                actual_char="\b",
                error_type=ErrorType.CORRECT,
                is_backspace=True,
            ),
            KeystrokeEvent(
                position=1,
                timestamp_ms=1600,
                expected_char="b",
                actual_char="b",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=400,
            ),
        ]
        run_id = _make_run(repo, sid, "ab", keystrokes)

        n = repo.reclassify_all_runs()

        # 3 non-backspace keystrokes reclassified, 1 backspace skipped
        assert n == 3

        rows = _read_keystrokes(repo, run_id)
        # Backspace row should be unchanged
        bs_row = [r for r in rows if r["is_backspace"]]
        assert len(bs_row) == 1


class TestMigrationGuard:
    """v6 migration should run once and not repeat."""

    def test_migration_runs_once(self, tmp_path):
        """Schema version is updated to 6 after reclassification."""
        db = Database(str(tmp_path / "test.db"))
        db.initialize()

        version = db.conn.execute(
            "SELECT version FROM schema_version"
        ).fetchone()
        assert version[0] == 6

    def test_second_initialize_skips_reclassification(self, tmp_path):
        """Re-initializing the same DB should not re-run reclassification."""
        db_path = str(tmp_path / "test.db")
        db1 = Database(db_path)
        db1.initialize()

        # Insert a run with a known error_type
        repo = Repository(db1)
        sid = _make_session(repo)
        ks = [
            KeystrokeEvent(
                position=0,
                timestamp_ms=1000,
                expected_char="a",
                actual_char="a",
                error_type=ErrorType.CORRECT,
                reaction_time_ms=None,
            ),
        ]
        _make_run(repo, sid, "a", ks)
        db1.close()

        # Re-open — should NOT re-run reclassification (version already 6)
        db2 = Database(db_path)
        db2.initialize()

        version = db2.conn.execute(
            "SELECT version FROM schema_version"
        ).fetchone()
        assert version[0] == 6
        db2.close()
