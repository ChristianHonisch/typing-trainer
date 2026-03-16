"""New user setup wizard dialog.

Shown when a profile has not completed setup yet.  Collects:
- Language preference (German / English)
- Training path (start from scratch vs skip to speed)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_BTN_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)


class NewUserWizard(QDialog):
    """Setup wizard for new user profiles."""

    def __init__(self, profile_name: str, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Typing Trainer - New Profile Setup")
        self.setMinimumSize(500, 400)
        self.setStyleSheet(f"""
            QWidget {{
                background: {COLOR_BG_DARK};
                color: {COLOR_TEXT_PRIMARY};
            }}
            QRadioButton {{
                color: {COLOR_TEXT_PRIMARY};
                spacing: 8px;
            }}
            QRadioButton::indicator {{
                border: 2px solid {COLOR_TEXT_SECONDARY};
                border-radius: 10px;
                width: 16px;
                height: 16px;
                background: {COLOR_BG_TERTIARY};
            }}
            QRadioButton::indicator:checked {{
                background: {COLOR_SUCCESS};
                border-color: {COLOR_SUCCESS};
            }}
        """)

        # Result attributes (read after exec())
        self.language: str = "de"
        self.skip_to_speed: bool = False

        self._profile_name = profile_name
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(30, 24, 30, 24)

        # Welcome
        welcome = QLabel("Welcome to Typing Trainer")
        welcome.setFont(app_font(16, bold=True))
        welcome.setStyleSheet(f"color: {COLOR_TEXT_BRIGHT};")
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome)

        subtitle = QLabel(f'Setting up profile "{self._profile_name}"')
        subtitle.setFont(app_font(10))
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # --- Language ---
        lang_group = QGroupBox("Language")
        lang_group.setFont(app_font(11))
        lang_group.setStyleSheet(
            f"""QGroupBox {{
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_BG_SECONDARY};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}"""
        )
        lang_layout = QHBoxLayout(lang_group)

        self._lang_de = QRadioButton("German")
        self._lang_de.setFont(app_font(11))
        self._lang_de.setChecked(True)
        self._lang_en = QRadioButton("English")
        self._lang_en.setFont(app_font(11))

        self._lang_group = QButtonGroup(self)
        self._lang_group.addButton(self._lang_de, 0)
        self._lang_group.addButton(self._lang_en, 1)

        lang_layout.addWidget(self._lang_de)
        lang_layout.addWidget(self._lang_en)
        lang_layout.addStretch()
        layout.addWidget(lang_group)

        # --- Training path ---
        path_group = QGroupBox("Training Path")
        path_group.setFont(app_font(11))
        path_group.setStyleSheet(lang_group.styleSheet())
        path_layout = QVBoxLayout(path_group)
        path_layout.setSpacing(10)

        self._path_scratch = QRadioButton("Start from scratch")
        self._path_scratch.setFont(app_font(11, bold=True))
        self._path_scratch.setChecked(True)
        path_layout.addWidget(self._path_scratch)

        scratch_desc = QLabel(
            "Learn each key from the ground up. Letters are introduced "
            "one by one. Recommended if you are learning a new keyboard "
            "layout or have never learned proper touch typing."
        )
        scratch_desc.setFont(app_font(9))
        scratch_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        scratch_desc.setWordWrap(True)
        scratch_desc.setContentsMargins(20, 0, 0, 6)
        path_layout.addWidget(scratch_desc)

        self._path_speed = QRadioButton("I already know the keys")
        self._path_speed.setFont(app_font(11, bold=True))
        path_layout.addWidget(self._path_speed)

        speed_desc = QLabel(
            "Skip the learning phase. All 26 keys are unlocked "
            "immediately. Jump straight into word-based speed training."
        )
        speed_desc.setFont(app_font(9))
        speed_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        speed_desc.setWordWrap(True)
        speed_desc.setContentsMargins(20, 0, 0, 0)
        path_layout.addWidget(speed_desc)

        self._path_group = QButtonGroup(self)
        self._path_group.addButton(self._path_scratch, 0)
        self._path_group.addButton(self._path_speed, 1)

        layout.addWidget(path_group)

        layout.addStretch()

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(app_font(11))
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        start_btn = QPushButton("Start")
        start_btn.setFont(app_font(11, bold=True))
        start_btn.setFixedWidth(120)
        start_btn.setDefault(True)
        start_btn.setStyleSheet(
            f"""QPushButton {{
                background: {COLOR_BTN_PRIMARY};
                color: {COLOR_TEXT_BRIGHT};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background: {COLOR_BTN_HOVER};
            }}"""
        )
        start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(start_btn)

        layout.addLayout(btn_layout)

    def _on_start(self) -> None:
        """Collect choices and accept the dialog."""
        self.language = "de" if self._lang_de.isChecked() else "en"
        self.skip_to_speed = self._path_speed.isChecked()
        self.accept()
