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
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    STATE_COLORS,
    app_font,
)


STATE_LABELS = {
    state: name for state, name in [(s, s.value.capitalize()) for s in STATE_COLORS]
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
            label = QLabel(
                f'<span style="color: {color};">&#9679;</span> {STATE_LABELS[state]}'
            )
            label.setFont(app_font(10))
            legend.addWidget(label)
        legend.addStretch()
        layout.addLayout(legend)

        # Table
        self._table = QTableWidget()
        self._table.setFont(app_font(11))
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels(
            [
                "Letter",
                "State",
                "Keystrokes",
                "Rolling Err",
                "Median RT",
                "Factor",
                "CV",
                "Runs",
                "Share",
            ]
        )
        header = self._table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table)

        # Space baseline RT label
        self._space_label = QLabel("")
        self._space_label.setFont(app_font(9))
        self._space_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        layout.addWidget(self._space_label)

    def update_display(
        self,
        active_letters: dict[str, LetterStats],
        remaining_letters: list[str] | None = None,
        keystroke_counts: dict[str, int] | None = None,
        run_counts: dict[str, int] | None = None,
        weight_shares: dict[str, float] | None = None,
        space_median_rt: float = 0.0,
    ) -> None:
        """Refresh the table with current letter states.

        Args:
            active_letters: Currently active (unlocked) letters with stats.
            remaining_letters: Letters not yet introduced, in introduction
                order.  Displayed as greyed-out "Locked" rows below the
                active letters.
            space_median_rt: Space key median RT for display context.
            keystroke_counts: Total all-time keystrokes per letter (from
                :meth:`Repository.get_per_letter_error_rates`).
            run_counts: Number of distinct runs each letter appeared in
                (from :meth:`Repository.get_per_letter_run_counts`).
        """
        # Disable sorting while populating to avoid crashes
        self._table.setSortingEnabled(False)

        # Update space baseline label
        if space_median_rt > 0:
            self._space_label.setText(f"Space baseline: {space_median_rt:.0f}ms")
        else:
            self._space_label.setText("")

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

            # Keystrokes (total all-time)
            ks_counts = keystroke_counts or {}
            ks_val = ks_counts.get(letter, 0)
            ks_item = _NumericTableItem(f"{ks_val:,}", float(ks_val))
            self._table.setItem(row, 2, ks_item)

            # Rolling error rate (2000-keystroke window)
            rolling_val = stats.rolling_error_rate_long
            rolling_err_item = _NumericTableItem(f"{rolling_val:.1%}", rolling_val)
            if rolling_val > 0.08:
                rolling_err_item.setForeground(QColor(COLOR_ERROR))
            elif rolling_val > 0.05:
                rolling_err_item.setForeground(QColor(COLOR_WARNING))
            self._table.setItem(row, 3, rolling_err_item)

            # Median RT
            rt_val = stats.median_rt
            if rt_val > 0:
                rt_item = _NumericTableItem(f"{rt_val:.0f}ms", rt_val)
            else:
                rt_item = _NumericTableItem("\u2014", -1.0)
            self._table.setItem(row, 4, rt_item)

            # Factor (RT / space median RT)
            factor_val = stats.rt_factor
            if factor_val > 0:
                factor_item = _NumericTableItem(f"{factor_val:.2f}x", factor_val)
                if factor_val < 1.25:
                    factor_item.setForeground(QColor(COLOR_MASTERED))
                elif factor_val > 1.80:
                    factor_item.setForeground(QColor(COLOR_ERROR))
                elif factor_val > 1.50:
                    factor_item.setForeground(QColor(COLOR_WARNING))
            else:
                factor_item = _NumericTableItem("\u2014", -1.0)
            self._table.setItem(row, 5, factor_item)

            # CV (coefficient of variation)
            cv_val = stats.rt_cv
            if stats.rt_keystroke_count > 0:
                cv_item = _NumericTableItem(f"{cv_val:.2f}", cv_val)
            else:
                cv_item = _NumericTableItem("\u2014", -1.0)
            self._table.setItem(row, 6, cv_item)

            # Runs (distinct runs this letter appeared in)
            rc = run_counts or {}
            runs_val = rc.get(letter, 0)
            runs_item = _NumericTableItem(str(runs_val), float(runs_val))
            self._table.setItem(row, 7, runs_item)

            # Share (projected weight share in next run)
            ws = weight_shares or {}
            share_val = ws.get(letter, 0.0)
            share_item = _NumericTableItem(f"{share_val:.1%}", share_val)
            self._table.setItem(row, 8, share_item)

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

            for col in range(2, 9):
                dash = _NumericTableItem("-", -1.0)
                dash.setForeground(muted)
                self._table.setItem(row, col, dash)

        # Re-enable sorting and apply default sort
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(7, Qt.SortOrder.DescendingOrder)
