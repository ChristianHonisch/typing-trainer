"""SQLite database schema and connection management.

All typing data is stored locally in a single SQLite file.
The schema captures sessions, runs, individual keystrokes, and letter states.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 7

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time  TEXT NOT NULL,
    end_time    TEXT,
    language    TEXT NOT NULL DEFAULT 'de',
    layout      TEXT NOT NULL DEFAULT 'qwertz'
);

-- Runs: one row per typing exercise.
-- Run-level metadata: session_id, start_time, end_time, mode,
--   practice_type, target_text, target_length, completed, failed,
--   fail_threshold_used, wpm, backspace_count
-- Denormalized aggregates (recomputed by reclassify_all_runs()):
--   total_keystrokes, cognitive_errors, motor_overflow_errors,
--   burst_repeat_count, swap_count, accuracy
CREATE TABLE IF NOT EXISTS runs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL REFERENCES sessions(id),
    start_time              TEXT NOT NULL,
    end_time                TEXT,
    mode                    TEXT NOT NULL,
    practice_type           TEXT NOT NULL,
    target_text             TEXT NOT NULL,
    target_length           INTEGER NOT NULL,
    total_keystrokes        INTEGER NOT NULL DEFAULT 0,
    cognitive_errors        INTEGER NOT NULL DEFAULT 0,
    motor_overflow_errors   INTEGER NOT NULL DEFAULT 0,
    backspace_count         INTEGER NOT NULL DEFAULT 0,
    accuracy                REAL NOT NULL DEFAULT 1.0,
    wpm                     REAL NOT NULL DEFAULT 0.0,
    completed               INTEGER NOT NULL DEFAULT 0,
    failed                  INTEGER NOT NULL DEFAULT 0,
    fail_threshold_used     REAL NOT NULL DEFAULT 0.0
);

-- Keystrokes: each row is one physical keypress.
-- Raw measurement columns (immutable once written):
--   position, timestamp_ms, expected_char, actual_char, is_backspace
-- Derived columns (recomputable via reclassify_all_runs()):
--   error_type, reaction_time_ms
-- Deprecated columns (retained for historical data):
--   prev_char — superseded by self-join on (run_id, position-1)
CREATE TABLE IF NOT EXISTS keystrokes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    position            INTEGER NOT NULL,
    timestamp_ms        INTEGER NOT NULL,
    expected_char       TEXT NOT NULL,
    actual_char         TEXT NOT NULL,
    error_type          TEXT NOT NULL,
    reaction_time_ms    INTEGER,
    prev_char           TEXT,
    is_backspace        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS letter_states (
    letter                          TEXT PRIMARY KEY,
    state                           TEXT NOT NULL DEFAULT 'introducing',
    stability_score                 REAL NOT NULL DEFAULT 0.3,
    last_practiced                  TEXT,
    error_rate_last_session         REAL NOT NULL DEFAULT 0.0,
    sessions_in_current_state       INTEGER NOT NULL DEFAULT 0,
    sessions_since_introduced       INTEGER NOT NULL DEFAULT 0,
    accuracy_history                TEXT NOT NULL DEFAULT '[]',
    keystrokes_at_introduction      INTEGER NOT NULL DEFAULT 0,
    mastery_score                   REAL NOT NULL DEFAULT 0.0,
    mastery_qualifying_keystrokes   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS active_letter_order (
    position    INTEGER PRIMARY KEY,
    letter      TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS speed_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    target_wpm      REAL NOT NULL DEFAULT 30.0,
    best_wpm        REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
CREATE INDEX IF NOT EXISTS idx_keystrokes_run ON keystrokes(run_id);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_keystrokes_expected_error
    ON keystrokes(expected_char, error_type, is_backspace);
"""


class Database:
    """SQLite database connection and schema management."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self) -> None:
        """Create tables if they don't exist. Apply migrations if needed."""
        self.conn.executescript(SCHEMA_SQL)

        # Check / set schema version
        cursor = self.conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
        if count == 0:
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            self.conn.commit()

        # Migrations: add columns that may not exist in older databases
        self._migrate()

    def _migrate(self) -> None:
        """Apply column migrations for schema evolution."""
        # Add keystrokes_at_introduction column to letter_states (v2)
        ls_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(letter_states)")
        }
        if "keystrokes_at_introduction" not in ls_columns:
            self.conn.execute(
                "ALTER TABLE letter_states ADD COLUMN "
                "keystrokes_at_introduction INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.commit()

        # Add burst_repeat_count and swap_count columns to runs (v3)
        runs_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        if "burst_repeat_count" not in runs_columns:
            self.conn.execute(
                "ALTER TABLE runs ADD COLUMN "
                "burst_repeat_count INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.commit()
        if "swap_count" not in runs_columns:
            self.conn.execute(
                "ALTER TABLE runs ADD COLUMN swap_count INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.commit()

        # Fix stability_score for introducing letters that were incorrectly
        # initialized at 1.0 (maximum) instead of 0.3.  Only affects letters
        # still in introducing state — letters that have already progressed
        # to consolidating/stable have earned their stability through practice.
        self.conn.execute(
            "UPDATE letter_states SET stability_score = 0.3 "
            "WHERE state = 'introducing' AND stability_score >= 1.0"
        )
        self.conn.commit()

        # Add composite index for per-letter queries (v3b).
        # Covers rolling accuracy, error windows, error rates, etc.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_keystrokes_expected_error "
            "ON keystrokes(expected_char, error_type, is_backspace)"
        )
        self.conn.commit()

        # Add index for bigram transition queries (v4).
        # Covers both error-rate and transition-time lookups:
        #   get_bigram_error_rates():  GROUP BY (prev_char, expected_char)
        #                              WHERE error_type IN (...) AND is_backspace=0
        #   get_bigram_transition_times(): WHERE error_type='correct'
        #                                  AND reaction_time_ms IS NOT NULL
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_keystrokes_bigram "
            "ON keystrokes(prev_char, expected_char, error_type, is_backspace)"
        )
        self.conn.commit()

        # Add composite index for bigram self-join (v5a).
        # The bigram queries join keystrokes to the previous keystroke
        # via (run_id, position - 1).  This index makes that fast.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_keystrokes_run_position "
            "ON keystrokes(run_id, position)"
        )
        self.conn.commit()

        # Reclassify mislabeled random_words runs (v5b).
        # Early runs were recorded as 'random_words' before the text
        # generator distinguished practice types, but their target text
        # is random letter gibberish (e.g. "neeeee eenenn nnee").
        # Detect: runs labeled random_words whose target text uses ≤2
        # distinct non-space characters — impossible for real words.
        rows = self.conn.execute(
            "SELECT id, target_text FROM runs WHERE practice_type = 'random_words'"
        ).fetchall()
        mislabeled_ids = []
        for row in rows:
            unique_chars = set(row[1].replace(" ", ""))
            if len(unique_chars) <= 2:
                mislabeled_ids.append(row[0])
        if mislabeled_ids:
            placeholders = ",".join("?" for _ in mislabeled_ids)
            self.conn.execute(
                f"UPDATE runs SET practice_type = 'random_strings' "
                f"WHERE id IN ({placeholders})",
                mislabeled_ids,
            )
            self.conn.commit()

        # --- Version-gated migrations ---
        current_version_row = self.conn.execute(
            "SELECT version FROM schema_version"
        ).fetchone()
        current_version = (
            current_version_row[0] if current_version_row is not None else 0
        )

        if current_version < 6:
            # v6: Reclassify all keystrokes from raw measurement data.
            # Re-runs ErrorClassifier on (position, timestamp_ms,
            # expected_char, actual_char, is_backspace) and recomputes
            # error_type, reaction_time_ms, and run-level aggregates.
            # Fixes historical misclassifications (e.g. motor overflow
            # false positives on legitimate double-letters).
            # Local import to avoid circular dependency.
            from typing_trainer.storage.repository import Repository

            repo = Repository(self)
            repo.reclassify_all_runs()
            self.conn.commit()

        if current_version < 7:
            # v7: Add mastery columns to letter_states.
            if "mastery_score" not in ls_columns:
                self.conn.execute(
                    "ALTER TABLE letter_states ADD COLUMN "
                    "mastery_score REAL NOT NULL DEFAULT 0.0"
                )
            if "mastery_qualifying_keystrokes" not in ls_columns:
                self.conn.execute(
                    "ALTER TABLE letter_states ADD COLUMN "
                    "mastery_qualifying_keystrokes INTEGER NOT NULL DEFAULT 0"
                )
            self.conn.commit()

            # Bootstrap mastery from session history: replay all sessions
            # to compute what mastery_score would be now.
            from typing_trainer.storage.repository import Repository

            repo = Repository(self)
            repo.bootstrap_mastery()
            self.conn.commit()

        if current_version < SCHEMA_VERSION:
            self.conn.execute(
                "UPDATE schema_version SET version = ?", (SCHEMA_VERSION,)
            )
            self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Database:
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
