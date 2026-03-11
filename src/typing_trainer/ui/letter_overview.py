"""Letter state overview panel.

Shows all active letters with color-coded states:
- Blue: introducing
- Yellow: consolidating
- Green: stable
- Red: degraded

Includes per-letter accuracy and stability score.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.models.letter_state import LetterStats
from typing_trainer.ui.theme import (
    COLOR_ERROR,
    COLOR_MASTERED,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    STATE_COLORS,
    app_font,
)


STATE_LABELS = {
    state: name
    for state, name in [
        (s, s.value.capitalize()) for s in STATE_COLORS
    ]
}


class LetterOverviewWidget(QWidget):
    """Detailed letter state overview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Legend
        legend = QHBoxLayout()
        for state, color in STATE_COLORS.items():
            label = QLabel(f'<span style="color: {color};">&#9679;</span> {STATE_LABELS[state]}')
            label.setFont(app_font(10))
            legend.addWidget(label)
        legend.addStretch()
        layout.addLayout(legend)

        # Table
        self._table = QTableWidget()
        self._table.setFont(app_font(11))
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Letter", "State", "Last Err", "Rolling Err", "Stability", "Mastery", "Sessions"]
        )
        header = self._table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self._table)

    def update_display(
        self,
        active_letters: dict[str, LetterStats],
        remaining_letters: list[str] | None = None,
    ) -> None:
        """Refresh the table with current letter states.

        Args:
            active_letters: Currently active (unlocked) letters with stats.
            remaining_letters: Letters not yet introduced, in introduction
                order.  Displayed as greyed-out "Locked" rows below the
                active letters.
        """
        letters = sorted(active_letters.keys())
        locked = remaining_letters or []
        self._table.setRowCount(len(letters) + len(locked))

        for row, letter in enumerate(letters):
            stats = active_letters[letter]
            color = STATE_COLORS.get(stats.state, COLOR_TEXT_BRIGHT)

            # Letter
            item = QTableWidgetItem(letter.upper())
            item.setForeground(QColor(color))
            item.setFont(app_font(12, bold=True))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, item)

            # State
            state_item = QTableWidgetItem(STATE_LABELS.get(stats.state, "?"))
            state_item.setForeground(QColor(color))
            self._table.setItem(row, 1, state_item)

            # Last error rate (most recent session)
            last_err_item = QTableWidgetItem(f"{stats.error_rate_latest:.1%}")
            if stats.error_rate_latest > 0.08:
                last_err_item.setForeground(QColor(COLOR_ERROR))
            elif stats.error_rate_latest > 0.05:
                last_err_item.setForeground(QColor(COLOR_WARNING))
            self._table.setItem(row, 2, last_err_item)

            # Rolling error rate (2000-keystroke window)
            rolling_err_item = QTableWidgetItem(
                f"{stats.rolling_error_rate_long:.1%}"
            )
            if stats.rolling_error_rate_long > 0.08:
                rolling_err_item.setForeground(QColor(COLOR_ERROR))
            elif stats.rolling_error_rate_long > 0.05:
                rolling_err_item.setForeground(QColor(COLOR_WARNING))
            self._table.setItem(row, 3, rolling_err_item)

            # Stability
            stability_item = QTableWidgetItem(f"{stats.stability_score:.2f}")
            if stats.stability_score < 0.5:
                stability_item.setForeground(QColor(COLOR_ERROR))
            self._table.setItem(row, 4, stability_item)

            # Mastery
            mastery_item = QTableWidgetItem(f"{stats.mastery_score:.2f}")
            if stats.mastery_score >= 0.8:
                mastery_item.setForeground(QColor(COLOR_MASTERED))
            self._table.setItem(row, 5, mastery_item)

            # Sessions since introduced
            sessions_item = QTableWidgetItem(str(stats.sessions_since_introduced))
            self._table.setItem(row, 6, sessions_item)

        # Locked (not yet introduced) letters — grey placeholder rows
        muted = QColor(COLOR_TEXT_MUTED)
        base_row = len(letters)
        for i, letter in enumerate(locked):
            row = base_row + i

            item = QTableWidgetItem(letter.upper())
            item.setForeground(muted)
            item.setFont(app_font(12, bold=False))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, item)

            locked_item = QTableWidgetItem("Locked")
            locked_item.setForeground(muted)
            self._table.setItem(row, 1, locked_item)

            for col in range(2, 7):
                dash = QTableWidgetItem("-")
                dash.setForeground(muted)
                self._table.setItem(row, col, dash)
