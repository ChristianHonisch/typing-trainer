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


class _NumericTableItem(QTableWidgetItem):
    """Table item that sorts by a stored numeric value rather than text."""

    def __init__(self, text: str, sort_value: float) -> None:
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, sort_value)

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        self_val = self.data(Qt.ItemDataRole.UserRole)
        other_val = other.data(Qt.ItemDataRole.UserRole)
        if self_val is not None and other_val is not None:
            return float(self_val) < float(other_val)
        return super().__lt__(other)


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
        self._table.setSortingEnabled(True)
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
        # Disable sorting while populating to avoid crashes
        self._table.setSortingEnabled(False)

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
            last_err_val = stats.error_rate_latest
            last_err_item = _NumericTableItem(f"{last_err_val:.1%}", last_err_val)
            if last_err_val > 0.08:
                last_err_item.setForeground(QColor(COLOR_ERROR))
            elif last_err_val > 0.05:
                last_err_item.setForeground(QColor(COLOR_WARNING))
            self._table.setItem(row, 2, last_err_item)

            # Rolling error rate (2000-keystroke window)
            rolling_val = stats.rolling_error_rate_long
            rolling_err_item = _NumericTableItem(
                f"{rolling_val:.1%}", rolling_val
            )
            if rolling_val > 0.08:
                rolling_err_item.setForeground(QColor(COLOR_ERROR))
            elif rolling_val > 0.05:
                rolling_err_item.setForeground(QColor(COLOR_WARNING))
            self._table.setItem(row, 3, rolling_err_item)

            # Stability
            stab_val = stats.stability_score
            stability_item = _NumericTableItem(f"{stab_val:.2f}", stab_val)
            if stab_val < 0.5:
                stability_item.setForeground(QColor(COLOR_ERROR))
            self._table.setItem(row, 4, stability_item)

            # Mastery
            mast_val = stats.mastery_score
            mastery_item = _NumericTableItem(f"{mast_val:.2f}", mast_val)
            if mast_val >= 0.8:
                mastery_item.setForeground(QColor(COLOR_MASTERED))
            self._table.setItem(row, 5, mastery_item)

            # Sessions since introduced
            sess_val = float(stats.sessions_since_introduced)
            sessions_item = _NumericTableItem(
                str(stats.sessions_since_introduced), sess_val
            )
            self._table.setItem(row, 6, sessions_item)

        # Locked (not yet introduced) letters — grey placeholder rows
        # Use sort values that push them to the bottom (high for asc, low
        # for desc depending on column — use -1.0 so they sort below real
        # data in ascending order; for descending they appear at the end).
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
                dash = _NumericTableItem("-", -1.0)
                dash.setForeground(muted)
                self._table.setItem(row, col, dash)

        # Re-enable sorting and apply default sort
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(6, Qt.SortOrder.DescendingOrder)
