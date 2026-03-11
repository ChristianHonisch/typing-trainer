"""Tests for database and repository."""

from datetime import datetime

from typing_trainer.models.letter_state import (
    ErrorType,
    LetterState,
    LetterStats,
    PracticeType,
    RunMode,
)
from typing_trainer.models.run_result import KeystrokeEvent, RunResult
from typing_trainer.models.session import Session
from typing_trainer.storage.database import Database
from typing_trainer.storage.repository import Repository


def make_repo(tmp_path) -> Repository:
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    return Repository(db)


class TestSessionCRUD:
    def test_create_and_get_session(self, tmp_path):
        repo = make_repo(tmp_path)
        session = Session(
            start_time=datetime(2026, 1, 1, 10, 0, 0),
            language="de",
            layout="qwertz",
        )
        sid = repo.create_session(session)
        assert sid > 0

        loaded = repo.get_session(sid)
        assert loaded is not None
        assert loaded.language == "de"
        assert loaded.start_time == datetime(2026, 1, 1, 10, 0, 0)

    def test_update_session_end(self, tmp_path):
        repo = make_repo(tmp_path)
        session = Session(start_time=datetime(2026, 1, 1, 10, 0, 0))
        sid = repo.create_session(session)

        end = datetime(2026, 1, 1, 11, 0, 0)
        repo.update_session_end(sid, end)

        loaded = repo.get_session(sid)
        assert loaded is not None
        assert loaded.end_time == end

    def test_get_recent_sessions(self, tmp_path):
        repo = make_repo(tmp_path)
        for i in range(5):
            s = Session(start_time=datetime(2026, 1, i + 1, 10, 0, 0))
            repo.create_session(s)

        recent = repo.get_recent_sessions(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].start_time is not None
        assert recent[1].start_time is not None
        assert recent[0].start_time > recent[1].start_time


class TestRunCRUD:
    def test_save_and_load_run(self, tmp_path):
        repo = make_repo(tmp_path)
        session = Session(start_time=datetime(2026, 1, 1, 10, 0, 0))
        sid = repo.create_session(session)

        run = RunResult(
            start_time=datetime(2026, 1, 1, 10, 1, 0),
            end_time=datetime(2026, 1, 1, 10, 2, 0),
            mode=RunMode.RELEARNING,
            practice_type=PracticeType.RANDOM_STRINGS,
            target_text="abc",
            target_length=3,
            total_keystrokes=3,
            cognitive_errors=1,
            accuracy=2 / 3,
            completed=True,
            failed=False,
            fail_threshold_used=0.90,
        )
        rid = repo.save_run(run, sid)
        assert rid > 0

        runs = repo.get_runs_for_session(sid)
        assert len(runs) == 1
        assert runs[0].mode == RunMode.RELEARNING
        assert runs[0].cognitive_errors == 1
        assert runs[0].completed is True

    def test_save_run_with_keystrokes(self, tmp_path):
        repo = make_repo(tmp_path)
        session = Session(start_time=datetime(2026, 1, 1, 10, 0, 0))
        sid = repo.create_session(session)

        run = RunResult(
            start_time=datetime(2026, 1, 1, 10, 1, 0),
            end_time=datetime(2026, 1, 1, 10, 2, 0),
            mode=RunMode.RELEARNING,
            practice_type=PracticeType.RANDOM_STRINGS,
            target_text="ab",
            target_length=2,
            total_keystrokes=2,
            keystrokes=[
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
            ],
        )
        rid = repo.save_run(run, sid)

        loaded = repo.get_run_with_keystrokes(rid)
        assert loaded is not None
        assert len(loaded.keystrokes) == 2
        assert loaded.keystrokes[0].error_type == ErrorType.CORRECT
        assert loaded.keystrokes[1].error_type == ErrorType.COGNITIVE_ERROR
        assert loaded.keystrokes[1].reaction_time_ms == 200

    def test_get_previous_run(self, tmp_path):
        repo = make_repo(tmp_path)
        session = Session(start_time=datetime(2026, 1, 1, 10, 0, 0))
        sid = repo.create_session(session)

        run1 = RunResult(
            start_time=datetime(2026, 1, 1, 10, 1, 0),
            end_time=datetime(2026, 1, 1, 10, 2, 0),
            mode=RunMode.RELEARNING,
            practice_type=PracticeType.RANDOM_STRINGS,
            target_text="a",
            target_length=1,
            total_keystrokes=1,
            accuracy=1.0,
        )
        rid1 = repo.save_run(run1, sid)

        run2 = RunResult(
            start_time=datetime(2026, 1, 1, 10, 3, 0),
            end_time=datetime(2026, 1, 1, 10, 4, 0),
            mode=RunMode.RELEARNING,
            practice_type=PracticeType.RANDOM_STRINGS,
            target_text="b",
            target_length=1,
            total_keystrokes=1,
            accuracy=0.5,
        )
        rid2 = repo.save_run(run2, sid)

        prev = repo.get_previous_run(sid, rid2)
        assert prev is not None
        assert prev.run_id == rid1


class TestLetterStateCRUD:
    def test_save_and_load_letter_state(self, tmp_path):
        repo = make_repo(tmp_path)
        stats = LetterStats(
            letter="e",
            state=LetterState.CONSOLIDATING,
            stability_score=0.8,
            last_practiced=datetime(2026, 1, 1, 10, 0, 0),
            error_rate_latest=0.03,
            sessions_in_current_state=2,
            sessions_since_introduced=5,
            accuracy_history=[0.97, 0.95, 0.93],
        )
        repo.save_letter_state(stats)

        loaded = repo.get_letter_state("e")
        assert loaded is not None
        assert loaded.state == LetterState.CONSOLIDATING
        assert loaded.stability_score == 0.8
        assert loaded.accuracy_history == [0.97, 0.95, 0.93]

    def test_upsert_letter_state(self, tmp_path):
        repo = make_repo(tmp_path)
        stats = LetterStats(letter="a", state=LetterState.INTRODUCING)
        repo.save_letter_state(stats)

        stats.state = LetterState.CONSOLIDATING
        stats.stability_score = 0.9
        repo.save_letter_state(stats)

        loaded = repo.get_letter_state("a")
        assert loaded is not None
        assert loaded.state == LetterState.CONSOLIDATING
        assert loaded.stability_score == 0.9

    def test_get_all_letter_states(self, tmp_path):
        repo = make_repo(tmp_path)
        repo.save_letter_state(
            LetterStats(letter="e", state=LetterState.STABLE)
        )
        repo.save_letter_state(
            LetterStats(letter="n", state=LetterState.CONSOLIDATING)
        )

        all_states = repo.get_all_letter_states()
        assert len(all_states) == 2
        assert "e" in all_states
        assert "n" in all_states

    def test_save_all_letter_states(self, tmp_path):
        repo = make_repo(tmp_path)
        states = {
            "e": LetterStats(letter="e", state=LetterState.STABLE),
            "n": LetterStats(letter="n", state=LetterState.INTRODUCING),
        }
        repo.save_all_letter_states(states)

        loaded = repo.get_all_letter_states()
        assert len(loaded) == 2


class TestActiveLetterOrder:
    def test_save_and_load_order(self, tmp_path):
        repo = make_repo(tmp_path)
        order = ["e", "n", "i", "s", "r"]
        repo.save_active_letter_order(order)

        loaded = repo.get_active_letter_order()
        assert loaded == order


class TestRollingAccuracy:
    """Tests for get_per_letter_rolling_accuracy."""

    def _insert_keystrokes(self, repo, run_id, keystrokes_data):
        """Insert keystroke records. Each item: (expected_char, error_type)."""
        for i, (expected, error_type) in enumerate(keystrokes_data):
            actual = expected if error_type == "correct" else "x"
            repo.db.conn.execute(
                """INSERT INTO keystrokes
                   (run_id, position, timestamp_ms, expected_char,
                    actual_char, error_type, reaction_time_ms, is_backspace)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, i, 1000 + i * 100, expected, actual, error_type, 100, 0),
            )
        repo.db.conn.commit()

    def _make_run(self, repo, session_id):
        """Create a minimal run and return its ID."""
        run = RunResult(
            start_time=datetime.now(),
            target_text="test",
            target_length=4,
            total_keystrokes=4,
        )
        return repo.save_run(run, session_id)

    def _make_session(self, repo):
        """Create a session and return its ID."""
        session = Session(start_time=datetime.now(), language="de", layout="qwertz")
        return repo.create_session(session)

    def test_all_correct(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes(repo, rid, [
            ("e", "correct"), ("e", "correct"), ("n", "correct"), ("n", "correct"),
        ])
        result = repo.get_per_letter_rolling_accuracy(["e", "n"], window=10)
        assert result["e"] == (1.0, 2)
        assert result["n"] == (1.0, 2)

    def test_mixed_errors(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # 8 correct e's, 2 errors on e -> 80% accuracy
        data = [("e", "correct")] * 8 + [("e", "cognitive_error")] * 2
        self._insert_keystrokes(repo, rid, data)
        result = repo.get_per_letter_rolling_accuracy(["e"], window=20)
        acc, count = result["e"]
        assert count == 10
        assert abs(acc - 0.8) < 0.01

    def test_window_limits_keystrokes(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # 10 keystrokes total, window of 5 -> only last 5 count
        # First 5: all errors. Last 5: all correct.
        data = [("e", "cognitive_error")] * 5 + [("e", "correct")] * 5
        self._insert_keystrokes(repo, rid, data)
        result = repo.get_per_letter_rolling_accuracy(["e"], window=5)
        acc, count = result["e"]
        assert count == 5
        assert acc == 1.0  # only the last 5 (correct) are in the window

    def test_excludes_motor_overflow(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        data = [("e", "correct"), ("e", "motor_overflow"), ("e", "correct")]
        self._insert_keystrokes(repo, rid, data)
        result = repo.get_per_letter_rolling_accuracy(["e"], window=10)
        acc, count = result["e"]
        assert count == 2  # motor overflow excluded
        assert acc == 1.0

    def test_excludes_backspace(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Insert a backspace keystroke manually
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, 0, 1000, "e", "e", "correct", 100, 1),
        )
        self._insert_keystrokes(repo, rid, [("e", "correct")])
        repo.db.conn.commit()
        result = repo.get_per_letter_rolling_accuracy(["e"], window=10)
        acc, count = result["e"]
        assert count == 1  # backspace excluded

    def test_letter_not_in_db(self, tmp_path):
        repo = make_repo(tmp_path)
        result = repo.get_per_letter_rolling_accuracy(["z"], window=10)
        assert result["z"] == (1.0, 0)

    def test_across_multiple_runs(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        self._insert_keystrokes(repo, rid1, [("e", "correct")] * 3)
        self._insert_keystrokes(repo, rid2, [("e", "cognitive_error")] * 2)
        result = repo.get_per_letter_rolling_accuracy(["e"], window=10)
        acc, count = result["e"]
        assert count == 5
        assert abs(acc - 0.6) < 0.01  # 3/5 correct


class TestAnalyticsQueries:
    """Tests for analytics query methods."""

    def _make_session(self, repo):
        session = Session(start_time=datetime.now(), language="de", layout="qwertz")
        return repo.create_session(session)

    def _make_run(
        self, repo, session_id, accuracy=1.0, wpm=30.0, failed=False,
        practice_type=PracticeType.RANDOM_STRINGS,
    ):
        run = RunResult(
            start_time=datetime.now(),
            target_text="test",
            target_length=4,
            total_keystrokes=4,
            accuracy=accuracy,
            wpm=wpm,
            failed=failed,
            practice_type=practice_type,
        )
        return repo.save_run(run, session_id)

    def _insert_keystrokes(self, repo, run_id, keystrokes_data):
        for i, (expected, error_type) in enumerate(keystrokes_data):
            actual = expected if error_type == "correct" else "x"
            repo.db.conn.execute(
                """INSERT INTO keystrokes
                   (run_id, position, timestamp_ms, expected_char,
                    actual_char, error_type, reaction_time_ms, is_backspace)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, i, 1000 + i * 100, expected, actual, error_type, 100, 0),
            )
        repo.db.conn.commit()

    # --- get_all_runs_summary ---

    def test_runs_summary_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_all_runs_summary() == []

    def test_runs_summary_single(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        self._make_run(repo, sid, accuracy=0.95, wpm=35.0, failed=False)
        result = repo.get_all_runs_summary()
        assert len(result) == 1
        assert result[0].accuracy == 0.95
        assert result[0].wpm == 35.0
        assert result[0].failed is False
        assert result[0].practice_type == "random_strings"

    def test_runs_summary_multiple_ordered(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        self._make_run(repo, sid, accuracy=0.90, wpm=25.0, failed=True)
        self._make_run(repo, sid, accuracy=0.98, wpm=40.0, failed=False)
        self._make_run(repo, sid, accuracy=1.00, wpm=45.0, failed=False)
        result = repo.get_all_runs_summary()
        assert len(result) == 3
        assert result[0].accuracy == 0.90
        assert result[0].failed is True
        assert result[1].accuracy == 0.98
        assert result[2].accuracy == 1.00
        # Check ordering by run_id
        assert result[0].run_id < result[1].run_id < result[2].run_id

    def test_runs_summary_practice_type(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        self._make_run(
            repo, sid, practice_type=PracticeType.RANDOM_STRINGS
        )
        self._make_run(
            repo, sid, practice_type=PracticeType.RANDOM_WORDS
        )
        result = repo.get_all_runs_summary()
        assert len(result) == 2
        assert result[0].practice_type == "random_strings"
        assert result[1].practice_type == "random_words"

    # --- get_per_letter_accuracy_series ---

    def test_accuracy_series_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_per_letter_accuracy_series("e") == []

    def test_accuracy_series_single_run(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # 9 correct + 1 error = 90% accuracy
        data = [("e", "correct")] * 9 + [("e", "cognitive_error")]
        self._insert_keystrokes(repo, rid, data)
        series = repo.get_per_letter_accuracy_series("e", window=200)
        assert len(series) == 1
        run_id, acc = series[0]
        assert run_id == rid
        assert abs(acc - 0.9) < 0.01

    def test_accuracy_series_multiple_runs(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        # Run 1: 5 correct for 'e'
        self._insert_keystrokes(repo, rid1, [("e", "correct")] * 5)
        # Run 2: 3 correct + 2 errors for 'e'
        self._insert_keystrokes(repo, rid2, [
            ("e", "correct"), ("e", "correct"), ("e", "correct"),
            ("e", "cognitive_error"), ("e", "cognitive_error"),
        ])
        series = repo.get_per_letter_accuracy_series("e", window=200)
        assert len(series) == 2
        # After run 1: 5/5 = 100%
        assert series[0][0] == rid1
        assert series[0][1] == 1.0
        # After run 2: 8/10 = 80%
        assert series[1][0] == rid2
        assert abs(series[1][1] - 0.8) < 0.01

    def test_accuracy_series_window_applied(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        # Run 1: 5 errors
        self._insert_keystrokes(repo, rid1, [("e", "cognitive_error")] * 5)
        # Run 2: 5 correct
        self._insert_keystrokes(repo, rid2, [("e", "correct")] * 5)
        # With window=5, after run 2 only the 5 correct are in the window
        series = repo.get_per_letter_accuracy_series("e", window=5)
        assert len(series) == 2
        assert series[1][1] == 1.0  # only the 5 correct in window

    def test_accuracy_series_ignores_other_letters(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes(repo, rid, [
            ("e", "correct"), ("n", "cognitive_error"), ("e", "correct"),
        ])
        series = repo.get_per_letter_accuracy_series("e", window=200)
        assert len(series) == 1
        assert series[0][1] == 1.0  # only 'e' keystrokes (both correct)

    # --- get_per_letter_error_rates ---

    def test_error_rates_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_per_letter_error_rates() == {}

    def test_error_rates_single_letter(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes(repo, rid, [
            ("e", "correct"), ("e", "correct"), ("e", "cognitive_error"),
        ])
        result = repo.get_per_letter_error_rates()
        assert "e" in result
        errors, total, rate = result["e"]
        assert errors == 1
        assert total == 3
        assert abs(rate - 1 / 3) < 0.01

    def test_error_rates_multiple_letters(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes(repo, rid, [
            ("e", "correct"), ("e", "correct"),
            ("n", "correct"), ("n", "cognitive_error"),
        ])
        result = repo.get_per_letter_error_rates()
        assert result["e"] == (0, 2, 0.0)
        assert result["n"][0] == 1  # 1 error
        assert result["n"][1] == 2  # 2 total
        assert abs(result["n"][2] - 0.5) < 0.01

    def test_error_rates_excludes_motor_overflow(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes(repo, rid, [
            ("e", "correct"), ("e", "motor_overflow"), ("e", "cognitive_error"),
        ])
        result = repo.get_per_letter_error_rates()
        # motor_overflow excluded: 1 correct + 1 error = 2 total
        errors, total, rate = result["e"]
        assert total == 2
        assert errors == 1
        assert abs(rate - 0.5) < 0.01


    # --- get_per_letter_rt_series ---

    def _insert_keystrokes_with_rt(self, repo, run_id, keystrokes_data):
        """Insert keystroke records with specific RTs.

        Each item: (expected_char, error_type, reaction_time_ms | None).
        """
        for i, (expected, error_type, rt) in enumerate(keystrokes_data):
            actual = expected if error_type == "correct" else "x"
            repo.db.conn.execute(
                """INSERT INTO keystrokes
                   (run_id, position, timestamp_ms, expected_char,
                    actual_char, error_type, reaction_time_ms, is_backspace)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, i, 1000 + i * 100, expected, actual, error_type, rt, 0),
            )
        repo.db.conn.commit()

    def test_rt_series_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_per_letter_rt_series("e") == []

    def test_rt_series_single_run(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes_with_rt(repo, rid, [
            ("e", "correct", 200),
            ("e", "correct", 300),
            ("e", "correct", 400),
        ])
        series = repo.get_per_letter_rt_series("e")
        assert len(series) == 1
        run_id, rts = series[0]
        assert run_id == rid
        assert rts == [200, 300, 400]

    def test_rt_series_multiple_runs(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        self._insert_keystrokes_with_rt(repo, rid1, [
            ("e", "correct", 500),
            ("e", "correct", 500),
        ])
        self._insert_keystrokes_with_rt(repo, rid2, [
            ("e", "correct", 300),
            ("e", "correct", 300),
        ])
        series = repo.get_per_letter_rt_series("e")
        assert len(series) == 2
        assert series[0][0] == rid1
        assert series[0][1] == [500, 500]
        assert series[1][0] == rid2
        assert series[1][1] == [300, 300]

    def test_rt_series_excludes_errors(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes_with_rt(repo, rid, [
            ("e", "correct", 200),
            ("e", "cognitive_error", 9999),  # should be excluded
            ("e", "correct", 400),
        ])
        series = repo.get_per_letter_rt_series("e")
        assert len(series) == 1
        # Only correct keystrokes
        assert series[0][1] == [200, 400]

    def test_rt_series_excludes_null_rt(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes_with_rt(repo, rid, [
            ("e", "correct", None),
            ("e", "correct", 400),
        ])
        series = repo.get_per_letter_rt_series("e")
        assert len(series) == 1
        # Only the non-null RT contributes
        assert series[0][1] == [400]

    def test_rt_series_excludes_high_rt(self, tmp_path):
        """Keystrokes with RT > RT_CAP_MS (2000) are excluded."""
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes_with_rt(repo, rid, [
            ("e", "correct", 300),
            ("e", "correct", 2000),   # exactly at cap — included
            ("e", "correct", 2001),   # just above cap — excluded
            ("e", "correct", 7000),   # far above cap — excluded
            ("e", "correct", 500),
        ])
        series = repo.get_per_letter_rt_series("e")
        assert len(series) == 1
        assert series[0][1] == [300, 2000, 500]

    def test_rt_series_all_above_cap_returns_no_run(self, tmp_path):
        """If all keystrokes for a letter in a run exceed the cap, that run is absent."""
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystrokes_with_rt(repo, rid, [
            ("e", "correct", 5000),
            ("e", "correct", 8000),
        ])
        series = repo.get_per_letter_rt_series("e")
        assert series == []


class TestConfusionPairs:
    """Tests for get_confusion_pairs() and get_swap_pairs()."""

    def _make_session(self, repo):
        session = Session(start_time=datetime.now(), language="de", layout="qwertz")
        return repo.create_session(session)

    def _make_run(self, repo, session_id):
        run = RunResult(
            start_time=datetime.now(),
            target_text="test",
            target_length=4,
            total_keystrokes=4,
            accuracy=0.5,
        )
        return repo.save_run(run, session_id)

    def _insert_keystroke(
        self, repo, run_id, position, expected, actual, error_type="cognitive_error"
    ):
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, position, 1000 + position * 100, expected, actual,
             error_type, 100, 0),
        )
        repo.db.conn.commit()

    # --- get_confusion_pairs ---

    def test_confusion_pairs_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_confusion_pairs() == []

    def test_confusion_pairs_single(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystroke(repo, rid, 0, "n", "e")
        result = repo.get_confusion_pairs()
        assert len(result) == 1
        assert result[0] == ("n", "e", 1)

    def test_confusion_pairs_counts(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # 3x n→e, 1x e→n
        for i in range(3):
            self._insert_keystroke(repo, rid, i, "n", "e")
        self._insert_keystroke(repo, rid, 3, "e", "n")
        result = repo.get_confusion_pairs()
        assert len(result) == 2
        # Sorted by count descending
        assert result[0] == ("n", "e", 3)
        assert result[1] == ("e", "n", 1)

    def test_confusion_pairs_excludes_correct(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystroke(repo, rid, 0, "e", "e", "correct")
        self._insert_keystroke(repo, rid, 1, "n", "e", "cognitive_error")
        result = repo.get_confusion_pairs()
        assert len(result) == 1
        assert result[0] == ("n", "e", 1)

    def test_confusion_pairs_excludes_motor_overflow(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystroke(repo, rid, 0, "e", "e", "motor_overflow")
        result = repo.get_confusion_pairs()
        assert len(result) == 0

    def test_confusion_pairs_multiple_runs(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        self._insert_keystroke(repo, rid1, 0, "n", "e")
        self._insert_keystroke(repo, rid2, 0, "n", "e")
        result = repo.get_confusion_pairs()
        assert len(result) == 1
        assert result[0] == ("n", "e", 2)

    # --- get_swap_pairs ---

    def test_swap_pairs_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_swap_pairs() == []

    def test_swap_pairs_basic(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Swap: expected "e" got "n", then expected "n" got "e"
        self._insert_keystroke(repo, rid, 0, "e", "n")
        self._insert_keystroke(repo, rid, 1, "n", "e")
        result = repo.get_swap_pairs()
        assert len(result) == 1
        # char_a < char_b alphabetically
        assert result[0] == ("e", "n", 1)

    def test_swap_pairs_alphabetical_order(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Swap: expected "s" got "e", then expected "e" got "s"
        self._insert_keystroke(repo, rid, 0, "s", "e")
        self._insert_keystroke(repo, rid, 1, "e", "s")
        result = repo.get_swap_pairs()
        assert len(result) == 1
        assert result[0] == ("e", "s", 1)

    def test_swap_pairs_not_consecutive(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Not a swap: correct keystroke between them
        self._insert_keystroke(repo, rid, 0, "e", "n")
        self._insert_keystroke(repo, rid, 1, "i", "i", "correct")
        self._insert_keystroke(repo, rid, 2, "n", "e")
        result = repo.get_swap_pairs()
        # The LAG window only considers cognitive errors, so
        # position 0 and 2 ARE consecutive in the cognitive-error
        # subsequence — this SHOULD detect the swap
        assert len(result) == 1
        assert result[0] == ("e", "n", 1)

    def test_swap_pairs_cross_run_boundary(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        # Errors in different runs should NOT form a swap
        self._insert_keystroke(repo, rid1, 0, "e", "n")
        self._insert_keystroke(repo, rid2, 0, "n", "e")
        result = repo.get_swap_pairs()
        assert len(result) == 0

    def test_swap_pairs_multiple_swaps(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Two distinct swap events separated by a correct keystroke
        self._insert_keystroke(repo, rid, 0, "e", "n")
        self._insert_keystroke(repo, rid, 1, "n", "e")
        # A non-swap cognitive error to break the chain
        self._insert_keystroke(repo, rid, 2, "s", "r")
        # Second swap
        self._insert_keystroke(repo, rid, 3, "e", "n")
        self._insert_keystroke(repo, rid, 4, "n", "e")
        result = repo.get_swap_pairs()
        assert len(result) == 1
        assert result[0] == ("e", "n", 2)


class TestPositionErrorRate:
    """Tests for get_error_rate_by_position()."""

    def _make_session(self, repo):
        session = Session(start_time=datetime.now(), language="de", layout="qwertz")
        return repo.create_session(session)

    def _make_run(self, repo, session_id):
        run = RunResult(
            start_time=datetime.now(),
            target_text="test",
            target_length=4,
            total_keystrokes=4,
            accuracy=0.5,
        )
        return repo.save_run(run, session_id)

    def _insert_keystroke(
        self, repo, run_id, position, error_type="correct"
    ):
        actual = "e" if error_type == "correct" else "x"
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, position, 1000 + position * 100, "e", actual,
             error_type, 100, 0),
        )
        repo.db.conn.commit()

    def test_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_error_rate_by_position() == []

    def test_single_bucket(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # 4 correct + 1 error in positions 0-4
        for i in range(4):
            self._insert_keystroke(repo, rid, i, "correct")
        self._insert_keystroke(repo, rid, 4, "cognitive_error")
        result = repo.get_error_rate_by_position(bucket_size=5)
        assert len(result) == 1
        bucket_start, errors, total = result[0]
        assert bucket_start == 0
        assert errors == 1
        assert total == 5

    def test_multiple_buckets(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Bucket 0-4: all correct
        for i in range(5):
            self._insert_keystroke(repo, rid, i, "correct")
        # Bucket 5-9: 3 errors
        for i in range(5, 8):
            self._insert_keystroke(repo, rid, i, "cognitive_error")
        for i in range(8, 10):
            self._insert_keystroke(repo, rid, i, "correct")
        result = repo.get_error_rate_by_position(bucket_size=5)
        assert len(result) == 2
        assert result[0] == (0, 0, 5)  # bucket 0-4: 0 errors, 5 total
        assert result[1] == (5, 3, 5)  # bucket 5-9: 3 errors, 5 total

    def test_custom_bucket_size(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        for i in range(10):
            error_type = "cognitive_error" if i >= 8 else "correct"
            self._insert_keystroke(repo, rid, i, error_type)
        # Bucket size 10: one big bucket
        result = repo.get_error_rate_by_position(bucket_size=10)
        assert len(result) == 1
        assert result[0] == (0, 2, 10)

    def test_excludes_backspace(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystroke(repo, rid, 0, "correct")
        # Insert a backspace keystroke directly
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, 0, 1100, "e", "e", "correct", 100, 1),
        )
        repo.db.conn.commit()
        result = repo.get_error_rate_by_position(bucket_size=5)
        assert len(result) == 1
        assert result[0] == (0, 0, 1)  # backspace excluded

    def test_excludes_motor_overflow(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_keystroke(repo, rid, 0, "correct")
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, 0, 1050, "e", "e", "motor_overflow", 50, 0),
        )
        repo.db.conn.commit()
        result = repo.get_error_rate_by_position(bucket_size=5)
        assert len(result) == 1
        assert result[0] == (0, 0, 1)  # motor_overflow excluded

    def test_multiple_runs_aggregate(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        # Run 1: position 0 correct
        self._insert_keystroke(repo, rid1, 0, "correct")
        # Run 2: position 0 error
        self._insert_keystroke(repo, rid2, 0, "cognitive_error")
        result = repo.get_error_rate_by_position(bucket_size=5)
        assert len(result) == 1
        assert result[0] == (0, 1, 2)  # aggregated across runs


class TestBigramErrorRates:
    """Tests for get_bigram_error_rates()."""

    def _make_session(self, repo):
        session = Session(start_time=datetime.now(), language="de", layout="qwertz")
        return repo.create_session(session)

    def _make_run(self, repo, session_id, practice_type=PracticeType.RANDOM_WORDS):
        run = RunResult(
            start_time=datetime.now(),
            target_text="test",
            target_length=4,
            total_keystrokes=4,
            accuracy=0.9,
            practice_type=practice_type,
        )
        return repo.save_run(run, session_id)

    def _insert_seed(self, repo, run_id, char="e"):
        """Insert a correct keystroke at position 0 as the seed for bigrams."""
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, prev_char,
                is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, 0, 900, char, char, "correct", 100, None, 0),
        )
        repo.db.conn.commit()

    def _insert_bigram_keystroke(
        self, repo, run_id, position, prev_char, expected, actual,
        error_type="correct", rt=100,
    ):
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, prev_char,
                is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, position, 1000 + position * 100, expected, actual,
             error_type, rt, prev_char, 0),
        )
        repo.db.conn.commit()

    def test_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_bigram_error_rates() == []

    def test_basic_bigram_error_rate(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        # 8 correct + 2 errors for bigram (e, n), positions 1..10
        # Interleave errors so each error's predecessor is correct
        for i in range(1, 9):
            self._insert_bigram_keystroke(
                repo, rid, i, "e", "n", "n", "correct"
            )
        # Error at pos 9 (prev pos 8 = correct) → counted
        self._insert_bigram_keystroke(
            repo, rid, 9, "e", "n", "x", "cognitive_error"
        )
        # Correct at pos 10 (prev pos 9 = error → excluded from bigram)
        self._insert_bigram_keystroke(
            repo, rid, 10, "e", "n", "n", "correct"
        )
        # Error at pos 11 (prev pos 10 = correct) → counted
        self._insert_bigram_keystroke(
            repo, rid, 11, "e", "n", "x", "cognitive_error"
        )
        # 8 + 1 correct with correct predecessor = 9 correct counted
        # 2 errors with correct predecessor = 2 errors counted
        # pos 10 excluded (prev was error) → 9 + 2 = 11 total? No:
        # pos 10 is correct but prev (pos 9) was error → excluded
        # So: pos 1-8 correct (8), pos 9 error (1), pos 11 error (1)
        # = 8 correct + 2 errors = 10 total
        result = repo.get_bigram_error_rates(min_count=5)
        assert len(result) == 1
        prev_c, exp_c, errors, total, rate = result[0]
        assert prev_c == "e"
        assert exp_c == "n"
        assert errors == 2
        assert total == 10
        assert abs(rate - 0.2) < 0.01

    def test_min_count_filters(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        # Only 3 keystrokes for (e, n) — below min_count=10
        for i in range(1, 4):
            self._insert_bigram_keystroke(
                repo, rid, i, "e", "n", "n", "correct"
            )
        result = repo.get_bigram_error_rates(min_count=10)
        assert len(result) == 0
        # But passes with min_count=3
        result = repo.get_bigram_error_rates(min_count=3)
        assert len(result) == 1

    def test_excludes_motor_overflow(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid, i, "e", "n", "n", "correct"
            )
        self._insert_bigram_keystroke(
            repo, rid, 11, "e", "n", "n", "motor_overflow"
        )
        result = repo.get_bigram_error_rates(min_count=5)
        assert len(result) == 1
        assert result[0][3] == 10  # motor overflow excluded

    def test_excludes_null_prev_char(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        # Insert keystroke with prev_char=None (first char in run)
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, prev_char,
                is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, 0, 1000, "n", "n", "correct", 100, None, 0),
        )
        repo.db.conn.commit()
        result = repo.get_bigram_error_rates(min_count=1)
        assert len(result) == 0

    def test_sorted_by_error_rate_descending(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        # Use two separate runs to avoid cross-contamination between groups
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        # Bigram (e, n): 8 correct + 2 errors = 20% error rate
        self._insert_seed(repo, rid1, "e")
        for i in range(1, 9):
            self._insert_bigram_keystroke(repo, rid1, i, "e", "n", "n", "correct")
        for i in range(9, 11):
            self._insert_bigram_keystroke(repo, rid1, i, "e", "n", "x", "cognitive_error")
        # Bigram (n, e): 5 correct + 5 errors = 50% error rate
        self._insert_seed(repo, rid2, "n")
        for i in range(1, 6):
            self._insert_bigram_keystroke(repo, rid2, i, "n", "e", "e", "correct")
        for i in range(6, 11):
            self._insert_bigram_keystroke(repo, rid2, i, "n", "e", "x", "cognitive_error")
        result = repo.get_bigram_error_rates(min_count=5)
        assert len(result) == 2
        # Higher error rate first
        assert result[0][4] > result[1][4]
        assert result[0][0] == "n"  # (n, e) with 50%
        assert result[1][0] == "e"  # (e, n) with 20%

    def test_excludes_keystrokes_after_errors(self, tmp_path):
        """Keystrokes whose predecessor was an error are excluded."""
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        # pos 1: correct (e->n) — counted
        self._insert_bigram_keystroke(repo, rid, 1, "e", "n", "n", "correct")
        # pos 2: error (n->e typed as x) — counted (prev was correct)
        self._insert_bigram_keystroke(repo, rid, 2, "n", "e", "x", "cognitive_error")
        # pos 3: correct (x->n, but prev was error) — NOT counted
        self._insert_bigram_keystroke(repo, rid, 3, "x", "n", "n", "correct")
        # pos 4: correct (n->e) — counted (prev was correct)
        self._insert_bigram_keystroke(repo, rid, 4, "n", "e", "e", "correct")
        result = repo.get_bigram_error_rates(min_count=1)
        # (e, n): 1 total (pos 1); (n, e): 2 total (pos 2 + 4);
        # (x, n) at pos 3 excluded because pos 2 was error
        bigrams = {(r[0], r[1]): (r[2], r[3]) for r in result}
        assert ("e", "n") in bigrams
        assert bigrams[("e", "n")] == (0, 1)  # 0 errors, 1 total
        assert ("n", "e") in bigrams
        assert bigrams[("n", "e")] == (1, 2)  # 1 error, 2 total
        assert ("x", "n") not in bigrams  # excluded

    def test_practice_type_filter(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid_words = self._make_run(repo, sid, PracticeType.RANDOM_WORDS)
        rid_strings = self._make_run(repo, sid, PracticeType.RANDOM_STRINGS)
        self._insert_seed(repo, rid_words, "e")
        self._insert_seed(repo, rid_strings, "e")
        # 10 keystrokes in random_words
        for i in range(1, 11):
            self._insert_bigram_keystroke(repo, rid_words, i, "e", "n", "n", "correct")
        # 10 keystrokes in random_strings
        for i in range(1, 11):
            self._insert_bigram_keystroke(repo, rid_strings, i, "e", "n", "n", "correct")
        # Without filter: 20 total
        result_all = repo.get_bigram_error_rates(min_count=5)
        assert result_all[0][3] == 20
        # With filter: only 10
        result_words = repo.get_bigram_error_rates(
            min_count=5, practice_types=["random_words"]
        )
        assert result_words[0][3] == 10


class TestBigramTransitionTimes:
    """Tests for get_bigram_transition_times()."""

    def _make_session(self, repo):
        session = Session(start_time=datetime.now(), language="de", layout="qwertz")
        return repo.create_session(session)

    def _make_run(self, repo, session_id, practice_type=PracticeType.RANDOM_WORDS):
        run = RunResult(
            start_time=datetime.now(),
            target_text="test",
            target_length=4,
            total_keystrokes=4,
            accuracy=0.9,
            practice_type=practice_type,
        )
        return repo.save_run(run, session_id)

    def _insert_seed(self, repo, run_id, char="e"):
        """Insert a correct keystroke at position 0 as the seed for bigrams."""
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, prev_char,
                is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, 0, 900, char, char, "correct", 100, None, 0),
        )
        repo.db.conn.commit()

    def _insert_bigram_keystroke(
        self, repo, run_id, position, prev_char, expected, actual,
        error_type="correct", rt=100,
    ):
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, prev_char,
                is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, position, 1000 + position * 100, expected, actual,
             error_type, rt, prev_char, 0),
        )
        repo.db.conn.commit()

    def test_empty(self, tmp_path):
        repo = make_repo(tmp_path)
        assert repo.get_bigram_transition_times() == []

    def test_basic_transition_times(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        # 10 correct keystrokes for bigram (e, n) with varied RTs
        rts = [100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
        for i, rt in enumerate(rts):
            self._insert_bigram_keystroke(
                repo, rid, i + 1, "e", "n", "n", "correct", rt
            )
        result = repo.get_bigram_transition_times(min_count=5)
        assert len(result) == 1
        prev_c, exp_c, rt_values, count = result[0]
        assert prev_c == "e"
        assert exp_c == "n"
        assert count == 10
        assert sorted(rt_values) == rts

    def test_excludes_errors(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid, i, "e", "n", "n", "correct", 100
            )
        # Add some errors — should be excluded
        self._insert_bigram_keystroke(
            repo, rid, 11, "e", "n", "x", "cognitive_error", 500
        )
        result = repo.get_bigram_transition_times(min_count=5)
        assert len(result) == 1
        assert result[0][3] == 10  # error excluded

    def test_excludes_null_rt(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid, i, "e", "n", "n", "correct", 100
            )
        # Add keystroke with null RT
        repo.db.conn.execute(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char,
                actual_char, error_type, reaction_time_ms, prev_char,
                is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, 11, 2000, "n", "n", "correct", None, "e", 0),
        )
        repo.db.conn.commit()
        result = repo.get_bigram_transition_times(min_count=5)
        # The null-RT keystroke is for (e, n) — should be excluded
        found = [r for r in result if r[0] == "e" and r[1] == "n"]
        assert found[0][3] == 10

    def test_min_count_filters(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        for i in range(1, 4):
            self._insert_bigram_keystroke(
                repo, rid, i, "e", "n", "n", "correct", 100
            )
        result = repo.get_bigram_transition_times(min_count=10)
        assert len(result) == 0
        result = repo.get_bigram_transition_times(min_count=3)
        assert len(result) == 1

    def test_sorted_by_median_rt_descending(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        # Use two separate runs to avoid cross-contamination
        rid1 = self._make_run(repo, sid)
        rid2 = self._make_run(repo, sid)
        # Bigram (e, n): fast (100ms)
        self._insert_seed(repo, rid1, "e")
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid1, i, "e", "n", "n", "correct", 100
            )
        # Bigram (n, e): slow (500ms)
        self._insert_seed(repo, rid2, "n")
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid2, i, "n", "e", "e", "correct", 500
            )
        result = repo.get_bigram_transition_times(min_count=5)
        assert len(result) == 2
        # Slowest first
        assert result[0][0] == "n"  # (n, e) with 500ms
        assert result[1][0] == "e"  # (e, n) with 100ms

    def test_excludes_keystrokes_after_errors(self, tmp_path):
        """Keystrokes whose predecessor was an error are excluded from RT."""
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid = self._make_run(repo, sid)
        self._insert_seed(repo, rid, "e")
        # pos 1: correct (e->n) — counted
        self._insert_bigram_keystroke(repo, rid, 1, "e", "n", "n", "correct", 100)
        # pos 2: error (n->e typed as x) — excluded (error, RT query only includes correct)
        self._insert_bigram_keystroke(repo, rid, 2, "n", "e", "x", "cognitive_error", 200)
        # pos 3: correct (x->n) — excluded (prev was error)
        self._insert_bigram_keystroke(repo, rid, 3, "x", "n", "n", "correct", 300)
        # pos 4: correct (n->e) — counted (prev was correct)
        self._insert_bigram_keystroke(repo, rid, 4, "n", "e", "e", "correct", 400)
        result = repo.get_bigram_transition_times(min_count=1)
        bigrams = {(r[0], r[1]): r[2] for r in result}
        assert ("e", "n") in bigrams
        assert bigrams[("e", "n")] == [100]
        assert ("n", "e") in bigrams
        assert bigrams[("n", "e")] == [400]
        assert ("x", "n") not in bigrams  # excluded

    def test_practice_type_filter(self, tmp_path):
        repo = make_repo(tmp_path)
        sid = self._make_session(repo)
        rid_words = self._make_run(repo, sid, PracticeType.RANDOM_WORDS)
        rid_strings = self._make_run(repo, sid, PracticeType.RANDOM_STRINGS)
        self._insert_seed(repo, rid_words, "e")
        self._insert_seed(repo, rid_strings, "e")
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid_words, i, "e", "n", "n", "correct", 100
            )
        for i in range(1, 11):
            self._insert_bigram_keystroke(
                repo, rid_strings, i, "e", "n", "n", "correct", 200
            )
        # Without filter: 20 total
        result_all = repo.get_bigram_transition_times(min_count=5)
        assert result_all[0][3] == 20
        # With filter: only 10
        result_words = repo.get_bigram_transition_times(
            min_count=5, practice_types=["random_words"]
        )
        assert result_words[0][3] == 10


class TestSpeedState:
    def test_default_speed_state(self, tmp_path):
        repo = make_repo(tmp_path)
        target, best = repo.get_speed_state()
        assert target == 30.0
        assert best == 0.0

    def test_save_speed_state(self, tmp_path):
        repo = make_repo(tmp_path)
        repo.save_speed_state(45.0, 42.0)
        target, best = repo.get_speed_state()
        assert target == 45.0
        assert best == 42.0
