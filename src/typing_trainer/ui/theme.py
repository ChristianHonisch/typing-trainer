"""Centralized theme: colors, fonts, and state color maps.

All UI modules should import visual constants from here instead of
hard-coding hex literals or QFont calls.

Fonts are resolved lazily (after QApplication exists) via ``app_font()``.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QLabel


# ---------------------------------------------------------------------------
# Semantic colors
# ---------------------------------------------------------------------------

# Status / feedback
COLOR_SUCCESS = "#4a9e4a"
COLOR_ERROR = "#ff4444"
COLOR_WARNING = "#cccc44"
COLOR_ALERT = "#cc8800"
COLOR_INFO = "#44aaff"

# Error background tint (for typed-character error highlighting)
COLOR_ERROR_BG = "#441111"

# Error type classification colors (for confusion matrix / stacked bars)
COLOR_SPATIAL = "#44aaff"       # blue — physically adjacent keys
COLOR_SAME_FINGER = "#cccc44"  # yellow — same finger, different row
COLOR_MIRROR = "#cc66ff"       # purple — homologous mirror position
COLOR_OTHER_ERROR = "#888888"  # gray — unclassified / other

# ---------------------------------------------------------------------------
# Surface / chrome colors
# ---------------------------------------------------------------------------

COLOR_BG_DARKEST = "#1a1a1a"
COLOR_BG_DARK = "#222222"
COLOR_BG_SECONDARY = "#2a2a2a"
COLOR_BG_TERTIARY = "#333333"
COLOR_BG_INPUT = "#1e1e1e"
COLOR_BG_CURSOR = "#444444"

# ---------------------------------------------------------------------------
# Text colors
# ---------------------------------------------------------------------------

COLOR_TEXT_PRIMARY = "#cccccc"
COLOR_TEXT_SECONDARY = "#888888"
COLOR_TEXT_MUTED = "#666666"
COLOR_TEXT_BRIGHT = "#ffffff"

# ---------------------------------------------------------------------------
# Button colors
# ---------------------------------------------------------------------------

COLOR_BTN_PRIMARY = "#2d5a2d"
COLOR_BTN_HOVER = "#3a7a3a"
COLOR_BTN_PRESSED = "#1a3a1a"
COLOR_BTN_DISABLED_BG = "#333333"
COLOR_BTN_DISABLED_TEXT = "#666666"

# ---------------------------------------------------------------------------
# Letter-state color map
# ---------------------------------------------------------------------------

from typing_trainer.models.letter_state import LetterState  # noqa: E402

COLOR_MASTERED = "#cc9900"
"""Gold / amber for MASTERED letters — distinct from STABLE green."""

STATE_COLORS: dict[LetterState, str] = {
    LetterState.INTRODUCING: COLOR_INFO,
    LetterState.CONSOLIDATING: COLOR_WARNING,
    LetterState.STABLE: COLOR_SUCCESS,
    LetterState.MASTERED: COLOR_MASTERED,
    LetterState.DEGRADED: COLOR_ERROR,
}


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

_resolved_family: str | None = None


def _resolve_font_family() -> str:
    """Pick the best available monospace font (called once, lazily)."""
    global _resolved_family
    if _resolved_family is not None:
        return _resolved_family

    preferred = ["Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"]
    available = set(QFontDatabase.families())
    for name in preferred:
        if name in available:
            _resolved_family = name
            return _resolved_family

    # Ultimate fallback — ask Qt for the system fixed font
    _resolved_family = QFontDatabase.systemFont(
        QFontDatabase.SystemFont.FixedFont
    ).family()
    return _resolved_family


def app_font(size: int, bold: bool = False) -> QFont:
    """Create a QFont using the resolved monospace family."""
    weight = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return QFont(_resolve_font_family(), size, weight)


# ---------------------------------------------------------------------------
# Debug / development flags
# ---------------------------------------------------------------------------

DEBUG_TEXT_SELECTABLE: bool = True
"""When True, informational QLabels are made mouse-selectable.

Useful for debugging (copying stats, error messages, etc.).
Set to False for normal use to prevent accidental text selection.
"""


def make_selectable(label: QLabel) -> None:
    """Make a QLabel's text selectable by mouse if the global flag is set."""
    if DEBUG_TEXT_SELECTABLE:
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
