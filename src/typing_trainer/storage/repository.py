"""Data access layer for sessions, runs, keystrokes, and letter states.

All reads/writes go through this module. The rest of the app should not
touch sqlite directly.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from typing_trainer.core.error_classifier import ErrorClassifier
from typing_trainer.core.stats import RT_CAP_MS
from typing_trainer.models.letter_state import (
    ErrorType,
    LetterState,
    LetterStats,
    PracticeType,
    RunMode,
)
from typing_trainer.models.run_result import (
    KeystrokeEvent,
    PerLetterResult,
    RunResult,
)
from typing_trainer.models.session import Session
from typing_trainer.storage.database import Database

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


@dataclass
class RunSummary:
    """Lightweight run data for analytics charts."""

    run_id: int
    accuracy: float
    wpm: float
    failed: bool
    practice_type: str = ""


def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime(_DATETIME_FMT)


def _str_to_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.strptime(s, _DATETIME_FMT)


class Repository:
    """CRUD operations for all persistent data."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Sessions ──────────────────────────────────────────────────────

    def create_session(self, session: Session) -> int:
        """Insert a new session. Returns the session ID."""
        cursor = self.db.conn.execute(
            """INSERT INTO sessions (start_time, end_time, language, layout)
               VALUES (?, ?, ?, ?)""",
            (
                _dt_to_str(session.start_time),
                _dt_to_str(session.end_time),
                session.language,
                session.layout,
            ),
        )
        self.db.conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("Failed to insert session: no lastrowid returned")
        session.session_id = cursor.lastrowid
        return cursor.lastrowid

    def update_session_end(self, session_id: int, end_time: datetime) -> None:
        """Update the end time of a session."""
        self.db.conn.execute(
            "UPDATE sessions SET end_time = ? WHERE id = ?",
            (_dt_to_str(end_time), session_id),
        )
        self.db.conn.commit()

    def get_session(self, session_id: int) -> Session | None:
        """Load a session by ID (without runs)."""
        row = self.db.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return Session(
            session_id=row["id"],
            start_time=_str_to_dt(row["start_time"]),
            end_time=_str_to_dt(row["end_time"]),
            language=row["language"],
            layout=row["layout"],
        )

    def get_recent_sessions(self, limit: int = 10) -> list[Session]:
        """Get the most recent sessions, ordered by start time descending."""
        rows = self.db.conn.execute(
            "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ?", (limit,)
        ).fetchall()
        sessions = []
        for row in rows:
            s = Session(
                session_id=row["id"],
                start_time=_str_to_dt(row["start_time"]),
                end_time=_str_to_dt(row["end_time"]),
                language=row["language"],
                layout=row["layout"],
            )
            # Load runs for this session
            s.runs = self.get_runs_for_session(row["id"])
            sessions.append(s)
        return sessions

    # ── Runs ──────────────────────────────────────────────────────────

    def save_run(self, run: RunResult, session_id: int) -> int:
        """Insert a completed run. Returns the run ID."""
        cursor = self.db.conn.execute(
            """INSERT INTO runs
               (session_id, start_time, end_time, mode, practice_type,
                target_text, target_length, total_keystrokes, cognitive_errors,
                motor_overflow_errors, burst_repeat_count, backspace_count,
                swap_count, accuracy, wpm,
                completed, failed, fail_threshold_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                _dt_to_str(run.start_time),
                _dt_to_str(run.end_time),
                run.mode.value,
                run.practice_type.value,
                run.target_text,
                run.target_length,
                run.total_keystrokes,
                run.cognitive_errors,
                run.motor_overflow_errors,
                run.burst_repeat_count,
                run.backspace_count,
                run.swap_count,
                run.accuracy,
                run.wpm,
                int(run.completed),
                int(run.failed),
                run.fail_threshold_used,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Failed to insert run: no lastrowid returned")
        run_id = cursor.lastrowid
        run.run_id = run_id
        run.session_id = session_id

        # Save keystrokes in batches
        if run.keystrokes:
            self._save_keystrokes(run_id, run.keystrokes)

        self.db.conn.commit()
        return run_id

    def _save_keystrokes(self, run_id: int, keystrokes: list[KeystrokeEvent]) -> None:
        """Batch-insert keystrokes for a run.

        The ``prev_char`` column is set to NULL for all new keystrokes.
        It was previously used for bigram analysis but is now superseded
        by a self-join approach.  The column is retained in the schema
        for historical data compatibility.
        """
        rows = [
            (
                run_id,
                ks.position,
                ks.timestamp_ms,
                ks.expected_char,
                ks.actual_char,
                ks.error_type.value,
                ks.reaction_time_ms,
                None,  # prev_char — deprecated, use self-join
                int(ks.is_backspace),
            )
            for ks in keystrokes
        ]
        self.db.conn.executemany(
            """INSERT INTO keystrokes
               (run_id, position, timestamp_ms, expected_char, actual_char,
                error_type, reaction_time_ms, prev_char, is_backspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def get_runs_for_session(self, session_id: int) -> list[RunResult]:
        """Load all runs for a session (without keystroke details)."""
        rows = self.db.conn.execute(
            "SELECT * FROM runs WHERE session_id = ? ORDER BY start_time",
            (session_id,),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def get_run_with_keystrokes(self, run_id: int) -> RunResult | None:
        """Load a run including all keystroke data."""
        row = self.db.conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None

        run = self._row_to_run(row)

        # Load keystrokes
        ks_rows = self.db.conn.execute(
            "SELECT * FROM keystrokes WHERE run_id = ? ORDER BY timestamp_ms",
            (run_id,),
        ).fetchall()
        run.keystrokes = [
            KeystrokeEvent(
                position=ks["position"],
                timestamp_ms=ks["timestamp_ms"],
                expected_char=ks["expected_char"],
                actual_char=ks["actual_char"],
                error_type=ErrorType(ks["error_type"]),
                reaction_time_ms=ks["reaction_time_ms"],
                prev_char=ks["prev_char"],
                is_backspace=bool(ks["is_backspace"]),
            )
            for ks in ks_rows
        ]
        return run

    def get_previous_run(self, session_id: int, before_run_id: int) -> RunResult | None:
        """Get the run immediately before the given run in the same session."""
        row = self.db.conn.execute(
            """SELECT * FROM runs
               WHERE session_id = ? AND id < ?
               ORDER BY id DESC LIMIT 1""",
            (session_id, before_run_id),
        ).fetchone()
        if row is None:
            # Try the last run from any previous session
            row = self.db.conn.execute(
                """SELECT * FROM runs
                   WHERE session_id < ?
                   ORDER BY id DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def _row_to_run(self, row) -> RunResult:
        return RunResult(
            run_id=row["id"],
            session_id=row["session_id"],
            start_time=_str_to_dt(row["start_time"]),
            end_time=_str_to_dt(row["end_time"]),
            mode=RunMode(row["mode"]),
            practice_type=PracticeType(row["practice_type"]),
            target_text=row["target_text"],
            target_length=row["target_length"],
            total_keystrokes=row["total_keystrokes"],
            cognitive_errors=row["cognitive_errors"],
            motor_overflow_errors=row["motor_overflow_errors"],
            burst_repeat_count=row["burst_repeat_count"],
            backspace_count=row["backspace_count"],
            swap_count=row["swap_count"],
            accuracy=row["accuracy"],
            wpm=row["wpm"],
            completed=bool(row["completed"]),
            failed=bool(row["failed"]),
            fail_threshold_used=row["fail_threshold_used"],
        )

    # ── Letter States ─────────────────────────────────────────────────

    def _upsert_letter_state(self, stats: LetterStats) -> None:
        """Execute the upsert SQL for a single letter state (no commit)."""
        self.db.conn.execute(
            """INSERT INTO letter_states
               (letter, state, stability_score, last_practiced,
                error_rate_last_session, sessions_in_current_state,
                sessions_since_introduced, accuracy_history,
                keystrokes_at_introduction,
                mastery_score, mastery_qualifying_keystrokes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(letter) DO UPDATE SET
                state = excluded.state,
                stability_score = excluded.stability_score,
                last_practiced = excluded.last_practiced,
                error_rate_last_session = excluded.error_rate_last_session,
                sessions_in_current_state = excluded.sessions_in_current_state,
                sessions_since_introduced = excluded.sessions_since_introduced,
                accuracy_history = excluded.accuracy_history,
                keystrokes_at_introduction = excluded.keystrokes_at_introduction,
                mastery_score = excluded.mastery_score,
                mastery_qualifying_keystrokes = excluded.mastery_qualifying_keystrokes""",
            (
                stats.letter,
                stats.state.value,
                stats.stability_score,
                _dt_to_str(stats.last_practiced),
                stats.error_rate_latest,
                stats.sessions_in_current_state,
                stats.sessions_since_introduced,
                json.dumps(stats.accuracy_history),
                stats.keystrokes_at_introduction,
                stats.mastery_score,
                stats.mastery_qualifying_keystrokes,
            ),
        )

    def save_letter_state(self, stats: LetterStats) -> None:
        """Upsert a letter's state."""
        self._upsert_letter_state(stats)
        self.db.conn.commit()

    def save_all_letter_states(self, states: dict[str, LetterStats]) -> None:
        """Save all letter states in a single transaction."""
        for stats in states.values():
            self._upsert_letter_state(stats)
        self.db.conn.commit()

    def get_all_letter_states(self) -> dict[str, LetterStats]:
        """Load all letter states."""
        rows = self.db.conn.execute("SELECT * FROM letter_states").fetchall()
        result: dict[str, LetterStats] = {}
        for row in rows:
            result[row["letter"]] = self._row_to_letter_stats(row)
        return result

    def get_letter_state(self, letter: str) -> LetterStats | None:
        """Load a single letter's state."""
        row = self.db.conn.execute(
            "SELECT * FROM letter_states WHERE letter = ?", (letter,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_letter_stats(row)

    @staticmethod
    def _row_to_letter_stats(row: sqlite3.Row) -> LetterStats:
        """Convert a DB row to a LetterStats object."""
        return LetterStats(
            letter=row["letter"],
            state=LetterState(row["state"]),
            stability_score=row["stability_score"],
            last_practiced=_str_to_dt(row["last_practiced"]),
            error_rate_latest=row["error_rate_last_session"],
            sessions_in_current_state=row["sessions_in_current_state"],
            sessions_since_introduced=row["sessions_since_introduced"],
            accuracy_history=json.loads(row["accuracy_history"]),
            keystrokes_at_introduction=row["keystrokes_at_introduction"],
            mastery_score=row["mastery_score"],
            mastery_qualifying_keystrokes=row["mastery_qualifying_keystrokes"],
        )

    # ── Active Letter Order ───────────────────────────────────────────

    def save_active_letter_order(self, letters: list[str]) -> None:
        """Save the current active letter introduction order."""
        self.db.conn.execute("DELETE FROM active_letter_order")
        for i, letter in enumerate(letters):
            self.db.conn.execute(
                "INSERT INTO active_letter_order (position, letter) VALUES (?, ?)",
                (i, letter),
            )
        self.db.conn.commit()

    def get_active_letter_order(self) -> list[str]:
        """Load the active letter introduction order."""
        rows = self.db.conn.execute(
            "SELECT letter FROM active_letter_order ORDER BY position"
        ).fetchall()
        return [row["letter"] for row in rows]

    # ── Speed State ───────────────────────────────────────────────────

    def get_speed_state(self) -> tuple[float, float]:
        """Get (target_wpm, best_wpm). Creates default if not exists."""
        row = self.db.conn.execute(
            "SELECT target_wpm, best_wpm FROM speed_state WHERE id = 1"
        ).fetchone()
        if row is None:
            self.db.conn.execute(
                "INSERT INTO speed_state (id, target_wpm, best_wpm) VALUES (1, 30.0, 0.0)"
            )
            self.db.conn.commit()
            return (30.0, 0.0)
        return (row["target_wpm"], row["best_wpm"])

    def save_speed_state(self, target_wpm: float, best_wpm: float) -> None:
        """Update speed training state."""
        self.db.conn.execute(
            """INSERT INTO speed_state (id, target_wpm, best_wpm)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                target_wpm = excluded.target_wpm,
                best_wpm = excluded.best_wpm""",
            (target_wpm, best_wpm),
        )
        self.db.conn.commit()

    # ── Aggregation Queries ───────────────────────────────────────────

    def get_session_count(self) -> int:
        """Get total number of sessions."""
        row = self.db.conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()
        return row["c"]

    def get_last_n_sessions_accuracy(self, n: int) -> list[float]:
        """Get aggregate accuracy for the last N sessions (most recent first)."""
        sessions = self.get_recent_sessions(limit=n)
        return [s.aggregate_accuracy for s in sessions]

    def get_training_time_today(self) -> int:
        """Total active training seconds today (sum of run durations).

        Counts only runs with both start_time and end_time, where
        start_time falls on today (local time).
        """
        row = self.db.conn.execute(
            """SELECT COALESCE(SUM(
                 (julianday(end_time) - julianday(start_time)) * 86400
               ), 0) AS total_s
               FROM runs
               WHERE date(start_time) = date('now', 'localtime')
                 AND end_time IS NOT NULL"""
        ).fetchone()
        return int(row["total_s"])

    def get_total_runs(self) -> int:
        """Get total number of runs across all sessions."""
        row = self.db.conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()
        return row["c"]

    def get_runs_today(self) -> int:
        """Get number of runs started today (local time).

        Stored ``start_time`` values are naive local-time datetimes
        (from ``datetime.now()``), so we compare ``date(start_time)``
        directly against ``date('now', 'localtime')``.
        """
        row = self.db.conn.execute(
            """SELECT COUNT(*) AS c FROM runs
               WHERE date(start_time) = date('now', 'localtime')"""
        ).fetchone()
        return row["c"]

    def get_keystrokes_today(self) -> int:
        """Get total cognitive keystrokes from runs started today."""
        row = self.db.conn.execute(
            """SELECT COALESCE(SUM(total_keystrokes), 0) AS total
               FROM runs
               WHERE date(start_time) = date('now', 'localtime')"""
        ).fetchone()
        return row["total"]

    def get_total_training_time(self) -> int:
        """Total active training seconds across all runs (sum of run durations)."""
        row = self.db.conn.execute(
            """SELECT COALESCE(SUM(
                 (julianday(end_time) - julianday(start_time)) * 86400
               ), 0) AS total_s
               FROM runs
               WHERE end_time IS NOT NULL"""
        ).fetchone()
        return int(row["total_s"])

    def get_elapsed_time_today(self) -> int:
        """Wall-clock elapsed seconds for sessions with runs today.

        For each session that has at least one run today, computes the
        span from the session's start_time to either its end_time or
        the latest run end_time today.
        """
        row = self.db.conn.execute(
            """SELECT COALESCE(SUM(span), 0) AS total_s
               FROM (
                   SELECT
                       (julianday(
                           COALESCE(s.end_time, MAX(r.end_time))
                       ) - julianday(s.start_time)) * 86400 AS span
                   FROM sessions s
                   JOIN runs r ON r.session_id = s.id
                    WHERE date(r.start_time) = date('now', 'localtime')
                     AND r.end_time IS NOT NULL
                   GROUP BY s.id
               )"""
        ).fetchone()
        return max(0, int(row["total_s"]))

    def get_total_elapsed_time(self) -> int:
        """Total wall-clock elapsed seconds across all sessions.

        For each session, computes the span from start_time to end_time.
        Sessions without end_time are excluded.
        """
        row = self.db.conn.execute(
            """SELECT COALESCE(SUM(
                 (julianday(end_time) - julianday(start_time)) * 86400
               ), 0) AS total_s
               FROM sessions
               WHERE end_time IS NOT NULL"""
        ).fetchone()
        return max(0, int(row["total_s"]))

    def get_total_keystrokes_relearning(self) -> int:
        """Get total cognitive keystrokes from Learn Keys runs only.

        Learn Keys = ``mode='relearning'`` AND ``practice_type='random_strings'``.
        Fix Keys runs (``practice_type='fix_keys'``) are excluded because
        only Learn Keys training counts toward letter unlocking.
        """
        row = self.db.conn.execute(
            """SELECT COALESCE(SUM(total_keystrokes), 0) AS total
               FROM runs
               WHERE mode = 'relearning'
                 AND practice_type = 'random_strings'"""
        ).fetchone()
        return row["total"]

    def _query_recent_keystrokes(
        self,
        letter: str,
        window: int,
        *,
        learn_keys_only: bool = False,
    ) -> list[sqlite3.Row]:
        """Fetch the most recent *window* cognitive keystrokes for *letter*.

        Returns rows newest-first (``ORDER BY id DESC``).

        Only scored keystrokes are included (``error_type IN
        ('correct', 'cognitive_error')``, ``is_backspace = 0``).

        Args:
            learn_keys_only: When ``True``, restrict to keystrokes from
                Learn Keys runs (``mode='relearning'`` AND
                ``practice_type='random_strings'``).
        """
        if learn_keys_only:
            return self.db.conn.execute(
                """SELECT k.error_type FROM keystrokes k
                   JOIN runs r ON k.run_id = r.id
                   WHERE k.expected_char = ?
                     AND k.error_type IN ('correct', 'cognitive_error')
                     AND k.is_backspace = 0
                     AND r.mode = 'relearning'
                     AND r.practice_type = 'random_strings'
                   ORDER BY k.id DESC
                   LIMIT ?""",
                (letter, window),
            ).fetchall()
        return self.db.conn.execute(
            """SELECT error_type FROM keystrokes
               WHERE expected_char = ?
                 AND error_type IN ('correct', 'cognitive_error')
                 AND is_backspace = 0
               ORDER BY id DESC
               LIMIT ?""",
            (letter, window),
        ).fetchall()

    def get_per_letter_rolling_accuracy(
        self,
        letters: list[str],
        window: int = 200,
        *,
        learn_keys_only: bool = False,
    ) -> dict[str, tuple[float, int]]:
        """Get rolling accuracy for each letter over the last *window* keystrokes.

        Only counts first-input keystrokes (not motor overflow or backspace).
        Returns ``{letter: (accuracy, total_keystrokes_in_window)}``.

        Args:
            learn_keys_only: When ``True``, restrict to keystrokes from
                Learn Keys runs (``mode='relearning'`` AND
                ``practice_type='random_strings'``).  Fix Keys, Build
                Speed, and Smooth Pairs runs are excluded.
        """
        result: dict[str, tuple[float, int]] = {}
        for letter in letters:
            rows = self._query_recent_keystrokes(
                letter,
                window,
                learn_keys_only=learn_keys_only,
            )

            total = len(rows)
            if total == 0:
                result[letter] = (1.0, 0)
                continue

            errors = sum(1 for r in rows if r["error_type"] == "cognitive_error")
            accuracy = (total - errors) / total
            result[letter] = (accuracy, total)

        return result

    def get_per_letter_error_window(
        self,
        letters: list[str],
        window: int = 200,
        *,
        learn_keys_only: bool = False,
    ) -> dict[str, list[bool]]:
        """Get the error/correct sequence for the last *window* keystrokes per letter.

        Returns a dict mapping each letter to a list of booleans where
        ``True`` = cognitive error and ``False`` = correct.  The list is
        in **chronological** order (index 0 = oldest, last index = newest).

        Only cognitive keystrokes are included (``error_type IN
        ('correct', 'cognitive_error')``, ``is_backspace = 0``).
        Letters with no data are omitted from the result.

        Args:
            learn_keys_only: When ``True``, restrict to keystrokes from
                Learn Keys runs (``mode='relearning'`` AND
                ``practice_type='random_strings'``).
        """
        result: dict[str, list[bool]] = {}
        for letter in letters:
            rows = self._query_recent_keystrokes(
                letter,
                window,
                learn_keys_only=learn_keys_only,
            )

            if not rows:
                continue

            # rows are newest-first; reverse to oldest-first
            result[letter] = [
                r["error_type"] == "cognitive_error" for r in reversed(rows)
            ]

        return result

    def get_per_letter_run_counts(self) -> dict[str, int]:
        """Get the number of distinct runs each letter appeared in.

        Only counts cognitive keystrokes (correct + cognitive_error).
        Returns ``{letter: run_count}``.
        """
        rows = self.db.conn.execute(
            """SELECT expected_char AS letter,
                      COUNT(DISTINCT run_id) AS run_count
               FROM keystrokes
               WHERE error_type IN ('correct', 'cognitive_error')
                 AND is_backspace = 0
               GROUP BY expected_char"""
        ).fetchall()
        return {row["letter"]: row["run_count"] for row in rows}

    def get_total_keystrokes_since(self, since_run_id: int | None = None) -> int:
        """Get total cognitive keystrokes since a given run ID (inclusive).

        If since_run_id is None, returns total across all runs.
        Only counts scored keystrokes (from runs table, not individual keystrokes).
        """
        if since_run_id is not None:
            row = self.db.conn.execute(
                """SELECT COALESCE(SUM(total_keystrokes), 0) as total
                   FROM runs WHERE id >= ?""",
                (since_run_id,),
            ).fetchone()
        else:
            row = self.db.conn.execute(
                "SELECT COALESCE(SUM(total_keystrokes), 0) as total FROM runs"
            ).fetchone()
        return row["total"]

    def get_total_keystrokes_all(self) -> int:
        """Get total cognitive keystrokes across all runs."""
        row = self.db.conn.execute(
            "SELECT COALESCE(SUM(total_keystrokes), 0) as total FROM runs"
        ).fetchone()
        return row["total"]

    # ── Analytics Queries ─────────────────────────────────────────────

    def get_all_runs_summary(self) -> list[RunSummary]:
        """Get lightweight summary of all runs for charting.

        Returns list ordered by run ID (chronological).
        """
        rows = self.db.conn.execute(
            "SELECT id, accuracy, wpm, failed, practice_type FROM runs ORDER BY id"
        ).fetchall()
        return [
            RunSummary(
                run_id=row["id"],
                accuracy=row["accuracy"],
                wpm=row["wpm"],
                failed=bool(row["failed"]),
                practice_type=row["practice_type"] or "",
            )
            for row in rows
        ]

    def get_letter_count_at_runs(self) -> list[tuple[int, int]]:
        """Get the number of unlocked letters at the end of each run.

        Uses ``keystrokes_at_introduction`` from ``letter_states`` to
        determine when each letter was introduced, and the cumulative
        keystroke total from ``runs`` to determine how many letters were
        active at the end of each run.

        Returns:
            List of ``(run_number, active_letter_count)`` ordered
            chronologically.  ``run_number`` is 1-based.
        """
        # Introduction thresholds per letter (sorted ascending)
        intro_rows = self.db.conn.execute(
            """SELECT keystrokes_at_introduction
               FROM letter_states
               ORDER BY keystrokes_at_introduction"""
        ).fetchall()
        thresholds = [row["keystrokes_at_introduction"] for row in intro_rows]

        if not thresholds:
            return []

        # Per-run keystroke totals with mode/practice_type, ordered chronologically.
        # We need mode and practice_type to build a Learn Keys-only
        # cumulative for threshold comparison, while keeping the run
        # number aligned with ALL runs for the x-axis.
        run_rows = self.db.conn.execute(
            "SELECT total_keystrokes, mode, practice_type FROM runs ORDER BY id"
        ).fetchall()

        if not run_rows:
            return []

        # Build Learn Keys-only cumulative for threshold comparison.
        # Only runs with mode='relearning' AND practice_type='random_strings'
        # contribute, because keystrokes_at_introduction is recorded using
        # the Learn Keys-only total.
        cumulative_learn = 0
        result: list[tuple[int, int]] = []
        threshold_idx = 0
        n_thresholds = len(thresholds)

        for run_num_0, row in enumerate(run_rows):
            if row["mode"] == "relearning" and row["practice_type"] == "random_strings":
                cumulative_learn += row["total_keystrokes"]
            # Advance threshold pointer using Learn Keys cumulative
            while (
                threshold_idx < n_thresholds
                and thresholds[threshold_idx] <= cumulative_learn
            ):
                threshold_idx += 1
            result.append((run_num_0 + 1, threshold_idx))

        return result

    def get_per_letter_keystroke_errors(self, letter: str) -> list[bool]:
        """Get the full chronological error sequence for a letter.

        Returns a list of booleans (``True`` = cognitive error,
        ``False`` = correct) covering every cognitive keystroke for the
        letter, in chronological order.  No limit — returns all data.
        """
        rows = self.db.conn.execute(
            """SELECT error_type FROM keystrokes
               WHERE expected_char = ?
                 AND error_type IN ('correct', 'cognitive_error')
                 AND is_backspace = 0
               ORDER BY id""",
            (letter,),
        ).fetchall()
        return [r["error_type"] == "cognitive_error" for r in rows]

    def get_per_letter_keystroke_rts(self, letter: str) -> list[int]:
        """Get all reaction times for correct keystrokes of a letter.

        Returns chronologically ordered RT values in milliseconds,
        capped at 2000 ms.  Only correct keystrokes with a valid
        ``reaction_time_ms`` are included.
        """
        rows = self.db.conn.execute(
            """SELECT reaction_time_ms FROM keystrokes
               WHERE expected_char = ?
                 AND error_type = 'correct'
                 AND is_backspace = 0
                 AND reaction_time_ms IS NOT NULL
                 AND reaction_time_ms <= 2000
               ORDER BY id""",
            (letter,),
        ).fetchall()
        return [r["reaction_time_ms"] for r in rows]

    def get_per_letter_rt_stats(
        self, letters: list[str], window: int = 400
    ) -> dict[str, tuple[float, float, int]]:
        """Get RT statistics for each letter over the last *window* correct keystrokes.

        Returns ``{letter: (median_rt_ms, cv, count)}``.
        Only correct keystrokes with valid ``reaction_time_ms <= 2000``
        are included.  Letters with no data return ``(0.0, 0.0, 0)``.
        """
        result: dict[str, tuple[float, float, int]] = {}
        for letter in letters:
            rows = self.db.conn.execute(
                """SELECT reaction_time_ms FROM keystrokes
                   WHERE expected_char = ?
                     AND error_type = 'correct'
                     AND is_backspace = 0
                     AND reaction_time_ms IS NOT NULL
                     AND reaction_time_ms <= 2000
                   ORDER BY id DESC
                   LIMIT ?""",
                (letter, window),
            ).fetchall()

            count = len(rows)
            if count == 0:
                result[letter] = (0.0, 0.0, 0)
                continue

            rts = [r["reaction_time_ms"] for r in rows]
            sorted_rts = sorted(rts)
            median = float(sorted_rts[count // 2])
            mean = sum(rts) / count
            if mean > 0:
                variance = sum((v - mean) ** 2 for v in rts) / count
                cv = variance**0.5 / mean
            else:
                cv = 0.0

            result[letter] = (median, cv, count)

        return result

    def get_per_letter_accuracy_series(
        self, letter: str, window: int = 200
    ) -> list[tuple[int, float]]:
        """Compute rolling accuracy for a letter at each run boundary.

        Uses a sliding window of the last ``window`` cognitive keystrokes
        for the given letter.  Returns one data point per run where the
        letter appeared: ``(run_id, rolling_accuracy)``.

        Efficient: single DB query + single-pass sliding window.
        """
        rows = self.db.conn.execute(
            """SELECT run_id, error_type FROM keystrokes
               WHERE expected_char = ?
                 AND error_type IN ('correct', 'cognitive_error')
                 AND is_backspace = 0
               ORDER BY id""",
            (letter,),
        ).fetchall()

        if not rows:
            return []

        buf: deque[bool] = deque()  # True = correct
        errors_in_buf = 0
        # dict preserves insertion order; last write per run_id wins
        series: dict[int, float] = {}

        for row in rows:
            is_correct: bool = row["error_type"] == "correct"
            buf.append(is_correct)
            if not is_correct:
                errors_in_buf += 1

            while len(buf) > window:
                old = buf.popleft()
                if not old:
                    errors_in_buf -= 1

            run_id: int = row["run_id"]
            series[run_id] = (len(buf) - errors_in_buf) / len(buf)

        return list(series.items())

    def get_per_letter_error_rates(
        self,
        *,
        last_n: int | None = None,
    ) -> dict[str, tuple[int, int, float]]:
        """Get aggregate error rate per letter across all keystrokes.

        Args:
            last_n: If set, only consider the most recent *last_n*
                cognitive keystrokes (by ``id DESC``).

        Returns dict of ``letter -> (errors, total, error_rate)``.
        Only includes cognitive keystrokes (correct + cognitive_error).
        """
        if last_n is not None:
            rows = self.db.conn.execute(
                """WITH recent AS (
                       SELECT expected_char, error_type
                       FROM keystrokes
                       WHERE error_type IN ('correct', 'cognitive_error')
                         AND is_backspace = 0
                       ORDER BY id DESC
                       LIMIT ?
                   )
                   SELECT expected_char AS letter,
                          COUNT(*) AS total,
                          SUM(CASE WHEN error_type = 'cognitive_error'
                              THEN 1 ELSE 0 END) AS errors
                   FROM recent
                   GROUP BY expected_char
                   ORDER BY expected_char""",
                (last_n,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """SELECT expected_char AS letter,
                          COUNT(*) AS total,
                          SUM(CASE WHEN error_type = 'cognitive_error'
                              THEN 1 ELSE 0 END) AS errors
                   FROM keystrokes
                   WHERE error_type IN ('correct', 'cognitive_error')
                     AND is_backspace = 0
                   GROUP BY expected_char
                   ORDER BY expected_char"""
            ).fetchall()

        result: dict[str, tuple[int, int, float]] = {}
        for row in rows:
            total: int = row["total"]
            errors: int = row["errors"]
            rate = errors / total if total > 0 else 0.0
            result[row["letter"]] = (errors, total, rate)
        return result

    def get_per_letter_rt_series(self, letter: str) -> list[tuple[int, list[int]]]:
        """Get raw reaction times per run for a letter.

        Returns ``(run_id, [rt_ms, ...])`` for each run where the letter
        was typed correctly with a recorded reaction time.  Keystrokes
        with ``reaction_time_ms > RT_CAP_MS`` (2 s) are excluded as they
        represent pauses rather than motor responses.  The caller is
        responsible for aggregation (e.g. trimmed mean).
        """
        rows = self.db.conn.execute(
            """SELECT run_id, reaction_time_ms
               FROM keystrokes
               WHERE expected_char = ?
                 AND error_type = 'correct'
                 AND reaction_time_ms IS NOT NULL
                 AND reaction_time_ms <= ?
                 AND is_backspace = 0
               ORDER BY run_id, position""",
            (letter, RT_CAP_MS),
        ).fetchall()

        # Group by run_id preserving order
        result: list[tuple[int, list[int]]] = []
        current_run: int | None = None
        current_rts: list[int] = []
        for row in rows:
            run_id: int = row["run_id"]
            rt: int = row["reaction_time_ms"]
            if run_id != current_run:
                if current_run is not None:
                    result.append((current_run, current_rts))
                current_run = run_id
                current_rts = []
            current_rts.append(rt)
        if current_run is not None:
            result.append((current_run, current_rts))
        return result

    def get_confusion_pairs(
        self,
        *,
        last_n: int | None = None,
    ) -> list[tuple[str, str, int]]:
        """Get counts of each (expected, actual) confusion pair.

        Only includes cognitive errors (not motor overflow, burst repeat,
        or backspace corrections).

        Args:
            last_n: If set, only consider the most recent *last_n*
                cognitive keystrokes (correct + cognitive_error, by
                ``id DESC``).  Confusion pairs are then counted only
                within that window.

        Returns:
            List of ``(expected_char, actual_char, count)`` sorted by
            count descending.
        """
        if last_n is not None:
            rows = self.db.conn.execute(
                """WITH recent AS (
                       SELECT expected_char, actual_char, error_type
                       FROM keystrokes
                       WHERE error_type IN ('correct', 'cognitive_error')
                         AND is_backspace = 0
                       ORDER BY id DESC
                       LIMIT ?
                   )
                   SELECT expected_char, actual_char, COUNT(*) AS cnt
                   FROM recent
                   WHERE error_type = 'cognitive_error'
                   GROUP BY expected_char, actual_char
                   ORDER BY cnt DESC""",
                (last_n,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """SELECT expected_char, actual_char, COUNT(*) AS cnt
                   FROM keystrokes
                   WHERE error_type = 'cognitive_error'
                     AND is_backspace = 0
                   GROUP BY expected_char, actual_char
                   ORDER BY cnt DESC"""
            ).fetchall()

        return [(row["expected_char"], row["actual_char"], row["cnt"]) for row in rows]

    def get_swap_pairs(
        self,
        *,
        last_n: int | None = None,
    ) -> list[tuple[str, str, int]]:
        """Get counts of transposition (swap) errors.

        A swap is two consecutive cognitive errors within the same run
        where ``expected₁ == actual₂`` and ``actual₁ == expected₂``
        (i.e. the two characters were typed in the wrong order).

        Args:
            last_n: If set, only consider the most recent *last_n*
                cognitive keystrokes (correct + cognitive_error, by
                ``id DESC``).  Swaps are detected only within that
                window.

        Returns:
            List of ``(char_a, char_b, count)`` where ``char_a < char_b``
            alphabetically, sorted by count descending.  Each swap event
            is counted once (not twice for each keystroke in the pair).
        """
        if last_n is not None:
            # When filtering by last_n, we need id and run_id to detect
            # consecutive pairs within the same run.
            # LAG() is applied over ALL keystrokes (not just errors) to
            # ensure "consecutive" means truly adjacent in the typing
            # stream, then we filter for pairs where both are cognitive
            # errors.
            rows = self.db.conn.execute(
                """WITH recent AS (
                       SELECT id, run_id, expected_char, actual_char, error_type
                       FROM keystrokes
                       WHERE error_type IN ('correct', 'cognitive_error')
                         AND is_backspace = 0
                       ORDER BY id DESC
                       LIMIT ?
                   ),
                   with_lag AS (
                       SELECT id, run_id, expected_char, actual_char, error_type,
                              LAG(expected_char) OVER (
                                  PARTITION BY run_id ORDER BY id
                              ) AS prev_expected,
                              LAG(actual_char) OVER (
                                  PARTITION BY run_id ORDER BY id
                              ) AS prev_actual,
                              LAG(error_type) OVER (
                                  PARTITION BY run_id ORDER BY id
                              ) AS prev_error_type
                       FROM recent
                   )
                   SELECT
                       CASE WHEN expected_char < actual_char
                            THEN expected_char ELSE actual_char END AS char_a,
                       CASE WHEN expected_char < actual_char
                            THEN actual_char ELSE expected_char END AS char_b,
                       COUNT(*) AS cnt
                   FROM with_lag
                   WHERE error_type = 'cognitive_error'
                     AND prev_error_type = 'cognitive_error'
                     AND expected_char = prev_actual
                     AND actual_char = prev_expected
                   GROUP BY char_a, char_b
                   ORDER BY cnt DESC""",
                (last_n,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """WITH with_lag AS (
                       SELECT id, run_id, expected_char, actual_char, error_type,
                              LAG(expected_char) OVER (
                                  PARTITION BY run_id ORDER BY id
                              ) AS prev_expected,
                              LAG(actual_char) OVER (
                                  PARTITION BY run_id ORDER BY id
                              ) AS prev_actual,
                              LAG(error_type) OVER (
                                  PARTITION BY run_id ORDER BY id
                              ) AS prev_error_type
                       FROM keystrokes
                       WHERE error_type IN ('correct', 'cognitive_error')
                         AND is_backspace = 0
                   )
                   SELECT
                       CASE WHEN expected_char < actual_char
                            THEN expected_char ELSE actual_char END AS char_a,
                       CASE WHEN expected_char < actual_char
                            THEN actual_char ELSE expected_char END AS char_b,
                       COUNT(*) AS cnt
                   FROM with_lag
                   WHERE error_type = 'cognitive_error'
                     AND prev_error_type = 'cognitive_error'
                     AND expected_char = prev_actual
                     AND actual_char = prev_expected
                   GROUP BY char_a, char_b
                   ORDER BY cnt DESC"""
            ).fetchall()

        return [(row["char_a"], row["char_b"], row["cnt"]) for row in rows]

    def get_error_rate_by_position(
        self, bucket_size: int = 5
    ) -> list[tuple[int, int, int]]:
        """Get error counts by absolute position within runs.

        Groups keystrokes into buckets of ``bucket_size`` consecutive
        positions (0-4, 5-9, ...) and counts errors vs total in each.

        Only includes cognitive keystrokes (correct + cognitive_error,
        no backspace).

        Returns:
            List of ``(bucket_start, errors, total)`` sorted by
            bucket_start.
        """
        rows = self.db.conn.execute(
            """SELECT
                   (position / ?) * ? AS bucket_start,
                   COUNT(*) AS total,
                   SUM(CASE WHEN error_type = 'cognitive_error'
                       THEN 1 ELSE 0 END) AS errors
               FROM keystrokes
               WHERE error_type IN ('correct', 'cognitive_error')
                 AND is_backspace = 0
               GROUP BY bucket_start
               ORDER BY bucket_start""",
            (bucket_size, bucket_size),
        ).fetchall()

        return [(row["bucket_start"], row["errors"], row["total"]) for row in rows]

    def get_historical_position_rts(
        self,
        min_target_length: int,
        n_runs: int = 64,
        warmup: int = 3,
    ) -> list[tuple[int, str, float]]:
        """Get per-position reaction times from recent qualifying runs.

        Returns ``(position, expected_char, reaction_time_ms)`` for every
        valid keystroke in the most recent *n_runs* runs whose
        ``target_length >= min_target_length``.

        Filters applied:
        - ``is_backspace = 0``
        - ``error_type`` not in (``motor_overflow``, ``burst_repeat``)
        - ``reaction_time_ms`` is not NULL and ``<= RT_CAP_MS``
        - ``position >= warmup``

        Results are **not** ordered in any particular way; callers should
        group by position themselves.
        """
        rows = self.db.conn.execute(
            """SELECT k.position, k.expected_char, k.reaction_time_ms
               FROM keystrokes k
               JOIN (
                   SELECT id FROM runs
                   WHERE target_length >= ?
                   ORDER BY id DESC
                   LIMIT ?
               ) AS recent ON recent.id = k.run_id
               WHERE k.is_backspace = 0
                 AND k.error_type NOT IN ('motor_overflow', 'burst_repeat')
                 AND k.reaction_time_ms IS NOT NULL
                 AND k.reaction_time_ms <= ?
                 AND k.position >= ?""",
            (min_target_length, n_runs, RT_CAP_MS, warmup),
        ).fetchall()
        return [
            (row["position"], row["expected_char"], float(row["reaction_time_ms"]))
            for row in rows
        ]

    def get_per_letter_occurrence_series(
        self,
    ) -> list[tuple[int, dict[str, float]]]:
        """Get per-letter occurrence percentage for each run.

        For every run, returns the percentage of keystrokes targeting each
        letter.  Only counts non-backspace keystrokes with ``error_type``
        in (``correct``, ``cognitive_error``) — i.e. the intended text
        distribution, excluding motor overflow and burst repeat.

        Returns:
            List of ``(run_id, {letter: percentage})`` ordered by run_id.
            Percentages are 0–100.
        """
        rows = self.db.conn.execute(
            """SELECT run_id, expected_char, COUNT(*) AS cnt
               FROM keystrokes
               WHERE is_backspace = 0
                 AND error_type IN ('correct', 'cognitive_error')
               GROUP BY run_id, expected_char
               ORDER BY run_id""",
        ).fetchall()

        # Build per-run totals and per-letter counts
        from collections import defaultdict

        run_letter_counts: dict[int, dict[str, int]] = defaultdict(dict)
        run_totals: dict[int, int] = defaultdict(int)
        for row in rows:
            rid = row["run_id"]
            char = row["expected_char"]
            cnt = row["cnt"]
            run_letter_counts[rid][char] = cnt
            run_totals[rid] += cnt

        result: list[tuple[int, dict[str, float]]] = []
        for rid in sorted(run_letter_counts):
            total = run_totals[rid]
            if total == 0:
                continue
            pcts = {
                char: cnt / total * 100.0
                for char, cnt in run_letter_counts[rid].items()
            }
            result.append((rid, pcts))
        return result

    def get_error_timeline(
        self,
    ) -> list[tuple[int, str, str, str, int, int]]:
        """Get all error keystrokes across all runs for timeline charting.

        Returns a list of
        ``(run_id, expected_char, actual_char, error_type, position, target_length)``
        for every non-backspace keystroke where ``error_type != 'correct'``,
        ordered chronologically (by ``run_id``, then ``position``).
        """
        rows = self.db.conn.execute(
            """SELECT k.run_id, k.expected_char, k.actual_char,
                      k.error_type, k.position, r.target_length
               FROM keystrokes k
               JOIN runs r ON r.id = k.run_id
               WHERE k.error_type != 'correct'
                 AND k.is_backspace = 0
               ORDER BY k.run_id, k.position""",
        ).fetchall()
        return [
            (
                row["run_id"],
                row["expected_char"],
                row["actual_char"],
                row["error_type"],
                row["position"],
                row["target_length"],
            )
            for row in rows
        ]

    def get_bigram_error_rates(
        self,
        min_count: int = 10,
        practice_types: list[str] | None = None,
    ) -> list[tuple[str, str, int, int, float]]:
        """Get error rate for each bigram (prev_char, expected_char).

        A "bigram" here is a transition from the previously typed character
        to the currently expected character.  Only includes keystrokes where
        the *previous* keystroke was correct, so ``prev_char`` reliably
        represents the intended letter transition.

        Only includes cognitive keystrokes (correct + cognitive_error),
        excludes backspaces and motor overflow / burst repeat.

        Args:
            min_count: Minimum total occurrences for a bigram to be
                included. Filters out noisy low-sample pairs.
            practice_types: If given, only include keystrokes from runs
                with these practice types (e.g. ``['random_words', 'sentences']``).
                If ``None``, includes all practice types.

        Returns:
            List of ``(prev_char, expected_char, errors, total, error_rate)``
            sorted by error_rate descending.
        """
        if practice_types:
            placeholders = ",".join("?" for _ in practice_types)
            rows = self.db.conn.execute(
                f"""SELECT k.prev_char, k.expected_char,
                          COUNT(*) AS total,
                          SUM(CASE WHEN k.error_type = 'cognitive_error'
                              THEN 1 ELSE 0 END) AS errors
                   FROM keystrokes k
                   JOIN runs r ON k.run_id = r.id
                   JOIN keystrokes pk
                     ON pk.run_id = k.run_id
                    AND pk.position = k.position - 1
                   WHERE k.prev_char IS NOT NULL
                     AND k.error_type IN ('correct', 'cognitive_error')
                     AND k.is_backspace = 0
                     AND pk.error_type = 'correct'
                     AND pk.is_backspace = 0
                     AND r.practice_type IN ({placeholders})
                   GROUP BY k.prev_char, k.expected_char
                   HAVING total >= ?
                   ORDER BY CAST(errors AS REAL) / total DESC""",
                (*practice_types, min_count),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """SELECT k.prev_char, k.expected_char,
                          COUNT(*) AS total,
                          SUM(CASE WHEN k.error_type = 'cognitive_error'
                              THEN 1 ELSE 0 END) AS errors
                   FROM keystrokes k
                   JOIN keystrokes pk
                     ON pk.run_id = k.run_id
                    AND pk.position = k.position - 1
                   WHERE k.prev_char IS NOT NULL
                     AND k.error_type IN ('correct', 'cognitive_error')
                     AND k.is_backspace = 0
                     AND pk.error_type = 'correct'
                     AND pk.is_backspace = 0
                   GROUP BY k.prev_char, k.expected_char
                   HAVING total >= ?
                   ORDER BY CAST(errors AS REAL) / total DESC""",
                (min_count,),
            ).fetchall()

        return [
            (
                row["prev_char"],
                row["expected_char"],
                row["errors"],
                row["total"],
                row["errors"] / row["total"] if row["total"] > 0 else 0.0,
            )
            for row in rows
        ]

    def get_bigram_transition_times(
        self,
        min_count: int = 10,
        practice_types: list[str] | None = None,
    ) -> list[tuple[str, str, list[int], int]]:
        """Get raw transition (reaction) times for each bigram.

        Returns raw RT values so the caller can compute trimmed mean or
        other robust statistics in Python.  Only includes correct
        keystrokes with a recorded reaction time where the *previous*
        keystroke was also correct, so ``prev_char`` reliably represents
        the intended letter transition.

        Args:
            min_count: Minimum number of correct keystrokes with RT for
                a bigram to be included.
            practice_types: If given, only include keystrokes from runs
                with these practice types.

        Returns:
            List of ``(prev_char, expected_char, rt_values, count)``
            sorted by median RT descending.  ``rt_values`` is a list of
            individual reaction times in ms; ``count`` = ``len(rt_values)``.
        """
        if practice_types:
            placeholders = ",".join("?" for _ in practice_types)
            rows = self.db.conn.execute(
                f"""SELECT k.prev_char, k.expected_char, k.reaction_time_ms
                   FROM keystrokes k
                   JOIN runs r ON k.run_id = r.id
                   JOIN keystrokes pk
                     ON pk.run_id = k.run_id
                    AND pk.position = k.position - 1
                   WHERE k.prev_char IS NOT NULL
                     AND k.error_type = 'correct'
                     AND k.reaction_time_ms IS NOT NULL
                     AND k.is_backspace = 0
                     AND pk.error_type = 'correct'
                     AND pk.is_backspace = 0
                     AND r.practice_type IN ({placeholders})
                   ORDER BY k.prev_char, k.expected_char""",
                tuple(practice_types),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """SELECT k.prev_char, k.expected_char, k.reaction_time_ms
                   FROM keystrokes k
                   JOIN keystrokes pk
                     ON pk.run_id = k.run_id
                    AND pk.position = k.position - 1
                   WHERE k.prev_char IS NOT NULL
                     AND k.error_type = 'correct'
                     AND k.reaction_time_ms IS NOT NULL
                     AND k.is_backspace = 0
                     AND pk.error_type = 'correct'
                     AND pk.is_backspace = 0
                   ORDER BY k.prev_char, k.expected_char"""
            ).fetchall()

        # Group by (prev_char, expected_char) and collect RT values
        from collections import defaultdict

        bigram_rts: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in rows:
            key = (row["prev_char"], row["expected_char"])
            bigram_rts[key].append(row["reaction_time_ms"])

        # Filter by min_count and sort by median RT descending
        result: list[tuple[str, str, list[int], int]] = []
        for (pc, ec), rts in bigram_rts.items():
            if len(rts) >= min_count:
                result.append((pc, ec, rts, len(rts)))

        # Sort by median RT descending (slowest first)
        result.sort(key=lambda x: sorted(x[2])[len(x[2]) // 2], reverse=True)
        return result

    # ── Reclassification ──────────────────────────────────────────────

    def reclassify_all_runs(
        self,
        motor_overflow_window_ms: int = 80,
        burst_max_interval_ms: int = 500,
    ) -> int:
        """Recompute derived keystroke columns from raw measurement data.

        Processes every run in the database, re-running the ErrorClassifier
        on the raw columns (``position``, ``timestamp_ms``, ``expected_char``,
        ``actual_char``, ``is_backspace``) and updating the derived columns
        (``error_type``, ``reaction_time_ms``).  Also recomputes run-level
        aggregates (``cognitive_errors``, ``motor_overflow_errors``, etc.).

        This is idempotent — running it twice produces the same result.

        Returns:
            Number of keystrokes reclassified.
        """
        run_ids = [
            row["id"]
            for row in self.db.conn.execute(
                "SELECT id FROM runs ORDER BY id"
            ).fetchall()
        ]

        total_reclassified = 0
        for run_id in run_ids:
            total_reclassified += self._reclassify_run(
                run_id, motor_overflow_window_ms, burst_max_interval_ms
            )

        self.db.conn.commit()
        return total_reclassified

    def _reclassify_run(
        self,
        run_id: int,
        motor_overflow_window_ms: int,
        burst_max_interval_ms: int,
    ) -> int:
        """Reclassify all keystrokes in a single run.

        Updates ``error_type`` and ``reaction_time_ms`` on each keystroke,
        then recomputes run-level aggregate columns.

        Returns number of keystrokes reclassified (excludes backspaces).
        """
        rows = self.db.conn.execute(
            """SELECT id, position, timestamp_ms, expected_char, actual_char,
                      is_backspace
               FROM keystrokes
               WHERE run_id = ?
               ORDER BY id""",
            (run_id,),
        ).fetchall()

        classifier = ErrorClassifier(
            motor_overflow_window_ms=motor_overflow_window_ms,
            burst_max_interval_ms=burst_max_interval_ms,
        )

        prev_timestamp: int | None = None
        reclassified = 0

        # Counters for run-level aggregates
        total_scored = 0
        cognitive_errors = 0
        motor_overflow_errors = 0
        burst_repeat_count = 0

        for row in rows:
            ks_id: int = row["id"]

            if row["is_backspace"]:
                # Backspace keystrokes are kept as-is — they are raw
                # observations with no derived classification.
                continue

            timestamp_ms: int = row["timestamp_ms"]
            expected_char: str = row["expected_char"]
            actual_char: str = row["actual_char"]

            # Recompute reaction time from timestamps
            reaction_time_ms: int | None = None
            if prev_timestamp is not None:
                reaction_time_ms = timestamp_ms - prev_timestamp

            # Reclassify
            result = classifier.classify(
                expected_char=expected_char,
                actual_char=actual_char,
                timestamp_ms=timestamp_ms,
                position=row["position"],
            )

            # Update derived columns
            self.db.conn.execute(
                """UPDATE keystrokes
                   SET error_type = ?, reaction_time_ms = ?
                   WHERE id = ?""",
                (result.error_type.value, reaction_time_ms, ks_id),
            )
            reclassified += 1

            # Only update prev_timestamp for cursor-advancing keystrokes
            # (not motor overflow or burst repeat — mirrors engine.py logic)
            if result.error_type not in (
                ErrorType.MOTOR_OVERFLOW,
                ErrorType.BURST_REPEAT,
            ):
                prev_timestamp = timestamp_ms
                total_scored += 1
                if result.error_type == ErrorType.COGNITIVE_ERROR:
                    cognitive_errors += 1
            else:
                if result.error_type == ErrorType.MOTOR_OVERFLOW:
                    motor_overflow_errors += 1
                else:
                    burst_repeat_count += 1

        # Recompute run aggregates
        accuracy = (
            (total_scored - cognitive_errors) / total_scored
            if total_scored > 0
            else 1.0
        )
        self.db.conn.execute(
            """UPDATE runs
               SET total_keystrokes = ?,
                   cognitive_errors = ?,
                   motor_overflow_errors = ?,
                   burst_repeat_count = ?,
                   swap_count = ?,
                   accuracy = ?
               WHERE id = ?""",
            (
                total_scored,
                cognitive_errors,
                motor_overflow_errors,
                burst_repeat_count,
                classifier.swap_count,
                accuracy,
                run_id,
            ),
        )

        return reclassified

    # ── Mastery Bootstrap ─────────────────────────────────────────────

    def bootstrap_mastery(
        self,
        mastery_keystrokes_required: int = 1500,
        advancement_accuracy: float = 0.95,
        mastery_threshold: float = 0.8,
        mastery_half_life_min_days: float = 14.0,
        mastery_half_life_max_days: float = 90.0,
        accuracy_window: int = 200,
    ) -> None:
        """Compute mastery_score from session history for all letters.

        Replays sessions chronologically, tracking per-letter rolling
        accuracy and state to determine qualifying keystrokes at each
        session boundary.  Applies mastery decay between sessions.

        This is a one-time migration — called from v7 schema migration.
        After this, ongoing mastery updates are handled incrementally
        by ``LetterManager.update_states_after_session()``.
        """
        import math

        # Load all sessions in chronological order with their runs
        sessions = self.db.conn.execute(
            "SELECT id, start_time, end_time FROM sessions ORDER BY id"
        ).fetchall()

        if not sessions:
            return

        # Load the current letter states to know which letters exist
        # and what their current state/stability/history is.
        # We only need to compute mastery — states are already correct.
        letter_states = self.get_all_letter_states()

        if not letter_states:
            return

        # Determine when each letter was first introduced by finding
        # the earliest session where it appears in keystrokes.
        letter_first_session: dict[str, int] = {}
        for letter in letter_states:
            row = self.db.conn.execute(
                """SELECT MIN(r.session_id) AS first_sid
                   FROM keystrokes k
                   JOIN runs r ON k.run_id = r.id
                   WHERE k.expected_char = ?
                     AND k.is_backspace = 0""",
                (letter,),
            ).fetchone()
            if row is not None and row["first_sid"] is not None:
                letter_first_session[letter] = row["first_sid"]

        # For each letter, build a rolling accuracy buffer and track
        # when it became STABLE.  We use a simplified heuristic:
        # a letter is "stable-like" once it has accumulated enough
        # keystrokes AND its rolling accuracy has been >= threshold
        # for a sustained period.
        #
        # Precise replay of the full state machine is complex (depends
        # on stability_score, sessions_in_current_state, accuracy_history,
        # etc.).  Instead we use a conservative approximation:
        #
        #   A letter qualifies for mastery in a session if:
        #   1. It has been active for >= 5 sessions (covers introducing +
        #      consolidating transition minimum)
        #   2. Its rolling accuracy (last `accuracy_window` keystrokes up
        #      to this session) is >= advancement_accuracy
        #
        # This slightly underestimates mastery for letters that became
        # stable very quickly, and slightly overestimates for edge cases
        # where a letter was degraded.  Since mastery builds slowly
        # (~0.013 per session), the error is small.
        MIN_SESSIONS_FOR_QUALIFYING = 5

        # Collect per-letter, per-session keystroke data
        # Structure: {letter: [(session_id, session_end_time, keystrokes_count)]}
        letter_session_data: dict[str, list[tuple[int, str | None, int]]] = {
            letter: [] for letter in letter_states
        }

        for session in sessions:
            sid = session["id"]
            end_time = session["end_time"]
            # Count scored keystrokes per letter in this session
            rows = self.db.conn.execute(
                """SELECT expected_char, COUNT(*) AS cnt
                   FROM keystrokes k
                   JOIN runs r ON k.run_id = r.id
                   WHERE r.session_id = ?
                     AND k.error_type IN ('correct', 'cognitive_error')
                     AND k.is_backspace = 0
                   GROUP BY expected_char""",
                (sid,),
            ).fetchall()
            for row in rows:
                letter = row["expected_char"]
                if letter in letter_session_data:
                    letter_session_data[letter].append((sid, end_time, row["cnt"]))

        # Build rolling accuracy buffers per letter and compute mastery
        for letter, stats in letter_states.items():
            first_sid = letter_first_session.get(letter)
            if first_sid is None:
                continue

            # Collect all scored keystrokes for rolling accuracy computation
            all_keystrokes = self.db.conn.execute(
                """SELECT k.error_type, r.session_id
                   FROM keystrokes k
                   JOIN runs r ON k.run_id = r.id
                   WHERE k.expected_char = ?
                     AND k.error_type IN ('correct', 'cognitive_error')
                     AND k.is_backspace = 0
                   ORDER BY k.id""",
                (letter,),
            ).fetchall()

            # Group keystrokes by session and compute rolling accuracy
            # at each session boundary
            session_boundaries: list[tuple[int, float, int]] = []
            buf: deque[bool] = deque()  # True = correct
            errors_in_buf = 0
            current_sid: int | None = None
            session_ks_count = 0

            for ks in all_keystrokes:
                sid = ks["session_id"]
                is_correct = ks["error_type"] == "correct"

                if sid != current_sid:
                    # Emit the previous session boundary
                    if current_sid is not None and len(buf) > 0:
                        acc = (len(buf) - errors_in_buf) / len(buf)
                        session_boundaries.append((current_sid, acc, session_ks_count))
                    current_sid = sid
                    session_ks_count = 0

                buf.append(is_correct)
                if not is_correct:
                    errors_in_buf += 1
                session_ks_count += 1

                while len(buf) > accuracy_window:
                    old = buf.popleft()
                    if not old:
                        errors_in_buf -= 1

            # Emit last session boundary
            if current_sid is not None and len(buf) > 0:
                acc = (len(buf) - errors_in_buf) / len(buf)
                session_boundaries.append((current_sid, acc, session_ks_count))

            # Now compute mastery by walking session boundaries
            mastery_score = 0.0
            qualifying_total = 0
            sessions_active = 0
            prev_end_time: datetime | None = None

            # Build a session_id -> end_time lookup
            session_end_times: dict[int, str | None] = {
                s["id"]: s["end_time"] for s in sessions
            }

            for sid, rolling_acc, ks_count in session_boundaries:
                sessions_active += 1
                end_time_str = session_end_times.get(sid)
                current_end = _str_to_dt(end_time_str) if end_time_str else None

                # Apply mastery decay since previous session
                if prev_end_time is not None and current_end is not None:
                    hours_elapsed = (
                        current_end - prev_end_time
                    ).total_seconds() / 3600.0
                    if hours_elapsed > 0 and mastery_score > 0:
                        half_life_days = mastery_half_life_min_days + mastery_score * (
                            mastery_half_life_max_days - mastery_half_life_min_days
                        )
                        half_life_hours = half_life_days * 24.0
                        decay_constant = math.log(2) / half_life_hours
                        mastery_score *= math.exp(-decay_constant * hours_elapsed)

                # Check qualifying condition
                if (
                    sessions_active >= MIN_SESSIONS_FOR_QUALIFYING
                    and rolling_acc >= advancement_accuracy
                ):
                    delta = ks_count / mastery_keystrokes_required
                    mastery_score = min(1.0, mastery_score + delta)
                    qualifying_total += ks_count

                if current_end is not None:
                    prev_end_time = current_end

            # Apply final decay from last session to now
            if prev_end_time is not None and mastery_score > 0:
                from datetime import datetime as _dt

                hours_since = (_dt.now() - prev_end_time).total_seconds() / 3600.0
                if hours_since > 0:
                    half_life_days = mastery_half_life_min_days + mastery_score * (
                        mastery_half_life_max_days - mastery_half_life_min_days
                    )
                    half_life_hours = half_life_days * 24.0
                    decay_constant = math.log(2) / half_life_hours
                    mastery_score *= math.exp(-decay_constant * hours_since)

            # Update the letter state
            stats.mastery_score = mastery_score
            stats.mastery_qualifying_keystrokes = qualifying_total

            # Check if it should be MASTERED
            if stats.state == LetterState.STABLE and mastery_score >= mastery_threshold:
                stats.state = LetterState.MASTERED
                stats.sessions_in_current_state = 0

            self._upsert_letter_state(stats)
