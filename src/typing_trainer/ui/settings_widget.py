"""Settings tab: user profile management and configuration editor.

Sections:
  1. Profile management (top) — select, create, delete profiles
  2. General settings (middle) — language, session timeout, rest
  3. Advanced settings (bottom, Nerd+ only) — all algorithm parameters
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.config import Config
from typing_trainer.models.letter_state import DisplayMode
from typing_trainer.ui.theme import (
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BTN_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_ERROR,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

# Valid profile name: alphanumeric, spaces, hyphens, 1-30 chars
_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9 \-]{1,30}$")


def _is_valid_profile_name(name: str) -> bool:
    return bool(_PROFILE_NAME_RE.match(name.strip()))


# Default config for reset buttons
_DEFAULTS = Config()


class SettingsWidget(QWidget):
    """Settings tab with profile management and config editors."""

    # Emitted when the user requests a profile switch.
    # Payload is the new profile name.
    profile_switch_requested = pyqtSignal(str)

    # Emitted when a new profile is created via the wizard.
    # Payload is the new profile name.
    new_profile_created = pyqtSignal(str)

    # Emitted when a profile is deleted.
    # Payload is the deleted profile name.
    profile_deleted = pyqtSignal(str)

    # Emitted when language or keyboard layout changes and runtime
    # objects need to be rebuilt.
    runtime_settings_changed = pyqtSignal()

    # Emitted when any config value changes (for live preview of
    # the letter share column in the dashboard).
    config_value_changed = pyqtSignal()

    def __init__(
        self,
        config: Config,
        profile_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._profile_name = profile_name
        self._spinboxes: dict[str, QSpinBox | QDoubleSpinBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scroll area wrapping all content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --- Profile management ---
        profile_group = QGroupBox("User Profile")
        profile_group.setFont(app_font(11))
        pg_layout = QVBoxLayout(profile_group)

        # Row 1: Active profile selector
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Active profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setFont(app_font(11))
        self._profile_combo.setMinimumWidth(180)
        self._profile_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._profile_combo.wheelEvent = lambda event: event.ignore()  # type: ignore[assignment]
        row1.addWidget(self._profile_combo, stretch=1)
        pg_layout.addLayout(row1)

        # Row 2: Profile action buttons
        row2 = QHBoxLayout()
        self._new_btn = QPushButton("New Profile")
        self._new_btn.setFont(app_font(10))
        self._new_btn.clicked.connect(self._on_new_profile)
        row2.addWidget(self._new_btn)

        self._delete_btn = QPushButton("Delete Profile")
        self._delete_btn.setFont(app_font(10))
        self._delete_btn.setStyleSheet(f"color: {COLOR_ERROR};")
        self._delete_btn.clicked.connect(self._on_delete_profile)
        row2.addWidget(self._delete_btn)
        row2.addStretch()
        pg_layout.addLayout(row2)

        # Profile info label
        self._profile_info = QLabel("")
        self._profile_info.setFont(app_font(9))
        self._profile_info.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        pg_layout.addWidget(self._profile_info)

        layout.addWidget(profile_group)

        # Connect combo change AFTER initial population
        self._profile_combo.currentTextChanged.connect(self._on_profile_selected)

        # --- General settings ---
        general_group = QGroupBox("General")
        general_group.setFont(app_font(11))
        gen_layout = QVBoxLayout(general_group)

        # Language
        lang_row = QHBoxLayout()
        lang_row.addWidget(self._make_label("Language"))
        self._lang_combo = QComboBox()
        self._lang_combo.setFont(app_font(11))
        self._lang_combo.addItem("German", "de")
        self._lang_combo.addItem("English", "en")
        idx = self._lang_combo.findData(self._config.language)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.setFixedWidth(120)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        self._lang_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._lang_combo.wheelEvent = lambda event: event.ignore()  # type: ignore[assignment]
        lang_row.addStretch()
        lang_row.addWidget(self._lang_combo)
        reset = self._make_reset_btn()
        reset.clicked.connect(
            lambda: self._lang_combo.setCurrentIndex(
                self._lang_combo.findData(_DEFAULTS.language)
            )
        )
        lang_row.addWidget(reset)
        gen_layout.addLayout(lang_row)

        # Keyboard layout
        kb_row = QHBoxLayout()
        kb_row.addWidget(self._make_label("Keyboard layout"))
        self._keyboard_combo = QComboBox()
        self._keyboard_combo.setFont(app_font(11))
        from typing_trainer.models.keyboard_layout import list_keyboards

        for name in list_keyboards():
            self._keyboard_combo.addItem(name.upper(), name)
        idx = self._keyboard_combo.findData(self._config.keyboard_layout)
        if idx >= 0:
            self._keyboard_combo.setCurrentIndex(idx)
        self._keyboard_combo.setFixedWidth(120)
        self._keyboard_combo.currentIndexChanged.connect(self._on_keyboard_changed)
        self._keyboard_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._keyboard_combo.wheelEvent = lambda event: event.ignore()  # type: ignore[assignment]
        kb_row.addStretch()
        kb_row.addWidget(self._keyboard_combo)
        kb_reset = self._make_reset_btn()
        kb_reset.clicked.connect(
            lambda: self._keyboard_combo.setCurrentIndex(
                self._keyboard_combo.findData(_DEFAULTS.keyboard_layout)
            )
        )
        kb_row.addWidget(kb_reset)
        gen_layout.addLayout(kb_row)

        # General numeric settings
        self._add_int_row(
            gen_layout, "Session timeout (min)", "session_timeout_minutes", 5, 120
        )
        self._add_int_row(
            gen_layout, "Rest suggestion (sec)", "rest_suggestion_seconds", 0, 60
        )

        layout.addWidget(general_group)

        # --- Advanced settings ---
        self._advanced_group = QGroupBox("Advanced Settings")
        self._advanced_group.setFont(app_font(11))
        adv_layout = QVBoxLayout(self._advanced_group)

        # Advancement & Progression
        adv_layout.addWidget(self._make_section_label("Advancement & Progression"))
        self._add_float_row(
            adv_layout,
            "Accuracy threshold",
            "advancement_accuracy",
            0.80,
            1.00,
            decimals=2,
            step=0.01,
            tip="Per-letter accuracy required for next letter",
        )
        self._add_int_row(
            adv_layout,
            "Min keystrokes",
            "advancement_min_keystrokes",
            100,
            5000,
            step=100,
            tip="Keystrokes after last unlock before next letter",
        )
        self._add_int_row(
            adv_layout,
            "Accuracy window",
            "advancement_accuracy_window",
            50,
            1000,
            step=50,
            tip="Rolling window size for per-letter accuracy",
        )

        # Fail Thresholds
        adv_layout.addWidget(self._make_section_label("Fail Thresholds"))
        self._add_float_row(
            adv_layout,
            "Relearning",
            "fail_threshold_relearning",
            0.50,
            1.00,
            decimals=2,
            step=0.05,
        )
        self._add_float_row(
            adv_layout,
            "Speed",
            "fail_threshold_speed",
            0.50,
            1.00,
            decimals=2,
            step=0.05,
        )
        self._add_float_row(
            adv_layout,
            "Transition",
            "fail_threshold_transition",
            0.50,
            1.00,
            decimals=2,
            step=0.05,
        )
        self._add_float_row(
            adv_layout,
            "Introducing (stage 1)",
            "fail_threshold_introducing_s1",
            0.50,
            1.00,
            decimals=2,
            step=0.05,
        )
        self._add_float_row(
            adv_layout,
            "Introducing (stage 2)",
            "fail_threshold_introducing_s2",
            0.50,
            1.00,
            decimals=2,
            step=0.05,
        )
        self._add_int_row(
            adv_layout, "Min errors before fail", "fail_threshold_min_errors", 1, 20
        )

        # Run Defaults
        adv_layout.addWidget(self._make_section_label("Run Defaults"))
        self._add_int_row(
            adv_layout,
            "Relearning length",
            "run_length_default_relearning",
            20,
            500,
            step=10,
        )
        self._add_int_row(
            adv_layout, "Speed length", "run_length_default_speed", 20, 500, step=10
        )
        self._add_int_row(
            adv_layout,
            "Transition length",
            "run_length_default_transition",
            20,
            500,
            step=10,
        )
        self._add_int_row(
            adv_layout, "Minimum run length", "run_length_minimum", 10, 200, step=10
        )

        # Speed Training
        adv_layout.addWidget(self._make_section_label("Speed Training"))
        self._add_int_row(adv_layout, "WPM increment on pass", "speed_increment", 1, 10)
        self._add_int_row(adv_layout, "WPM decrement on fail", "speed_decrement", 1, 10)

        # Letter Weighting
        adv_layout.addWidget(self._make_section_label("Letter Weighting"))
        self._add_float_row(
            adv_layout,
            "Introducing weight",
            "weight_introducing",
            0.0,
            10.0,
            decimals=1,
            step=0.5,
        )
        self._add_float_row(
            adv_layout,
            "Degraded weight",
            "weight_degraded",
            0.0,
            10.0,
            decimals=1,
            step=0.5,
        )
        self._add_float_row(
            adv_layout,
            "Consolidating weight",
            "weight_consolidating",
            0.0,
            10.0,
            decimals=1,
            step=0.5,
        )
        self._add_float_row(
            adv_layout,
            "Recently stable weight",
            "weight_recently_stable",
            0.0,
            10.0,
            decimals=1,
            step=0.5,
        )
        self._add_float_row(
            adv_layout,
            "Volume deficit weight",
            "weight_volume_deficit",
            0.0,
            10.0,
            decimals=1,
            step=0.5,
        )
        self._add_float_row(
            adv_layout,
            "Mastered weight",
            "weight_mastered",
            0.0,
            10.0,
            decimals=1,
            step=0.1,
        )
        self._add_int_row(
            adv_layout,
            "Recently stable keystrokes",
            "recently_stable_keystrokes",
            100,
            5000,
            step=100,
        )
        self._add_float_row(
            adv_layout,
            "Max letter share",
            "max_letter_share",
            0.10,
            1.00,
            decimals=2,
            step=0.05,
        )

        # High Accuracy Suppression
        adv_layout.addWidget(self._make_section_label("High Accuracy Suppression"))
        self._add_float_row(
            adv_layout,
            "Accuracy threshold",
            "high_accuracy_threshold",
            0.90,
            1.00,
            decimals=2,
            step=0.01,
            tip="Accuracy above which weight is suppressed",
        )
        self._add_int_row(
            adv_layout,
            "Window (keystrokes)",
            "high_accuracy_window",
            100,
            2000,
            step=100,
            tip="Rolling window for the high-accuracy check",
        )
        self._add_int_row(
            adv_layout,
            "Min keystrokes",
            "high_accuracy_min_keystrokes",
            100,
            2000,
            step=100,
            tip="Need this many keystrokes before suppression applies",
        )
        self._add_float_row(
            adv_layout,
            "Weight factor",
            "high_accuracy_factor",
            0.01,
            1.00,
            decimals=2,
            step=0.05,
            tip="Multiply weight by this when suppressed (0.1 = 10%)",
        )

        # Error Classification
        adv_layout.addWidget(self._make_section_label("Error Classification"))
        self._add_int_row(
            adv_layout,
            "Motor overflow window (ms)",
            "motor_overflow_window_ms",
            20,
            200,
            step=10,
        )
        self._add_int_row(
            adv_layout,
            "Burst max interval (ms)",
            "burst_max_interval_ms",
            100,
            1000,
            step=50,
        )
        self._add_int_row(adv_layout, "Warmup keystrokes", "warmup_keystrokes", 0, 20)

        # Mastery
        adv_layout.addWidget(self._make_section_label("Mastery"))
        self._add_int_row(
            adv_layout,
            "Keystrokes required",
            "mastery_keystrokes_required",
            500,
            10000,
            step=500,
        )
        self._add_float_row(
            adv_layout,
            "Mastery threshold",
            "mastery_threshold",
            0.50,
            1.00,
            decimals=2,
            step=0.05,
        )
        self._add_float_row(
            adv_layout,
            "Half-life min (days)",
            "mastery_half_life_min_days",
            1.0,
            365.0,
            decimals=1,
            step=1.0,
        )
        self._add_float_row(
            adv_layout,
            "Half-life max (days)",
            "mastery_half_life_max_days",
            7.0,
            365.0,
            decimals=1,
            step=1.0,
        )

        # Spaced Repetition
        adv_layout.addWidget(self._make_section_label("Spaced Repetition"))
        self._add_float_row(
            adv_layout,
            "Consolidating half-life (h)",
            "half_life_consolidating_hours",
            6.0,
            168.0,
            decimals=1,
            step=6.0,
        )
        self._add_float_row(
            adv_layout,
            "Stable half-life (h)",
            "half_life_stable_hours",
            24.0,
            720.0,
            decimals=1,
            step=12.0,
        )
        self._add_float_row(
            adv_layout,
            "Stability revert threshold",
            "stability_revert_threshold",
            0.10,
            0.90,
            decimals=2,
            step=0.05,
        )

        # Bigrams
        adv_layout.addWidget(self._make_section_label("Bigrams"))
        self._add_int_row(adv_layout, "Min count", "bigram_min_count", 1, 100, step=5)
        self._add_float_row(
            adv_layout,
            "Target share",
            "bigram_target_share",
            0.10,
            0.90,
            decimals=2,
            step=0.05,
        )
        self._add_int_row(adv_layout, "Max targets", "bigram_max_targets", 1, 10)
        self._add_float_row(
            adv_layout,
            "Trimmed mean fraction",
            "bigram_trimmed_mean_fraction",
            0.00,
            0.50,
            decimals=2,
            step=0.05,
        )

        # Anti-repeat
        adv_layout.addWidget(self._make_section_label("Anti-repeat"))
        self._add_int_row(
            adv_layout, "Min letters no repeat", "min_letters_no_repeat", 2, 10
        )
        self._add_int_row(
            adv_layout, "Min hand letters no repeat", "min_hand_letters_no_repeat", 2, 8
        )

        layout.addWidget(self._advanced_group)
        layout.addStretch()

        # Cap content width so labels and spinners stay visually close
        container.setMaximumWidth(550)

        scroll.setWidget(container)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # Helper methods for building settings rows
    # ------------------------------------------------------------------

    @staticmethod
    def _make_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(app_font(10))
        lbl.setMinimumWidth(200)
        return lbl

    @staticmethod
    def _make_section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(app_font(10, bold=True))
        lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; margin-top: 8px;")
        return lbl

    @staticmethod
    def _make_reset_btn() -> QPushButton:
        btn = QPushButton("\u21ba")  # ↺
        btn.setFont(app_font(10))
        btn.setFixedSize(24, 24)
        btn.setToolTip("Reset to default")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn

    def _make_value_handler(self, field: str):  # type: ignore[no-untyped-def]
        """Create a spinbox valueChanged handler that updates config and emits signal."""

        def handler(value: int | float) -> None:
            setattr(self._config, field, value)
            self.config_value_changed.emit()

        return handler

    def _add_int_row(
        self,
        parent_layout: QVBoxLayout,
        label: str,
        field: str,
        min_val: int,
        max_val: int,
        step: int = 1,
        tip: str = "",
    ) -> None:
        row = QHBoxLayout()
        lbl = self._make_label(label)
        if tip:
            lbl.setToolTip(tip)
        row.addWidget(lbl)

        spin = QSpinBox()
        spin.setFont(app_font(10))
        spin.setFixedWidth(90)
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setValue(getattr(self._config, field))
        spin.valueChanged.connect(self._make_value_handler(field))
        spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        spin.wheelEvent = lambda event: event.ignore()  # type: ignore[assignment]
        row.addStretch()
        row.addWidget(spin)

        self._spinboxes[field] = spin

        default_val = getattr(_DEFAULTS, field)
        reset = self._make_reset_btn()
        reset.clicked.connect(lambda _=None, s=spin, d=default_val: s.setValue(d))
        row.addWidget(reset)

        parent_layout.addLayout(row)

    def _add_float_row(
        self,
        parent_layout: QVBoxLayout,
        label: str,
        field: str,
        min_val: float,
        max_val: float,
        decimals: int = 2,
        step: float = 0.01,
        tip: str = "",
    ) -> None:
        row = QHBoxLayout()
        lbl = self._make_label(label)
        if tip:
            lbl.setToolTip(tip)
        row.addWidget(lbl)

        spin = QDoubleSpinBox()
        spin.setFont(app_font(10))
        spin.setFixedWidth(90)
        spin.setRange(min_val, max_val)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setValue(getattr(self._config, field))
        spin.valueChanged.connect(self._make_value_handler(field))
        spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        spin.wheelEvent = lambda event: event.ignore()  # type: ignore[assignment]
        row.addStretch()
        row.addWidget(spin)

        self._spinboxes[field] = spin

        default_val = getattr(_DEFAULTS, field)
        reset = self._make_reset_btn()
        reset.clicked.connect(lambda _=None, s=spin, d=default_val: s.setValue(d))
        row.addWidget(reset)

        parent_layout.addLayout(row)

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def refresh_profile_list(
        self, profiles: list[str] | None = None, active: str | None = None
    ) -> None:
        """Rebuild the profile combo box.

        Args:
            profiles: Available profile names.  If ``None``, reads from
                disk via :func:`list_profiles`.
            active: The currently active profile name.
        """
        from typing_trainer.main import list_profiles as _list_profiles

        if profiles is None:
            profiles = _list_profiles()
        if active is None:
            active = self._profile_name

        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for p in profiles:
            self._profile_combo.addItem(p)
        idx = self._profile_combo.findText(active)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        self._profile_combo.blockSignals(False)

        # Disable delete if only one profile
        self._delete_btn.setEnabled(len(profiles) > 1)

    def set_profile_info(self, runs: int, keystrokes: int, letters: int) -> None:
        """Update the profile info label."""
        self._profile_info.setText(
            f"{runs} runs, {keystrokes:,} keystrokes, {letters} letters unlocked"
        )

    def update_config_display(self, config: Config) -> None:
        """Refresh all spinboxes to reflect a new config (after profile switch)."""
        self._config = config
        for field_name, spin in self._spinboxes.items():
            spin.blockSignals(True)
            val = getattr(config, field_name)
            spin.setValue(val)
            spin.blockSignals(False)
        # Language combo
        idx = self._lang_combo.findData(config.language)
        if idx >= 0:
            self._lang_combo.blockSignals(True)
            self._lang_combo.setCurrentIndex(idx)
            self._lang_combo.blockSignals(False)
        idx = self._keyboard_combo.findData(config.keyboard_layout)
        if idx >= 0:
            self._keyboard_combo.blockSignals(True)
            self._keyboard_combo.setCurrentIndex(idx)
            self._keyboard_combo.blockSignals(False)

    def set_display_mode(self, mode: DisplayMode) -> None:
        """Show/hide advanced section based on display mode."""
        self._advanced_group.setVisible(mode != DisplayMode.BASIC)

    def _on_lang_changed(self, _index: int) -> None:
        data = self._lang_combo.currentData()
        if isinstance(data, str):
            self._config.language = data
            self.runtime_settings_changed.emit()

    def _on_keyboard_changed(self, _index: int) -> None:
        data = self._keyboard_combo.currentData()
        if isinstance(data, str):
            self._config.keyboard_layout = data
            self.runtime_settings_changed.emit()

    def _on_profile_selected(self, name: str) -> None:
        if name and name != self._profile_name:
            self.profile_switch_requested.emit(name)

    def _on_new_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "New Profile",
            "Profile name (letters, numbers, spaces, hyphens):",
        )
        if not ok or not name:
            return
        name = name.strip()
        if not _is_valid_profile_name(name):
            QMessageBox.warning(
                self,
                "Invalid Name",
                "Profile name must be 1-30 characters: "
                "letters, numbers, spaces, or hyphens.",
            )
            return

        from typing_trainer.main import get_profile_dir, list_profiles

        if name.lower() in [p.lower() for p in list_profiles()]:
            QMessageBox.warning(
                self, "Name Taken", f'A profile named "{name}" already exists.'
            )
            return

        # Create the profile directory
        profile_dir = get_profile_dir(name)
        profile_dir.mkdir(parents=True, exist_ok=True)

        self.new_profile_created.emit(name)

    def _on_delete_profile(self) -> None:
        from typing_trainer.main import list_profiles

        profiles = list_profiles()
        if len(profiles) <= 1:
            QMessageBox.warning(
                self, "Cannot Delete", "Cannot delete the last remaining profile."
            )
            return

        current = self._profile_combo.currentText()
        reply = QMessageBox.warning(
            self,
            "Delete Profile",
            f'Really delete profile "{current}" and all training data?\n\n'
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Second confirmation
        reply2 = QMessageBox.critical(
            self,
            "Confirm Deletion",
            f'This will permanently delete all data for "{current}".\n\nAre you sure?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return

        self.profile_deleted.emit(current)
