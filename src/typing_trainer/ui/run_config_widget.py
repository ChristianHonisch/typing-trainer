"""Pre-run configuration widget with preset-based training modes.

Presets:
  - Learn Keys: motor foundation, unlock new letters (random strings)
  - Fix Keys: error-prone letter focus (random strings, auto-selected)
  - Build Speed: real words, accuracy matters, speed grows (random words)
  - Smooth Pairs: drill specific slow bigrams (bigram words)
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.config import Config
from typing_trainer.models.letter_state import (
    LetterState,
    LetterStats,
    PracticeType,
    RunMode,
)
from typing_trainer.ui.theme import (
    COLOR_ALERT,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BTN_DISABLED_BG,
    COLOR_BTN_DISABLED_TEXT,
    COLOR_BTN_HOVER,
    COLOR_BTN_PRESSED,
    COLOR_BTN_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_SECONDARY,
    STATE_COLORS,
    app_font,
    make_selectable,
)

_STABLE_STATES = frozenset({LetterState.STABLE, LetterState.MASTERED})

# Preset descriptions (shown after selection)
_PRESET_DESCRIPTIONS: dict[str, str] = {
    "Learn Keys": (
        "The motor foundation. You are learning where each key lives. "
        "Used to unlock new letters."
    ),
    "Fix Keys": (
        "Optional: the error-prone letter focus. You already know the keys, "
        "some just need repair."
    ),
    "Build Speed": ("Type real words, accuracy still matters, speed grows naturally."),
    "Smooth Pairs": ("Drill specific slow bigrams, words containing those pairs."),
}

# Preset -> (RunMode, PracticeType, default_length)
_PRESET_CONFIG: dict[str, tuple[RunMode, PracticeType, int]] = {
    "Learn Keys": (RunMode.RELEARNING, PracticeType.RANDOM_STRINGS, 120),
    "Fix Keys": (RunMode.RELEARNING, PracticeType.FIX_KEYS, 60),
    "Build Speed": (RunMode.SPEED, PracticeType.RANDOM_WORDS, 120),
    "Smooth Pairs": (RunMode.TRANSITION, PracticeType.BIGRAM_WORDS, 120),
}


class RunConfigWidget(QWidget):
    """Widget for configuring and starting a typing run.

    Signals:
        start_run: emitted with (run_length, mode, practice_type) when start is clicked.
    """

    start_run = pyqtSignal(int, object, object)

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._active_letters: dict[str, LetterStats] = {}
        self._speed_available = False
        self._transition_available = False
        self._selected_bigrams: list[tuple[str, str]] = []

        # Letter selection state
        self._selected_letters: set[str] = set()
        self._letter_buttons: dict[str, QPushButton] = {}

        # Rest timer state
        self._rest_remaining = 0
        self._rest_timer = QTimer(self)
        self._rest_timer.setInterval(1000)
        self._rest_timer.timeout.connect(self._on_rest_tick)

        # Suppress auto-switch feedback loop
        self._suppress_letter_toggle_switch = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Typing Trainer")
        title.setFont(app_font(24, bold=True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(10)

        # Letter set display + selection toggles
        self._letter_group = QGroupBox("Active Letters")
        self._letter_group.setFont(app_font(11))
        letter_layout = QVBoxLayout(self._letter_group)

        self._letter_display = QLabel("")
        self._letter_display.setFont(app_font(14))
        self._letter_display.setWordWrap(True)
        make_selectable(self._letter_display)
        letter_layout.addWidget(self._letter_display)

        # Letter toggle buttons row
        self._toggle_row = QHBoxLayout()
        self._toggle_row.setSpacing(4)
        self._toggle_row.addStretch()  # trailing stretch
        letter_layout.addLayout(self._toggle_row)

        layout.addWidget(self._letter_group)

        # Alerts
        self._alert_label = QLabel("")
        self._alert_label.setFont(app_font(11))
        self._alert_label.setStyleSheet(f"color: {COLOR_ALERT};")
        self._alert_label.setWordWrap(True)
        make_selectable(self._alert_label)
        self._alert_label.hide()
        layout.addWidget(self._alert_label)

        # Bigram selection display
        self._bigram_label = QLabel("")
        self._bigram_label.setFont(app_font(11))
        self._bigram_label.setWordWrap(True)
        make_selectable(self._bigram_label)
        self._bigram_label.hide()
        layout.addWidget(self._bigram_label)

        # --- Configuration controls ---
        config_layout = QHBoxLayout()

        # Run length
        length_group = QVBoxLayout()
        length_label = QLabel("Keystrokes:")
        length_label.setFont(app_font(11))
        length_group.addWidget(length_label)

        self._length_spin = QSpinBox()
        self._length_spin.setRange(self.config.run_length_minimum, 1000)
        self._length_spin.setValue(120)
        self._length_spin.setSingleStep(10)
        self._length_spin.setFont(app_font(12))
        length_group.addWidget(self._length_spin)
        config_layout.addLayout(length_group)

        # Preset
        preset_group = QVBoxLayout()
        preset_label = QLabel("Preset:")
        preset_label.setFont(app_font(11))
        preset_group.addWidget(preset_label)

        self._preset_combo = QComboBox()
        self._preset_combo.setFont(app_font(12))
        self._preset_combo.addItems(list(_PRESET_CONFIG.keys()))
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_group.addWidget(self._preset_combo)

        self._preset_warning = QLabel("")
        self._preset_warning.setFont(app_font(9))
        self._preset_warning.setStyleSheet(f"color: {COLOR_ALERT};")
        self._preset_warning.setWordWrap(True)
        self._preset_warning.hide()
        preset_group.addWidget(self._preset_warning)

        config_layout.addLayout(preset_group)

        layout.addLayout(config_layout)

        # Preset description
        self._preset_desc = QLabel("")
        self._preset_desc.setFont(app_font(10))
        self._preset_desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._preset_desc.setWordWrap(True)
        layout.addWidget(self._preset_desc)

        # --- All keys option (Build Speed / Smooth Pairs) ---
        all_keys_layout = QHBoxLayout()
        all_keys_layout.setSpacing(6)

        self._all_letters_cb = QCheckBox("All keys")
        self._all_letters_cb.setFont(app_font(10))
        self._all_letters_cb.setChecked(False)
        self._all_letters_cb.setToolTip(
            "Use the full alphabet (a\u2013z + space). For people who "
            "already know the key positions and want to skip Learn Keys."
        )
        self._all_letters_cb.stateChanged.connect(self._on_all_letters_changed)
        all_keys_layout.addWidget(self._all_letters_cb)
        all_keys_layout.addStretch()

        self._all_letters_widgets = [self._all_letters_cb]

        layout.addLayout(all_keys_layout)

        # --- Fix Keys controls (worst N / best M) ---
        self._fix_keys_row = QHBoxLayout()
        self._fix_keys_row.setSpacing(6)

        fix_worst_label = QLabel("Worst:")
        fix_worst_label.setFont(app_font(10))
        self._fix_keys_row.addWidget(fix_worst_label)

        self._fix_worst_spin = QSpinBox()
        self._fix_worst_spin.setFont(app_font(10))
        self._fix_worst_spin.setRange(1, 26)
        self._fix_worst_spin.setValue(3)
        self._fix_worst_spin.setSingleStep(1)
        self._fix_worst_spin.setToolTip(
            "Number of worst letters (by accuracy) to include"
        )
        self._fix_worst_spin.valueChanged.connect(self._on_fix_keys_changed)
        self._fix_keys_row.addWidget(self._fix_worst_spin)

        self._fix_keys_row.addSpacing(10)

        fix_best_label = QLabel("Best:")
        fix_best_label.setFont(app_font(10))
        self._fix_keys_row.addWidget(fix_best_label)

        self._fix_best_spin = QSpinBox()
        self._fix_best_spin.setFont(app_font(10))
        self._fix_best_spin.setRange(0, 26)
        self._fix_best_spin.setValue(2)
        self._fix_best_spin.setSingleStep(1)
        self._fix_best_spin.setToolTip(
            "Number of best letters (by accuracy) to include as anchors"
        )
        self._fix_best_spin.valueChanged.connect(self._on_fix_keys_changed)
        self._fix_keys_row.addWidget(self._fix_best_spin)

        self._fix_keys_row.addStretch()

        # Collect fix keys widgets for show/hide
        self._fix_keys_widgets = [
            fix_worst_label,
            self._fix_worst_spin,
            fix_best_label,
            self._fix_best_spin,
        ]

        layout.addLayout(self._fix_keys_row)

        # --- Highlight weak letters option (Learn Keys only) ---
        highlight_layout = QHBoxLayout()
        highlight_layout.setSpacing(6)

        self._highlight_cb = QCheckBox("Highlight weak")
        self._highlight_cb.setFont(app_font(10))
        self._highlight_cb.setChecked(True)
        highlight_layout.addWidget(self._highlight_cb)

        self._highlight_count_spin = QSpinBox()
        self._highlight_count_spin.setFont(app_font(10))
        self._highlight_count_spin.setRange(0, 10)
        self._highlight_count_spin.setValue(3)
        self._highlight_count_spin.setSingleStep(1)
        highlight_layout.addWidget(self._highlight_count_spin)

        self._highlight_suffix = QLabel("letters")
        self._highlight_suffix.setFont(app_font(10))
        highlight_layout.addWidget(self._highlight_suffix)

        highlight_layout.addStretch()

        self._highlight_widgets = [
            self._highlight_cb,
            self._highlight_count_spin,
            self._highlight_suffix,
        ]

        layout.addLayout(highlight_layout)

        # --- Single letter mode (Learn Keys / Fix Keys) ---
        single_letter_layout = QHBoxLayout()
        single_letter_layout.setSpacing(6)

        self._single_letter_cb = QCheckBox("Single letter mode")
        self._single_letter_cb.setFont(app_font(10))
        self._single_letter_cb.setChecked(False)
        self._single_letter_cb.setToolTip(
            "Show only the current letter in large font. "
            "Helps focus on individual key positions."
        )
        single_letter_layout.addWidget(self._single_letter_cb)

        self._show_prev_result_cb = QCheckBox("Show previous result")
        self._show_prev_result_cb.setFont(app_font(10))
        self._show_prev_result_cb.setChecked(False)
        self._show_prev_result_cb.setEnabled(False)
        self._show_prev_result_cb.setToolTip(
            "Show the result of the last keystroke above the current letter."
        )
        self._single_letter_cb.stateChanged.connect(
            lambda checked: self._show_prev_result_cb.setEnabled(bool(checked))
        )
        single_letter_layout.addWidget(self._show_prev_result_cb)

        single_letter_layout.addStretch()

        self._single_letter_widgets = [
            self._single_letter_cb,
            self._show_prev_result_cb,
        ]

        layout.addLayout(single_letter_layout)

        layout.addStretch()

        # Rest timer label (shown after a run completes)
        self._rest_label = QLabel("")
        self._rest_label.setFont(app_font(12))
        self._rest_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rest_label.hide()
        layout.addWidget(self._rest_label)

        # Start button
        self._start_btn = QPushButton("Start Run")
        self._start_btn.setFont(app_font(16, bold=True))
        self._start_btn.setMinimumHeight(50)
        self._start_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BTN_PRIMARY};
                color: {COLOR_TEXT_BRIGHT};
                border: none;
                border-radius: 5px;
                padding: 10px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_BTN_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_BTN_PRESSED};
            }}
            """
        )
        self._start_btn.clicked.connect(self._on_start)
        layout.addWidget(self._start_btn)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Apply initial preset state
        self._apply_preset_ui()

    # ------------------------------------------------------------------
    # Preset handling
    # ------------------------------------------------------------------

    def _current_preset(self) -> str:
        return self._preset_combo.currentText()

    def _on_preset_changed(self, _index: int) -> None:
        """Handle preset selection change."""
        preset = self._current_preset()
        cfg = _PRESET_CONFIG.get(preset)
        if cfg is not None:
            _mode, _ptype, default_length = cfg
            self._length_spin.setValue(default_length)

        self._apply_preset_ui()
        self._apply_default_selection()
        self._update_preset_warning()

    def _apply_preset_ui(self) -> None:
        """Show/hide UI controls appropriate for the current preset."""
        preset = self._current_preset()

        # Description
        self._preset_desc.setText(_PRESET_DESCRIPTIONS.get(preset, ""))

        # Fix Keys controls
        is_fix = preset == "Fix Keys"
        for w in self._fix_keys_widgets:
            w.setVisible(is_fix)

        # Highlight weak (Learn Keys only)
        is_learn = preset == "Learn Keys"
        for w in self._highlight_widgets:
            w.setVisible(is_learn)

        # Single letter mode (Learn Keys / Fix Keys only)
        is_relearning = preset in ("Learn Keys", "Fix Keys")
        for w in self._single_letter_widgets:
            w.setVisible(is_relearning)

        # All keys checkbox (Build Speed / Smooth Pairs only)
        is_speed_or_transition = preset in ("Build Speed", "Smooth Pairs")
        for w in self._all_letters_widgets:
            w.setVisible(is_speed_or_transition)

        # Enable/disable toggle buttons based on "All keys" state
        all_keys = is_speed_or_transition and self._all_letters_cb.isChecked()
        for btn in self._letter_buttons.values():
            btn.setEnabled(not all_keys)

        # Bigram display (Smooth Pairs only)
        self._update_bigram_display()

    def _update_preset_warning(self) -> None:
        """Show warnings for presets whose prerequisites aren't met."""
        preset = self._current_preset()
        if preset == "Build Speed" and not self._speed_available:
            self._preset_warning.setText(
                "Keys are not settled. Speed training is not recommended."
            )
            self._preset_warning.show()
        elif preset == "Smooth Pairs":
            if not self._speed_available:
                self._preset_warning.setText(
                    "Keys are not settled. Transition training is not recommended."
                )
                self._preset_warning.show()
            elif not self._selected_bigrams:
                self._preset_warning.setText(
                    "No bigrams selected. Select bigrams in Analysis > Bigrams."
                )
                self._preset_warning.show()
            else:
                self._preset_warning.hide()
        else:
            self._preset_warning.hide()

    def get_mode_and_practice_type(self) -> tuple[RunMode, PracticeType]:
        """Get the RunMode and PracticeType for the current preset."""
        preset = self._current_preset()
        cfg = _PRESET_CONFIG.get(preset)
        if cfg is not None:
            return cfg[0], cfg[1]
        return RunMode.RELEARNING, PracticeType.RANDOM_STRINGS

    # ------------------------------------------------------------------
    # Letter display and selection
    # ------------------------------------------------------------------

    def update_letter_display(
        self,
        active_letters: dict[str, LetterStats],
        speed_available: bool = False,
        transition_available: bool = False,
    ) -> None:
        """Update the letter set display and rebuild toggle buttons."""
        self._active_letters = active_letters
        self._speed_available = speed_available
        self._transition_available = transition_available

        if not active_letters:
            self._letter_display.setText("No letters active")
            self._rebuild_letter_toggles()
            return

        # Color-coded letter overview
        parts: list[str] = []
        for letter in sorted(active_letters.keys()):
            stats = active_letters[letter]
            color = STATE_COLORS.get(stats.state, COLOR_TEXT_BRIGHT)
            parts.append(f'<span style="color: {color};">{letter}</span>')

        self._letter_display.setText(
            '<span style="font-size: 16pt; letter-spacing: 6px;">'
            + " ".join(parts)
            + "</span>"
        )

        self._rebuild_letter_toggles()
        self._update_preset_warning()
        self._update_highlight_max()

    def select_preset(self, name: str) -> None:
        """Programmatically select a preset by display name.

        Does nothing if *name* is not found in the combo box.
        """
        idx = self._preset_combo.findText(name)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _rebuild_letter_toggles(self) -> None:
        """Rebuild the letter toggle buttons to match current active letters."""
        # Remove old buttons
        for btn in self._letter_buttons.values():
            self._toggle_row.removeWidget(btn)
            btn.deleteLater()
        self._letter_buttons.clear()

        # Prune selection: drop letters no longer active
        self._selected_letters &= set(self._active_letters.keys())

        # Learn Keys: always include all active letters so newly
        # unlocked letters are auto-selected immediately.
        preset = self._current_preset()
        if preset == "Learn Keys":
            self._selected_letters = set(self._active_letters.keys())
        # All keys: full alphabet regardless of what's unlocked.
        elif (
            preset in ("Build Speed", "Smooth Pairs")
            and self._all_letters_cb.isChecked()
        ):
            self._selected_letters = set("abcdefghijklmnopqrstuvwxyz ")

        # If selection is now empty (e.g. first call), apply preset default
        if not self._selected_letters and self._active_letters:
            self._apply_default_selection()

        # Build buttons in sorted order
        all_keys = (
            preset in ("Build Speed", "Smooth Pairs")
            and self._all_letters_cb.isChecked()
        )
        for letter in sorted(self._active_letters.keys()):
            btn = QPushButton(letter)
            btn.setFont(app_font(12, bold=True))
            btn.setFixedSize(32, 32)
            btn.setCheckable(True)
            btn.setChecked(letter in self._selected_letters)
            btn.setEnabled(not all_keys)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(
                lambda checked, l=letter: self._on_letter_toggled(l, checked)
            )
            self._letter_buttons[letter] = btn
            # Insert before the trailing stretch
            self._toggle_row.insertWidget(self._toggle_row.count() - 1, btn)

        self._update_toggle_styles()
        self._update_start_button()

    def _apply_default_selection(self) -> None:
        """Set the letter selection to the preset-appropriate default.

        - Learn Keys: all active letters
        - Fix Keys: auto-select worst N + best M
        - Build Speed / Smooth Pairs: only STABLE + MASTERED letters
        """
        preset = self._current_preset()
        if preset in ("Build Speed", "Smooth Pairs"):
            if self._all_letters_cb.isChecked():
                # Full alphabet + space — for users who already know the keys
                self._selected_letters = set("abcdefghijklmnopqrstuvwxyz ")
            else:
                self._selected_letters = {
                    letter
                    for letter, stats in self._active_letters.items()
                    if stats.state in _STABLE_STATES
                }
        elif preset == "Fix Keys":
            self._apply_fix_keys_selection()
        else:
            # Learn Keys: all
            self._selected_letters = set(self._active_letters.keys())

        # Sync button checked state
        for letter, btn in self._letter_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(letter in self._selected_letters)
            btn.blockSignals(False)

        self._update_toggle_styles()
        self._update_start_button()

    def _apply_fix_keys_selection(self) -> None:
        """Auto-select worst N + best M letters by rolling error rate."""
        n_worst = self._fix_worst_spin.value()
        n_best = self._fix_best_spin.value()

        # Sort by error rate descending (worst first)
        ranked = sorted(
            self._active_letters.items(),
            key=lambda t: t[1].rolling_error_rate,
            reverse=True,
        )

        selected: set[str] = set()

        # Worst N
        for letter, _stats in ranked[:n_worst]:
            selected.add(letter)

        # Best M (from the end, skip any already selected)
        if n_best > 0:
            best_candidates = [
                letter for letter, _ in reversed(ranked) if letter not in selected
            ]
            for letter in best_candidates[:n_best]:
                selected.add(letter)

        self._selected_letters = selected

    def _on_all_letters_changed(self) -> None:
        """Handle 'All keys' checkbox change in Build Speed / Smooth Pairs.

        When checked, all 26 letters + space are used and the toggle
        buttons are disabled (no manual selection).  When unchecked,
        the default STABLE/MASTERED selection is restored.
        """
        preset = self._current_preset()
        if preset not in ("Build Speed", "Smooth Pairs"):
            return
        all_keys = self._all_letters_cb.isChecked()
        self._apply_default_selection()
        # Sync + enable/disable buttons
        for letter, btn in self._letter_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(letter in self._selected_letters)
            btn.setEnabled(not all_keys)
            btn.blockSignals(False)
        self._update_toggle_styles()
        self._update_start_button()

    def _on_fix_keys_changed(self) -> None:
        """Handle worst/best spinbox value changes in Fix Keys preset."""
        if self._current_preset() != "Fix Keys":
            return
        self._apply_fix_keys_selection()
        # Sync buttons
        for letter, btn in self._letter_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(letter in self._selected_letters)
            btn.blockSignals(False)
        self._update_toggle_styles()
        self._update_start_button()
        self._update_highlight_max()

    def _on_letter_toggled(self, letter: str, checked: bool) -> None:
        """Handle a letter toggle button click."""
        if checked:
            self._selected_letters.add(letter)
        else:
            self._selected_letters.discard(letter)

        # Auto-switch from Learn Keys to Fix Keys if user deselects a letter
        if (
            not self._suppress_letter_toggle_switch
            and not checked
            and self._current_preset() == "Learn Keys"
        ):
            self._suppress_letter_toggle_switch = True
            self._preset_combo.blockSignals(True)
            idx = self._preset_combo.findText("Fix Keys")
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
            self._preset_combo.blockSignals(False)
            # Apply Fix Keys UI but keep the current manual selection
            self._apply_preset_ui()
            self._update_preset_warning()
            self._suppress_letter_toggle_switch = False

        self._update_toggle_styles()
        self._update_start_button()
        self._update_highlight_max()

    def _update_toggle_styles(self) -> None:
        """Update visual styling of toggle buttons based on selection."""
        for letter, btn in self._letter_buttons.items():
            stats = self._active_letters.get(letter)
            if stats is None:
                continue
            color = STATE_COLORS.get(stats.state, COLOR_TEXT_BRIGHT)
            if letter in self._selected_letters:
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {COLOR_BG_SECONDARY};
                        color: {color};
                        border: 2px solid {color};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {COLOR_BG_TERTIARY};
                    }}
                    """
                )
            else:
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {COLOR_BTN_DISABLED_BG};
                        color: {COLOR_BTN_DISABLED_TEXT};
                        border: 2px solid {COLOR_BG_TERTIARY};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {COLOR_BG_TERTIARY};
                        color: {color};
                    }}
                    """
                )

    def _update_start_button(self) -> None:
        """Enable/disable the start button based on letter selection."""
        self._start_btn.setEnabled(len(self._selected_letters) > 0)

    def get_selected_letters(self) -> dict[str, LetterStats]:
        """Get the currently selected letters with their stats.

        When "All keys" is checked (Build Speed / Smooth Pairs), this
        returns all 26 letters + space.  Letters that haven't been
        formally introduced yet get a synthetic :class:`LetterStats`
        with neutral defaults (STABLE state, zero error rate) so the
        text generator can weight them equally alongside real letters.
        """
        if (
            self._current_preset() in ("Build Speed", "Smooth Pairs")
            and self._all_letters_cb.isChecked()
        ):
            result: dict[str, LetterStats] = {}
            for letter in "abcdefghijklmnopqrstuvwxyz ":
                if letter in self._active_letters:
                    result[letter] = self._active_letters[letter]
                else:
                    result[letter] = LetterStats(
                        letter=letter,
                        state=LetterState.STABLE,
                    )
            return result
        return {
            letter: stats
            for letter, stats in self._active_letters.items()
            if letter in self._selected_letters
        }

    def _update_highlight_max(self) -> None:
        """Clamp the highlight spinbox max to (non-space selected letters - 1)."""
        non_space = sum(1 for l in self._selected_letters if l != " ")
        new_max = max(0, non_space - 1)
        self._highlight_count_spin.setMaximum(new_max)

    def get_highlight_letters(self) -> set[str]:
        """Return the set of letters that should be highlighted as weak.

        Only available in Learn Keys preset.  Returns empty set for
        other presets or when the checkbox is unchecked.
        """
        if self._current_preset() != "Learn Keys":
            return set()
        if not self._highlight_cb.isChecked():
            return set()
        n = self._highlight_count_spin.value()
        if n <= 0:
            return set()

        # Only consider selected non-space letters
        candidates = [
            (letter, stats)
            for letter, stats in self._active_letters.items()
            if letter in self._selected_letters and letter != " "
        ]
        # Sort by rolling_error_rate descending (worst first)
        candidates.sort(key=lambda t: t[1].rolling_error_rate, reverse=True)
        return {letter for letter, _ in candidates[:n]}

    # ------------------------------------------------------------------
    # Alerts, bigrams
    def get_single_letter_mode(self) -> bool:
        """Whether single-letter display mode is enabled."""
        return self._single_letter_cb.isChecked()

    def get_show_prev_result(self) -> bool:
        """Whether to show the previous keystroke result in single-letter mode."""
        return (
            self._single_letter_cb.isChecked() and self._show_prev_result_cb.isChecked()
        )

    # ------------------------------------------------------------------

    def set_alerts(self, alerts: list[str]) -> None:
        """Show alerts (e.g., review due, degradation warnings)."""
        if alerts:
            self._alert_label.setText("\n".join(alerts))
            self._alert_label.show()
        else:
            self._alert_label.hide()

    # ------------------------------------------------------------------
    # Keyboard, bigrams, rest timer
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        """Allow starting a run by pressing Return/Enter."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_start()
        else:
            super().keyPressEvent(event)

    def set_selected_bigrams(self, bigrams: list[tuple[str, str]]) -> None:
        """Set the selected bigrams for transition training."""
        self._selected_bigrams = list(bigrams)
        self._transition_available = len(bigrams) > 0
        self._update_bigram_display()

    def get_selected_bigrams(self) -> list[tuple[str, str]]:
        """Get the currently selected bigrams."""
        return list(self._selected_bigrams)

    def _update_bigram_display(self) -> None:
        """Show/hide the bigram selection label based on preset."""
        preset = self._current_preset()
        if preset == "Smooth Pairs" and self._selected_bigrams:
            bigram_strs = []
            for a, b in self._selected_bigrams:
                a_label = "SPC" if a == " " else a
                b_label = "SPC" if b == " " else b
                bigram_strs.append(f"{a_label}\u2192{b_label}")
            self._bigram_label.setText(f"Target bigrams: {', '.join(bigram_strs)}")
            self._bigram_label.setStyleSheet("color: #44aaff;")
            self._bigram_label.show()
        else:
            self._bigram_label.hide()

    def start_rest_timer(self, seconds: int) -> None:
        """Start or resume the rest suggestion countdown."""
        self._rest_remaining = seconds
        self._update_rest_display()
        self._rest_label.show()
        if seconds > 0:
            self._rest_timer.start()
        else:
            self._rest_timer.stop()

    def _on_rest_tick(self) -> None:
        self._rest_remaining = max(0, self._rest_remaining - 1)
        self._update_rest_display()
        if self._rest_remaining <= 0:
            self._rest_timer.stop()

    def _update_rest_display(self) -> None:
        if self._rest_remaining > 0:
            self._rest_label.setText(f"Suggested rest: {self._rest_remaining}s")
            self._rest_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        else:
            self._rest_label.setText("Rest complete")
            self._rest_label.setStyleSheet(f"color: {COLOR_SUCCESS};")

    def _on_start(self) -> None:
        if not self._selected_letters:
            return
        self._rest_timer.stop()
        self._rest_label.hide()
        length = self._length_spin.value()
        mode, practice_type = self.get_mode_and_practice_type()
        self.start_run.emit(length, mode, practice_type)
