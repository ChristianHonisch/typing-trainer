"""Pre-run configuration widget.

Allows the user to set:
- Run length (number of keystrokes)
- Mode (relearning / speed / transition)
- Practice type (random_strings / random_words / sentences / bigram_words)
- Which active letters to include in the run

Also shows the active letter set and any review alerts.
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
from typing_trainer.models.letter_state import LetterState, LetterStats, PracticeType, RunMode
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

        # Configuration controls
        config_layout = QHBoxLayout()

        # Run length
        length_group = QVBoxLayout()
        length_label = QLabel("Keystrokes:")
        length_label.setFont(app_font(11))
        length_group.addWidget(length_label)

        self._length_spin = QSpinBox()
        self._length_spin.setRange(
            self.config.run_length_minimum, 1000
        )
        self._length_spin.setValue(self.config.run_length_default_relearning)
        self._length_spin.setSingleStep(10)
        self._length_spin.setFont(app_font(12))
        length_group.addWidget(self._length_spin)
        config_layout.addLayout(length_group)

        # Mode
        mode_group = QVBoxLayout()
        mode_label = QLabel("Mode:")
        mode_label.setFont(app_font(11))
        mode_group.addWidget(mode_label)

        self._mode_combo = QComboBox()
        self._mode_combo.setFont(app_font(12))
        self._mode_combo.addItem("Relearning", RunMode.RELEARNING)
        self._mode_combo.addItem("Speed", RunMode.SPEED)
        self._mode_combo.addItem("Transition", RunMode.TRANSITION)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_group.addWidget(self._mode_combo)

        self._mode_warning = QLabel("")
        self._mode_warning.setFont(app_font(9))
        self._mode_warning.setStyleSheet(f"color: {COLOR_ALERT};")
        self._mode_warning.setWordWrap(True)
        self._mode_warning.hide()
        mode_group.addWidget(self._mode_warning)

        config_layout.addLayout(mode_group)

        # Practice type
        type_group = QVBoxLayout()
        type_label = QLabel("Practice:")
        type_label.setFont(app_font(11))
        type_group.addWidget(type_label)

        self._type_combo = QComboBox()
        self._type_combo.setFont(app_font(12))
        self._type_combo.addItem("Random Strings", PracticeType.RANDOM_STRINGS)
        self._type_combo.addItem("Random Words", PracticeType.RANDOM_WORDS)
        self._type_combo.addItem("Sentences", PracticeType.SENTENCES)
        type_group.addWidget(self._type_combo)
        config_layout.addLayout(type_group)

        layout.addLayout(config_layout)

        # Highlight weak letters option
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

        highlight_suffix = QLabel("letters")
        highlight_suffix.setFont(app_font(10))
        highlight_layout.addWidget(highlight_suffix)

        highlight_layout.addStretch()
        layout.addLayout(highlight_layout)

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
        self._update_mode_warning()
        self._update_practice_types()
        self._update_highlight_max()

    def _rebuild_letter_toggles(self) -> None:
        """Rebuild the letter toggle buttons to match current active letters.

        Preserves the current selection where possible (only removes letters
        that are no longer active).  Does NOT reset the selection to the
        mode default — that only happens on explicit mode change.
        """
        # Remove old buttons
        for btn in self._letter_buttons.values():
            self._toggle_row.removeWidget(btn)
            btn.deleteLater()
        self._letter_buttons.clear()

        # Prune selection: drop letters no longer active
        self._selected_letters &= set(self._active_letters.keys())

        # If selection is now empty (e.g. first call), apply mode default
        if not self._selected_letters and self._active_letters:
            self._apply_default_selection()

        # Build buttons in sorted order
        for letter in sorted(self._active_letters.keys()):
            btn = QPushButton(letter)
            btn.setFont(app_font(12, bold=True))
            btn.setFixedSize(32, 32)
            btn.setCheckable(True)
            btn.setChecked(letter in self._selected_letters)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked, l=letter: self._on_letter_toggled(l, checked))
            self._letter_buttons[letter] = btn
            # Insert before the trailing stretch
            self._toggle_row.insertWidget(
                self._toggle_row.count() - 1, btn
            )

        self._update_toggle_styles()
        self._update_start_button()

    def _apply_default_selection(self) -> None:
        """Set the letter selection to the mode-appropriate default.

        - Relearning: all active letters
        - Speed / Transition: only STABLE + MASTERED letters
        """
        mode = self._mode_combo.currentData()
        if mode in (RunMode.SPEED, RunMode.TRANSITION):
            self._selected_letters = {
                letter
                for letter, stats in self._active_letters.items()
                if stats.state in _STABLE_STATES
            }
        else:
            self._selected_letters = set(self._active_letters.keys())

        # Sync button checked state
        for letter, btn in self._letter_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(letter in self._selected_letters)
            btn.blockSignals(False)

        self._update_toggle_styles()
        self._update_start_button()

    def _on_letter_toggled(self, letter: str, checked: bool) -> None:
        """Handle a letter toggle button click."""
        if checked:
            self._selected_letters.add(letter)
        else:
            self._selected_letters.discard(letter)
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

        Returns a subset of active_letters filtered to only selected ones.
        """
        return {
            letter: stats
            for letter, stats in self._active_letters.items()
            if letter in self._selected_letters
        }

    def _update_highlight_max(self) -> None:
        """Clamp the highlight spinbox max to (non-space selected letters - 1)."""
        non_space = sum(
            1 for l in self._selected_letters if l != " "
        )
        new_max = max(0, non_space - 1)
        self._highlight_count_spin.setMaximum(new_max)

    def get_highlight_letters(self) -> set[str]:
        """Return the set of letters that should be highlighted as weak.

        Selects the N worst letters by rolling error rate (200-keystroke
        window) from the currently selected non-space letters.  Returns
        an empty set when the checkbox is unchecked or N is 0.
        """
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
    # Alerts, mode, practice type
    # ------------------------------------------------------------------

    def set_alerts(self, alerts: list[str]) -> None:
        """Show alerts (e.g., review due, degradation warnings)."""
        if alerts:
            self._alert_label.setText("\n".join(alerts))
            self._alert_label.show()
        else:
            self._alert_label.hide()

    def _on_mode_changed(self, index: int) -> None:
        mode = self._mode_combo.currentData()
        self._update_mode_warning()
        self._update_practice_types()
        # Reset run length to mode-appropriate default
        if mode == RunMode.SPEED:
            self._length_spin.setValue(self.config.run_length_default_speed)
        elif mode == RunMode.TRANSITION:
            self._length_spin.setValue(self.config.run_length_default_transition)
        else:
            self._length_spin.setValue(self.config.run_length_default_relearning)

        # Reset letter selection to mode default
        self._apply_default_selection()

    def _update_mode_warning(self) -> None:
        """Show or hide warning when speed/transition conditions aren't met."""
        mode = self._mode_combo.currentData()
        if mode == RunMode.SPEED and not self._speed_available:
            self._mode_warning.setText(
                "Keys are not settled. Speed training is not recommended."
            )
            self._mode_warning.show()
        elif mode == RunMode.TRANSITION and not self._transition_available:
            if not self._speed_available:
                self._mode_warning.setText(
                    "Keys are not settled. Transition training is not recommended."
                )
            else:
                self._mode_warning.setText(
                    "No bigrams selected. Select bigrams in Analysis > Bigrams."
                )
            self._mode_warning.show()
        else:
            self._mode_warning.hide()

    def _update_practice_types(self) -> None:
        """Update available practice types based on the selected mode.

        Relearning:  random_strings, random_words
        Speed:       random_words, sentences
        Transition:  bigram_words (fixed, no choice)
        """
        mode = self._mode_combo.currentData()
        prev_type = self._type_combo.currentData()

        self._type_combo.blockSignals(True)
        self._type_combo.clear()

        if mode == RunMode.TRANSITION:
            self._type_combo.addItem("Bigram Words", PracticeType.BIGRAM_WORDS)
        elif mode == RunMode.SPEED:
            self._type_combo.addItem("Random Words", PracticeType.RANDOM_WORDS)
            self._type_combo.addItem("Sentences", PracticeType.SENTENCES)
        else:
            self._type_combo.addItem("Random Strings", PracticeType.RANDOM_STRINGS)
            self._type_combo.addItem("Random Words", PracticeType.RANDOM_WORDS)

        # Try to restore previous selection
        for i in range(self._type_combo.count()):
            if self._type_combo.itemData(i) == prev_type:
                self._type_combo.setCurrentIndex(i)
                break

        self._type_combo.blockSignals(False)

        # Show/hide bigram selection info
        self._update_bigram_display()

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
        """Set the selected bigrams for transition training.

        Called by main_window when the user selects bigrams in the
        analysis tab's bigram chart.
        """
        self._selected_bigrams = list(bigrams)
        self._transition_available = len(bigrams) > 0
        self._update_bigram_display()

    def get_selected_bigrams(self) -> list[tuple[str, str]]:
        """Get the currently selected bigrams."""
        return list(self._selected_bigrams)

    def _update_bigram_display(self) -> None:
        """Show/hide the bigram selection label based on mode."""
        mode = self._mode_combo.currentData()
        if mode == RunMode.TRANSITION and self._selected_bigrams:
            bigram_strs = []
            for a, b in self._selected_bigrams:
                a_label = "SPC" if a == " " else a
                b_label = "SPC" if b == " " else b
                bigram_strs.append(f"{a_label}\u2192{b_label}")
            self._bigram_label.setText(
                f"Target bigrams: {', '.join(bigram_strs)}"
            )
            self._bigram_label.setStyleSheet("color: #44aaff;")
            self._bigram_label.show()
        else:
            self._bigram_label.hide()

    def start_rest_timer(self, seconds: int) -> None:
        """Start or resume the rest suggestion countdown.

        Called by main_window when transitioning from the summary
        screen back to the config screen.  If ``seconds`` is 0,
        shows "Rest complete" immediately without counting down.
        """
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
            self._rest_label.setText(
                f"Suggested rest: {self._rest_remaining}s"
            )
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
        mode = self._mode_combo.currentData()
        practice_type = self._type_combo.currentData()
        self.start_run.emit(length, mode, practice_type)
