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
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
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
from typing_trainer.models.keyboard_layout import KeyboardLayout, load_keyboard
from typing_trainer.models.letter_state import (
    DisplayMode,
    LetterState,
    LetterStats,
    PracticeType,
    RunMode,
)
from typing_trainer.models.session import Session
from typing_trainer.storage.database import Database
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.letter_overview import LetterOverviewWidget
from typing_trainer.ui.run_config_widget import RunConfigWidget
from typing_trainer.ui.run_summary_widget import RunSummaryWidget
from typing_trainer.ui.session_dashboard import SessionDashboard, TrainingStatusData
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
from typing_trainer.ui.settings_widget import SettingsWidget
from typing_trainer.ui.typing_widget import TypingWidget

# Tab indices (Settings is inserted at 0, shifting the others)
_TAB_SETTINGS = 0
_TAB_TRAINING = 1
_TAB_ANALYSIS = 2


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(
        self,
        config: Config,
        profile_name: str = "default",
        profile_dir: "Path | None" = None,
    ) -> None:
        super().__init__()
        self.config = config
        self._profile_name = profile_name
        self._profile_dir = profile_dir
        self.keyboard_layout: KeyboardLayout = load_keyboard(config.keyboard_layout)

        # Core components
        self.db = Database(config.db_path)
        self.db.initialize()
        self.repo = Repository(self.db, warmup=config.warmup_keystrokes)
        self.engine = TypingEngine(config)
        self.text_gen = TextGenerator(config, self.keyboard_layout)
        self.letter_mgr = LetterManager(config, self.keyboard_layout)
        self.spaced_rep = SpacedRepetition(config)
        self.speed_mgr = SpeedManager(config)

        # State
        self._active_letters: dict[str, LetterStats] = {}
        self._current_session: Session | None = None
        self._space_median_rt: float = 0.0

        # Session timeout timer
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setInterval(60_000)  # check every minute
        self._inactivity_timer.timeout.connect(self._check_session_timeout)

        self._load_state()
        self._setup_ui()
        self._ensure_session()
        self._settings_widget.refresh_profile_list(active=self._profile_name)
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
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Top bar: profile info + display mode selector
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(8, 4, 8, 4)

        # Profile name + gear button
        self._profile_label = QLabel(f"Profile: {self._profile_name}")
        self._profile_label.setFont(app_font(10))
        self._profile_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        top_bar.addWidget(self._profile_label)

        gear_btn = QPushButton("\u2699")  # ⚙
        gear_btn.setFont(app_font(12))
        gear_btn.setFixedSize(24, 24)
        gear_btn.setToolTip("Open settings")
        gear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gear_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {COLOR_TEXT_SECONDARY}; }}"
            f"QPushButton:hover {{ color: {COLOR_TEXT_PRIMARY}; }}"
        )
        gear_btn.clicked.connect(lambda: self._main_tabs.setCurrentIndex(_TAB_SETTINGS))
        top_bar.addWidget(gear_btn)

        top_bar.addStretch()

        # Display mode
        display_label = QLabel("Display:")
        display_label.setFont(app_font(10))
        top_bar.addWidget(display_label)

        self._display_mode_combo = QComboBox()
        self._display_mode_combo.setFont(app_font(10))
        self._display_mode_combo.addItem("Basic", DisplayMode.BASIC)
        self._display_mode_combo.addItem("Nerd", DisplayMode.NERD)
        self._display_mode_combo.addItem("Extreme Nerd", DisplayMode.EXTREME_NERD)
        # Default to Nerd
        self._display_mode_combo.setCurrentIndex(1)
        self._display_mode_combo.currentIndexChanged.connect(
            self._on_display_mode_changed
        )
        top_bar.addWidget(self._display_mode_combo)
        outer_layout.addLayout(top_bar)

        # Main content area
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter: main area | sidebar
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Right sidebar (added to splitter after main area below)
        self._sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)

        self._session_dashboard = SessionDashboard()
        sidebar_layout.addWidget(self._session_dashboard)

        self._letter_overview = LetterOverviewWidget()
        sidebar_layout.addWidget(self._letter_overview)

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
        self._summary_widget = RunSummaryWidget(self.config, self.keyboard_layout)
        self._summary_widget.continue_clicked.connect(self._on_continue)
        self._stack.addWidget(self._summary_widget)

        # Tab 0: Settings
        self._settings_widget = SettingsWidget(self.config, self._profile_name)
        self._settings_widget.profile_switch_requested.connect(self._on_profile_switch)
        self._settings_widget.new_profile_created.connect(self._on_new_profile_created)
        self._settings_widget.profile_deleted.connect(self._on_profile_deleted)
        self._settings_widget.runtime_settings_changed.connect(
            self._on_runtime_settings_changed
        )
        self._settings_widget.config_value_changed.connect(self._refresh_dashboard)
        self._main_tabs.addTab(self._settings_widget, "Settings")

        # Tab 1: Training
        self._main_tabs.addTab(self._stack, "Training")

        # Tab 2: Analysis
        self._analytics = AnalyticsWidget(
            config=self.config,
            keyboard_layout=self.keyboard_layout,
        )
        self._main_tabs.addTab(self._analytics, "Analysis")

        # Wire bigram chart selection -> run config + auto-switch to Training
        self._analytics.bigram_chart.bigrams_selected.connect(self._on_bigrams_selected)

        self._splitter.addWidget(self._main_tabs)
        self._splitter.addWidget(self._sidebar)

        # Set initial sizes (main area fills most, sidebar ~300px on right)
        self._splitter.setSizes([700, 300])
        main_layout.addWidget(self._splitter)
        outer_layout.addLayout(main_layout, stretch=1)

        # Show Training tab, config page
        self._main_tabs.setCurrentIndex(_TAB_TRAINING)
        self._stack.setCurrentIndex(0)
        self._config_widget.setFocus()

        # Apply initial display mode
        self._apply_display_mode()

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
            layout=self.config.keyboard_layout,
        )
        self._current_session.touch()
        session_id = self.repo.create_session(self._current_session)
        self._current_session.session_id = session_id

    def _end_session(self) -> None:
        """End the current session."""
        if (
            self._current_session is not None
            and self._current_session.session_id is not None
        ):
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
        if index == _TAB_ANALYSIS:
            self._analytics.refresh(self.repo)

    # ------------------------------------------------------------------
    # Display mode
    # ------------------------------------------------------------------

    def _current_display_mode(self) -> DisplayMode:
        """Get the currently selected display mode."""
        data = self._display_mode_combo.currentData()
        if isinstance(data, DisplayMode):
            return data
        return DisplayMode.NERD

    def _on_display_mode_changed(self, _index: int) -> None:
        """Handle display mode combo change."""
        self._apply_display_mode()

    def _apply_display_mode(self) -> None:
        """Show/hide UI elements based on the current display mode."""
        mode = self._current_display_mode()

        # Sidebar (session dashboard + letter overview)
        self._sidebar.setVisible(mode != DisplayMode.BASIC)

        # Analysis tab
        self._main_tabs.setTabVisible(_TAB_ANALYSIS, mode != DisplayMode.BASIC)

        # Settings: advanced section visibility
        self._settings_widget.set_display_mode(mode)
        self._analytics.set_display_mode(mode)

        # Run summary sections
        self._summary_widget.set_display_mode(mode)

        # Session dashboard (for per-letter bar rendering)
        self._session_dashboard.set_display_mode(mode)

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def _apply_runtime_settings(self) -> None:
        """Rebuild runtime objects after config/layout changes."""
        self.keyboard_layout = load_keyboard(self.config.keyboard_layout)
        self.text_gen = TextGenerator(self.config, self.keyboard_layout)
        self.letter_mgr = LetterManager(self.config, self.keyboard_layout)
        self._summary_widget.set_runtime_dependencies(self.config, self.keyboard_layout)
        self._analytics.set_runtime_dependencies(self.config, self.keyboard_layout)
        self._settings_widget.update_config_display(self.config)
        self._refresh_dashboard()

    def _on_runtime_settings_changed(self) -> None:
        """Handle live changes to language / keyboard layout settings."""
        self._apply_runtime_settings()

    def _on_profile_switch(self, name: str) -> None:
        """Switch to a different user profile."""
        from typing_trainer.main import get_profile_dir, set_active_profile

        # End current session
        self._end_session()

        # Save current config
        if self._profile_dir is not None:
            self.config.save(self._profile_dir / "config.json")

        # Close current DB
        self.db.close()

        # Load new profile
        new_dir = get_profile_dir(name)
        new_config_path = new_dir / "config.json"
        new_config = Config.load(new_config_path)
        new_config.db_path = str(new_dir / "typing_trainer.db")

        # Replace core state
        self.config = new_config
        self._profile_name = name
        self._profile_dir = new_dir
        self.keyboard_layout = load_keyboard(new_config.keyboard_layout)
        self.db = Database(new_config.db_path)
        self.db.initialize()
        self.repo = Repository(self.db, warmup=new_config.warmup_keystrokes)
        self.engine = TypingEngine(new_config)
        self.text_gen = TextGenerator(new_config, self.keyboard_layout)
        self.letter_mgr = LetterManager(new_config, self.keyboard_layout)
        self.spaced_rep = SpacedRepetition(new_config)
        self.speed_mgr = SpeedManager(new_config)

        # Reload state from new DB
        self._load_state()
        self._ensure_session()

        # Update UI
        self._profile_label.setText(f"Profile: {name}")
        self._summary_widget.set_runtime_dependencies(new_config, self.keyboard_layout)
        self._analytics.set_runtime_dependencies(new_config, self.keyboard_layout)
        self._settings_widget.update_config_display(new_config)
        self._settings_widget._profile_name = name
        self._refresh_dashboard()
        self._main_tabs.setCurrentIndex(_TAB_SETTINGS)

        set_active_profile(name)

    def _on_new_profile_created(self, name: str) -> None:
        """Handle creation of a new profile — run the wizard."""
        from typing_trainer.main import get_profile_dir, set_active_profile
        from typing_trainer.ui.new_user_wizard import NewUserWizard

        wizard = NewUserWizard(name, self)
        if not wizard.exec():
            return

        # Create config for the new profile
        profile_dir = get_profile_dir(name)
        profile_dir.mkdir(parents=True, exist_ok=True)
        new_config = Config()
        new_config.language = wizard.language
        new_config.wizard_completed = True
        new_config.db_path = str(profile_dir / "typing_trainer.db")
        new_config.save(profile_dir / "config.json")

        # Initialize DB and letters
        new_db = Database(new_config.db_path)
        new_db.initialize()
        new_repo = Repository(new_db)
        new_mgr = LetterManager(new_config)

        if wizard.skip_to_speed:
            letters = new_mgr.initialize_all_letters()
        else:
            letters = new_mgr.initialize_first_letters(count=2)

        new_repo.save_all_letter_states(letters)
        new_repo.save_active_letter_order(new_mgr.introduction_order)
        new_db.close()

        # Switch to the new profile
        self._settings_widget.refresh_profile_list(active=name)
        self._on_profile_switch(name)

    def _on_profile_deleted(self, name: str) -> None:
        """Handle profile deletion with auto-switch."""
        from typing_trainer.main import delete_profile, list_profiles

        # Determine which profile to switch to
        profiles = list_profiles()
        remaining = [p for p in profiles if p != name]
        if not remaining:
            return  # Should not happen (button is disabled)

        # If deleting the active profile, switch first
        if name == self._profile_name:
            next_profile = remaining[0]
            self._on_profile_switch(next_profile)

        # Now delete
        delete_profile(name)
        self._settings_widget.refresh_profile_list()

    def _check_session_timeout(self) -> None:
        """Check if the session has timed out due to inactivity."""
        if self._current_session is not None and self._current_session.is_expired(
            self.config.session_timeout_minutes
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
        rolling_accuracy_wide = self.repo.get_per_letter_rolling_accuracy(
            active_letter_list, self.config.high_accuracy_window
        )
        for letter, stats in self._active_letters.items():
            acc, count = rolling_accuracy.get(letter, (1.0, 0))
            stats.rolling_error_rate = 1.0 - acc
            stats.rolling_keystroke_count = count
            acc_long, _count_long = rolling_accuracy_long.get(letter, (1.0, 0))
            stats.rolling_error_rate_long = 1.0 - acc_long
            acc_wide, count_wide = rolling_accuracy_wide.get(letter, (1.0, 0))
            stats.rolling_accuracy_wide = acc_wide
            stats.rolling_keystroke_count_wide = count_wide

        # RT statistics for mastery evaluation
        rt_stats = self.repo.get_per_letter_rt_stats(
            active_letter_list, self.config.mastery_rt_window
        )
        space_rt_stats = self.repo.get_per_letter_rt_stats(
            [" "], self.config.mastery_rt_window
        )
        self._space_median_rt = space_rt_stats.get(" ", (0.0, 0.0, 0))[0]

        for letter, stats in self._active_letters.items():
            median, cv, count = rt_stats.get(letter, (0.0, 0.0, 0))
            stats.median_rt = median
            stats.rt_cv = cv
            stats.rt_keystroke_count = count
            stats.rt_factor = (
                median / self._space_median_rt if self._space_median_rt > 0 else 0.0
            )

        # Per-run state recheck — detect degradation/recovery and
        # RT-based mastery transitions.
        if self.letter_mgr.recheck_all_states(
            self._active_letters, self._space_median_rt
        ):
            self.repo.save_all_letter_states(self._active_letters)

        # Letter overview (uses rolling_error_rate_long)
        remaining = [
            ch
            for ch in self.letter_mgr.introduction_order
            if ch not in self._active_letters
        ]
        error_rates = self.repo.get_per_letter_error_rates()
        keystroke_counts = {
            letter: total for letter, (_, total, _) in error_rates.items()
        }
        run_counts = self.repo.get_per_letter_run_counts()
        # Compute weight shares for next run
        w_letters, w_weights = self.text_gen._compute_weights(self._active_letters)
        total_w = sum(w_weights)
        weight_shares = (
            {l: w / total_w for l, w in zip(w_letters, w_weights)}
            if total_w > 0
            else {}
        )
        self._letter_overview.update_display(
            self._active_letters,
            remaining,
            keystroke_counts,
            run_counts,
            weight_shares,
            space_median_rt=self._space_median_rt,
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
            speed_available and len(self._config_widget.get_selected_bigrams()) > 0
        )
        self._config_widget.update_letter_display(
            self._active_letters, speed_available, transition_available
        )

        # Session dashboard — build TrainingStatusData
        session_runs = 0
        session_keystrokes = 0
        session_training_s = 0
        session_elapsed_s = 0
        if self._current_session is not None:
            session_runs = self._current_session.run_count
            session_keystrokes = self._current_session.total_cognitive_keystrokes
            for run in self._current_session.runs:
                if run.start_time is not None and run.end_time is not None:
                    session_training_s += int(
                        (run.end_time - run.start_time).total_seconds()
                    )
            if self._current_session.start_time is not None:
                session_elapsed_s = int(
                    (datetime.now() - self._current_session.start_time).total_seconds()
                )

        status_data = TrainingStatusData(
            session_runs=session_runs,
            session_keystrokes=session_keystrokes,
            session_training_s=session_training_s,
            session_elapsed_s=session_elapsed_s,
            today_runs=self.repo.get_runs_today(),
            today_keystrokes=self.repo.get_keystrokes_today(),
            today_training_s=self.repo.get_training_time_today(),
            today_elapsed_s=self.repo.get_elapsed_time_today(),
            total_runs=self.repo.get_total_runs(),
            total_keystrokes=self.repo.get_total_keystrokes_all(),
            total_training_s=self.repo.get_total_training_time(),
            total_elapsed_s=self.repo.get_total_elapsed_time(),
        )
        self._session_dashboard.update_session_info(status_data)

        # Advancement check — only relearning-mode keystrokes count
        total_keystrokes_relearning = self.repo.get_total_keystrokes_relearning()
        rolling_accuracy_relearning = self.repo.get_per_letter_rolling_accuracy(
            active_letter_list,
            self.config.advancement_accuracy_window,
            learn_keys_only=True,
        )
        advancement = self.letter_mgr.check_advancement(
            self._active_letters,
            rolling_accuracy_relearning,
            total_keystrokes_relearning,
        )
        blocked_letters = [
            p.letter
            for p in advancement.per_letter_progress
            if p.has_enough_data and not p.meets_accuracy
        ]
        error_window: dict[str, list[bool]] = {}
        if blocked_letters:
            error_window = self.repo.get_per_letter_error_window(
                blocked_letters,
                self.config.advancement_accuracy_window,
                learn_keys_only=True,
            )
        self._session_dashboard.update_advancement(
            advancement, error_window, space_median_rt=self._space_median_rt
        )

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
            alerts.append(f"Letters due for review: {', '.join(due_letters)}")
        if advancement.can_advance and advancement.next_letter:
            alerts.append(f"Ready to introduce letter '{advancement.next_letter}'!")
        self._config_widget.set_alerts(alerts)

        # Update settings profile info
        self._settings_widget.set_profile_info(
            runs=self.repo.get_total_runs(),
            keystrokes=self.repo.get_total_keystrokes_all(),
            letters=len(self._active_letters),
        )

    def _on_bigrams_selected(self, bigrams: list[tuple[str, str]]) -> None:
        """Handle bigram selection from the analytics bigram chart.

        Transfers the selection to the run config widget, switches to
        the Training tab, and sets the preset to Smooth Pairs.
        """
        self._config_widget.set_selected_bigrams(bigrams)
        # Switch to Training tab
        self._main_tabs.setCurrentIndex(_TAB_TRAINING)
        self._stack.setCurrentIndex(0)
        self._config_widget.setFocus()
        # Auto-select Smooth Pairs preset
        self._config_widget.select_preset("Smooth Pairs")

    def _on_start_run(
        self, length: int, mode: RunMode, practice_type: PracticeType
    ) -> None:
        """Start a new typing run."""
        self._ensure_session()
        if self._current_session is not None:
            self._current_session.touch()

        # Determine fail threshold
        fail_threshold = self.letter_mgr.get_fail_threshold(self._active_letters, mode)

        # Set target bigrams on text generator for transition mode
        if mode == RunMode.TRANSITION:
            bigrams = self._config_widget.get_selected_bigrams()
            self.text_gen.set_target_bigrams(bigrams)

        # Generate text using selected letters (user may have deselected some)
        selected_letters = self._config_widget.get_selected_letters()
        lowercase_only = self._config_widget.get_lowercase_only()
        capitalize_count = self._config_widget.get_capitalize_count()
        target_text = self.text_gen.generate(
            practice_type,
            length,
            selected_letters,
            lowercase_only=lowercase_only,
            capitalize_count=capitalize_count,
        )

        if not target_text:
            return

        # Start engine
        self.engine.start_run(target_text, mode, practice_type, fail_threshold)

        # Create typing widget
        highlight_letters = self._config_widget.get_highlight_letters()
        single_letter = self._config_widget.get_single_letter_mode()
        show_prev = self._config_widget.get_show_prev_result()
        typing_widget = TypingWidget(
            self.engine,
            highlight_letters=highlight_letters,
            single_letter_mode=single_letter,
            show_prev_result=show_prev,
        )
        typing_widget.run_finished.connect(self._on_run_finished)
        typing_widget.run_aborted.connect(self._on_run_aborted)

        # Replace in stack
        old = self._stack.widget(1)
        assert old is not None
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(1, typing_widget)

        self._main_tabs.setCurrentIndex(_TAB_TRAINING)
        self._main_tabs.setTabEnabled(_TAB_ANALYSIS, False)
        self._main_tabs.setTabEnabled(_TAB_SETTINGS, False)
        self._display_mode_combo.setEnabled(False)
        self._stack.setCurrentIndex(1)
        typing_widget.start_run()

    def _check_and_apply_advancement(self) -> None:
        """Check advancement criteria and introduce next letter if ready.

        Only relearning-mode keystrokes count toward letter unlocking
        (both rolling accuracy AND keystroke volume threshold).
        """
        active_letter_list = list(self._active_letters.keys())
        rolling_accuracy = self.repo.get_per_letter_rolling_accuracy(
            active_letter_list,
            self.config.advancement_accuracy_window,
            learn_keys_only=True,
        )
        total_keystrokes = self.repo.get_total_keystrokes_relearning()
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

        # Track whether this run required capitalization (Shift key).
        result.capitalize = self.config.require_capitalization and any(
            c.isupper() for c in result.target_text
        )

        # Save to database
        if (
            self._current_session is not None
            and self._current_session.session_id is not None
        ):
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

        # Update per-letter error rates in active letters from this run
        for letter, per_letter in result.per_letter.items():
            if letter in self._active_letters:
                self._active_letters[letter].error_rate_latest = per_letter.error_rate
                self._active_letters[letter].last_practiced = datetime.now()

        # Process speed run if applicable
        speed_result = None
        if result.mode == RunMode.SPEED:
            speed_result = self.speed_mgr.process_speed_run(result)
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

        # Re-enable controls locked during the run
        self._main_tabs.setTabEnabled(_TAB_ANALYSIS, True)
        self._main_tabs.setTabEnabled(_TAB_SETTINGS, True)
        self._display_mode_combo.setEnabled(True)
        self._refresh_dashboard()

    def _on_run_aborted(self) -> None:
        """Handle user-initiated run abort (Escape).

        The run is discarded entirely — nothing is saved to the database,
        session stats are not updated, and no letter state changes occur.
        """
        self._main_tabs.setTabEnabled(_TAB_ANALYSIS, True)
        self._main_tabs.setTabEnabled(_TAB_SETTINGS, True)
        self._display_mode_combo.setEnabled(True)
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
        self.repo.save_speed_state(self.speed_mgr.target_wpm, self.speed_mgr.best_wpm)
        self.db.close()
        super().closeEvent(event)
