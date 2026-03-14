"""Main application window — controller connecting all UI widgets to the engine.

Layout:
- Left sidebar: session dashboard + letter overview
- Main area: tabbed (Training | Analysis)
  - Training tab: stacked widget (run config / typing / run summary)
  - Analysis tab: sub-tabbed charts (accuracy, WPM, per-letter, errors)

Flow: config -> typing -> summary -> config (loop)
Analysis tab disabled during typing runs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.config import Config
from typing_trainer.core.engine import TypingEngine
from typing_trainer.core.letter_manager import LetterManager
from typing_trainer.core.spaced_repetition import SpacedRepetition
from typing_trainer.core.speed_manager import SpeedManager
from typing_trainer.core.text_generator import TextGenerator
from typing_trainer.models.letter_state import LetterState, LetterStats, PracticeType, RunMode
from typing_trainer.models.session import Session
from typing_trainer.storage.database import Database
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.letter_overview import LetterOverviewWidget
from typing_trainer.ui.run_config_widget import RunConfigWidget
from typing_trainer.ui.run_summary_widget import RunSummaryWidget
from typing_trainer.ui.session_dashboard import SessionDashboard
from typing_trainer.ui.theme import (
    COLOR_BG_CURSOR,
    COLOR_BG_DARK,
    COLOR_BG_DARKEST,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)
from typing_trainer.ui.analytics_widget import AnalyticsWidget
from typing_trainer.ui.typing_widget import TypingWidget


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

        # Core components
        self.db = Database(config.db_path)
        self.db.initialize()
        self.repo = Repository(self.db)
        self.engine = TypingEngine(config)
        self.text_gen = TextGenerator(config)
        self.letter_mgr = LetterManager(config)
        self.spaced_rep = SpacedRepetition(config)
        self.speed_mgr = SpeedManager(config)

        # State
        self._active_letters: dict[str, LetterStats] = {}
        self._current_session: Session | None = None
        self._last_run_result = None
        self._last_speed_result = None

        # Session timeout timer
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setInterval(60_000)  # check every minute
        self._inactivity_timer.timeout.connect(self._check_session_timeout)

        self._load_state()
        self._setup_ui()
        self._ensure_session()
        self._refresh_dashboard()

        self._inactivity_timer.start()

    def _load_state(self) -> None:
        """Load persisted state from the database."""
        self._active_letters = self.repo.get_all_letter_states()

        if not self._active_letters:
            # First launch — initialize with first 2 letters
            self._active_letters = self.letter_mgr.initialize_first_letters(count=2)
            self.repo.save_all_letter_states(self._active_letters)
            intro_order = self.letter_mgr.introduction_order
            self.repo.save_active_letter_order(intro_order)

        # Apply time-based decay
        self._active_letters, reverted = self.spaced_rep.apply_time_decay(
            self._active_letters
        )
        if reverted:
            self.repo.save_all_letter_states(self._active_letters)

        # Load speed state
        target_wpm, best_wpm = self.repo.get_speed_state()
        self.speed_mgr.target_wpm = target_wpm
        self.speed_mgr.best_wpm = best_wpm

    def _setup_ui(self) -> None:
        self.setWindowTitle("Typing Trainer")
        self.setMinimumSize(1000, 700)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter: sidebar | main area
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left sidebar
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)

        self._session_dashboard = SessionDashboard()
        sidebar_layout.addWidget(self._session_dashboard)

        self._letter_overview = LetterOverviewWidget()
        sidebar_layout.addWidget(self._letter_overview)

        splitter.addWidget(sidebar)

        # Main area: top-level tab widget (Training | Analysis)
        self._main_tabs = QTabWidget()
        self._main_tabs.setObjectName("mainTabs")
        self._main_tabs.setFont(app_font(12))
        self._main_tabs.currentChanged.connect(self._on_main_tab_changed)

        # Tab 0: Training (stacked widget: config / typing / summary)
        self._stack = QStackedWidget()

        # Page 0: Run configuration
        self._config_widget = RunConfigWidget(self.config)
        self._config_widget.start_run.connect(self._on_start_run)
        self._stack.addWidget(self._config_widget)

        # Page 1: Typing (created per-run)
        self._typing_placeholder = QWidget()
        self._stack.addWidget(self._typing_placeholder)

        # Page 2: Run summary
        self._summary_widget = RunSummaryWidget(self.config)
        self._summary_widget.continue_clicked.connect(self._on_continue)
        self._stack.addWidget(self._summary_widget)

        self._main_tabs.addTab(self._stack, "Training")

        # Tab 1: Analysis
        self._analytics = AnalyticsWidget(config=self.config)
        self._main_tabs.addTab(self._analytics, "Analysis")

        # Wire bigram chart selection -> run config + auto-switch to Training
        self._analytics.bigram_chart.bigrams_selected.connect(
            self._on_bigrams_selected
        )

        splitter.addWidget(self._main_tabs)

        # Set initial sizes (sidebar ~300px, main area fills rest)
        splitter.setSizes([300, 700])
        main_layout.addWidget(splitter)

        # Show config page
        self._stack.setCurrentIndex(0)
        self._config_widget.setFocus()

        # Dark theme
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background-color: {COLOR_BG_DARKEST};
                color: {COLOR_TEXT_PRIMARY};
            }}
            QGroupBox {{
                border: 1px solid {COLOR_BG_TERTIARY};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                padding: 0 5px;
            }}
            QTableWidget {{
                background-color: {COLOR_BG_DARK};
                gridline-color: {COLOR_BG_TERTIARY};
                border: none;
            }}
            QHeaderView::section {{
                background-color: {COLOR_BG_SECONDARY};
                border: 1px solid {COLOR_BG_TERTIARY};
                padding: 4px;
            }}
            QSpinBox, QComboBox {{
                background-color: {COLOR_BG_SECONDARY};
                border: 1px solid {COLOR_BG_CURSOR};
                padding: 5px;
                color: {COLOR_TEXT_PRIMARY};
            }}
            QSplitter::handle {{
                background-color: {COLOR_BG_TERTIARY};
                width: 2px;
            }}
            QTabWidget#mainTabs > QTabBar::tab {{
                background: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_SECONDARY};
                padding: 8px 24px;
                border: 1px solid {COLOR_BG_TERTIARY};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-size: 13px;
            }}
            QTabWidget#mainTabs > QTabBar::tab:selected {{
                background: {COLOR_BG_DARK};
                color: {COLOR_TEXT_PRIMARY};
            }}
            QTabWidget#mainTabs > QTabBar::tab:disabled {{
                color: {COLOR_BG_TERTIARY};
            }}
            QTabWidget#mainTabs::pane {{
                border: 1px solid {COLOR_BG_TERTIARY};
                border-top: none;
            }}
            """
        )

    def _ensure_session(self) -> None:
        """Ensure there's an active session, creating one if needed."""
        if self._current_session is not None:
            if self._current_session.is_expired(self.config.session_timeout_minutes):
                self._end_session()
            else:
                return

        self._current_session = Session(
            start_time=datetime.now(),
            language=self.config.language,
            layout="qwertz",
        )
        self._current_session.touch()
        session_id = self.repo.create_session(self._current_session)
        self._current_session.session_id = session_id

    def _end_session(self) -> None:
        """End the current session."""
        if self._current_session is not None and self._current_session.session_id is not None:
            self.repo.update_session_end(
                self._current_session.session_id, datetime.now()
            )

            # Update letter states based on this session
            if self._current_session.run_count > 0:
                self._active_letters, warnings = (
                    self.letter_mgr.update_states_after_session(
                        self._active_letters, self._current_session
                    )
                )
                self.repo.save_all_letter_states(self._active_letters)

        self._current_session = None

    def _on_main_tab_changed(self, index: int) -> None:
        """Handle top-level tab switch. Refresh analytics when selected."""
        if index == 1:  # Analysis tab
            self._analytics.refresh(self.repo)

    def _check_session_timeout(self) -> None:
        """Check if the session has timed out due to inactivity."""
        if (
            self._current_session is not None
            and self._current_session.is_expired(self.config.session_timeout_minutes)
        ):
            self._end_session()
            self._ensure_session()
            self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        """Refresh all dashboard displays with current state."""
        # Compute rolling accuracy FIRST — needed by letter overview and
        # text generation weighting.
        active_letter_list = list(self._active_letters.keys())
        rolling_accuracy = self.repo.get_per_letter_rolling_accuracy(
            active_letter_list, self.config.advancement_accuracy_window
        )
        rolling_accuracy_long = self.repo.get_per_letter_rolling_accuracy(
            active_letter_list, 2000
        )
        for letter, stats in self._active_letters.items():
            acc, count = rolling_accuracy.get(letter, (1.0, 0))
            stats.rolling_error_rate = 1.0 - acc
            stats.rolling_keystroke_count = count
            acc_long, _count_long = rolling_accuracy_long.get(letter, (1.0, 0))
            stats.rolling_error_rate_long = 1.0 - acc_long

        # Per-run state recheck — detect degradation/recovery immediately
        # rather than waiting for session end.
        if self.letter_mgr.recheck_all_states(self._active_letters):
            self.repo.save_all_letter_states(self._active_letters)

        # Letter overview (uses rolling_error_rate_long)
        remaining = [
            ch for ch in self.letter_mgr.introduction_order
            if ch not in self._active_letters
        ]
        error_rates = self.repo.get_per_letter_error_rates()
        keystroke_counts = {
            letter: total for letter, (_, total, _) in error_rates.items()
        }
        self._letter_overview.update_display(
            self._active_letters, remaining, keystroke_counts,
        )

        # Config widget letter display
        all_stable = all(
            s.state in (LetterState.STABLE, LetterState.MASTERED)
            for s in self._active_letters.values()
        )
        recent_sessions = self.repo.get_recent_sessions(limit=5)
        speed_available = (
            all_stable
            and len(recent_sessions) >= 5
            and all(s.aggregate_accuracy >= 0.95 for s in recent_sessions[:5])
        )
        # Transition mode: same entry conditions as speed, plus bigrams selected
        transition_available = (
            speed_available
            and len(self._config_widget.get_selected_bigrams()) > 0
        )
        self._config_widget.update_letter_display(
            self._active_letters, speed_available, transition_available
        )

        # Session dashboard — compute training times
        session_active_s = 0
        session_elapsed_s = 0
        if self._current_session is not None:
            for run in self._current_session.runs:
                if run.start_time is not None and run.end_time is not None:
                    session_active_s += int(
                        (run.end_time - run.start_time).total_seconds()
                    )
            if self._current_session.start_time is not None:
                session_elapsed_s = int(
                    (datetime.now() - self._current_session.start_time).total_seconds()
                )
        today_s = self.repo.get_training_time_today()
        self._session_dashboard.update_session_info(
            self._current_session, session_active_s, session_elapsed_s, today_s
        )

        # Advancement check
        total_keystrokes = self.repo.get_total_keystrokes_all()
        advancement = self.letter_mgr.check_advancement(
            self._active_letters, rolling_accuracy, total_keystrokes
        )
        blocked_letters = [
            p.letter for p in advancement.per_letter_progress
            if p.has_enough_data and not p.meets_accuracy
        ]
        error_window: dict[str, list[bool]] = {}
        if blocked_letters:
            error_window = self.repo.get_per_letter_error_window(
                blocked_letters, self.config.advancement_accuracy_window
            )
        self._session_dashboard.update_advancement(advancement, error_window)

        # Review status
        review_statuses = self.spaced_rep.get_review_status(self._active_letters)
        self._session_dashboard.update_review_status(review_statuses)

        # Degradation warnings
        warnings = self.letter_mgr.get_degradation_warnings(self._active_letters)
        self._session_dashboard.update_warnings(warnings)

        # Alerts on config widget
        alerts: list[str] = []
        due_letters = self.spaced_rep.get_due_letters(self._active_letters)
        if due_letters:
            alerts.append(
                f"Letters due for review: {', '.join(due_letters)}"
            )
        if advancement.can_advance and advancement.next_letter:
            alerts.append(
                f"Ready to introduce letter '{advancement.next_letter}'!"
            )
        self._config_widget.set_alerts(alerts)

    def _on_bigrams_selected(self, bigrams: list[tuple[str, str]]) -> None:
        """Handle bigram selection from the analytics bigram chart.

        Transfers the selection to the run config widget, switches to
        the Training tab, and sets the mode to Transition.
        """
        self._config_widget.set_selected_bigrams(bigrams)
        # Switch to Training tab
        self._main_tabs.setCurrentIndex(0)
        self._stack.setCurrentIndex(0)
        self._config_widget.setFocus()
        # Auto-select transition mode
        for i in range(self._config_widget._mode_combo.count()):
            if self._config_widget._mode_combo.itemData(i) == RunMode.TRANSITION:
                self._config_widget._mode_combo.setCurrentIndex(i)
                break

    def _on_start_run(self, length: int, mode: RunMode, practice_type: PracticeType) -> None:
        """Start a new typing run."""
        self._ensure_session()
        if self._current_session is not None:
            self._current_session.touch()

        # Determine fail threshold
        fail_threshold = self.letter_mgr.get_fail_threshold(
            self._active_letters, mode
        )

        # Set target bigrams on text generator for transition mode
        if mode == RunMode.TRANSITION:
            bigrams = self._config_widget.get_selected_bigrams()
            self.text_gen.set_target_bigrams(bigrams)

        # Generate text using selected letters (user may have deselected some)
        selected_letters = self._config_widget.get_selected_letters()
        target_text = self.text_gen.generate(
            practice_type, length, selected_letters
        )

        if not target_text:
            return

        # Start engine
        self.engine.start_run(target_text, mode, practice_type, fail_threshold)

        # Create typing widget
        highlight_letters = self._config_widget.get_highlight_letters()
        typing_widget = TypingWidget(self.engine, highlight_letters=highlight_letters)
        typing_widget.run_finished.connect(self._on_run_finished)
        typing_widget.run_aborted.connect(self._on_run_aborted)

        # Replace in stack
        old = self._stack.widget(1)
        assert old is not None
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(1, typing_widget)

        self._main_tabs.setCurrentIndex(0)  # Ensure Training tab is active
        self._main_tabs.setTabEnabled(1, False)  # Disable Analysis during run
        self._stack.setCurrentIndex(1)
        typing_widget.start_run()

    def _check_and_apply_advancement(self) -> None:
        """Check advancement criteria and introduce next letter if ready."""
        active_letter_list = list(self._active_letters.keys())
        rolling_accuracy = self.repo.get_per_letter_rolling_accuracy(
            active_letter_list, self.config.advancement_accuracy_window
        )
        total_keystrokes = self.repo.get_total_keystrokes_all()
        advancement = self.letter_mgr.check_advancement(
            self._active_letters, rolling_accuracy, total_keystrokes
        )
        if advancement.can_advance and advancement.next_letter:
            self.letter_mgr.introduce_letter(
                advancement.next_letter, self._active_letters, total_keystrokes
            )
            self.repo.save_all_letter_states(self._active_letters)

    def _on_run_finished(self) -> None:
        """Handle run completion or failure."""
        result = self.engine.finish_run()

        # Save to database
        if self._current_session is not None and self._current_session.session_id is not None:
            self.repo.save_run(result, self._current_session.session_id)
            self._current_session.add_run(result)

        # Get previous run for delta display
        previous = None
        if (
            result.run_id is not None
            and self._current_session is not None
            and self._current_session.session_id is not None
        ):
            previous = self.repo.get_previous_run(
                self._current_session.session_id, result.run_id
            )

        self._last_run_result = result

        # Update per-letter error rates in active letters from this run
        for letter, per_letter in result.per_letter.items():
            if letter in self._active_letters:
                self._active_letters[letter].error_rate_latest = (
                    per_letter.error_rate
                )
                self._active_letters[letter].last_practiced = datetime.now()

        # Process speed run if applicable
        speed_result = None
        if result.mode == RunMode.SPEED:
            speed_result = self.speed_mgr.process_speed_run(result)
            self._last_speed_result = speed_result
            # Persist speed state
            self.repo.save_speed_state(
                self.speed_mgr.target_wpm, self.speed_mgr.best_wpm
            )

        # Check advancement immediately so the next run includes any new letter
        self._check_and_apply_advancement()

        # Compute settled letters for the intra-run speed chart:
        # letters with >= 2000 historical keystrokes, best third by accuracy.
        settled_letters: set[str] = set()
        rolling_long = self.repo.get_per_letter_rolling_accuracy(
            list(self._active_letters.keys()), 2000
        )
        qualifying = [
            (letter, acc)
            for letter, (acc, count) in rolling_long.items()
            if count >= 2000 and letter != " "
        ]
        if qualifying:
            qualifying.sort(key=lambda t: t[1], reverse=True)  # best first
            n = max(1, len(qualifying) // 3)
            settled_letters = {letter for letter, _ in qualifying[:n]}

        # Show summary
        self._summary_widget.show_result(
            result, previous, speed_result, settled_letters, repo=self.repo
        )
        self._stack.setCurrentIndex(2)
        self._summary_widget.setFocus()

        # Re-enable Analysis tab and refresh dashboard
        self._main_tabs.setTabEnabled(1, True)
        self._refresh_dashboard()

    def _on_run_aborted(self) -> None:
        """Handle user-initiated run abort (Escape).

        The run is discarded entirely — nothing is saved to the database,
        session stats are not updated, and no letter state changes occur.
        """
        self._main_tabs.setTabEnabled(1, True)
        self._stack.setCurrentIndex(0)
        self._config_widget.setFocus()

    def _on_continue(self) -> None:
        """Return to the run config screen."""
        # Safety net: check advancement again in case it wasn't applied yet
        self._check_and_apply_advancement()

        # Transfer rest timer from summary to config widget
        rest_remaining = self._summary_widget.rest_remaining
        self._config_widget.start_rest_timer(rest_remaining)

        self._refresh_dashboard()
        self._stack.setCurrentIndex(0)
        self._config_widget.setFocus()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Clean up on window close."""
        self._end_session()
        self.repo.save_speed_state(
            self.speed_mgr.target_wpm, self.speed_mgr.best_wpm
        )
        self.db.close()
        super().closeEvent(event)
