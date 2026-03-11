"""Bigram transition analysis: error-prone and slow bigram tables.

User-directed analysis view for identifying problematic letter
transitions.  Two tables:
  - Error-prone bigrams: sorted by error rate
  - Slow bigrams: sorted by trimmed mean transition time

Users can select 1-3 bigrams to target in transition training.
Selected bigrams are communicated via the ``bigrams_selected`` signal.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from typing_trainer.core.stats import trimmed_mean
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_BG_SECONDARY,
    COLOR_BTN_DISABLED_BG,
    COLOR_BTN_DISABLED_TEXT,
    COLOR_BTN_HOVER,
    COLOR_BTN_PRIMARY,
    COLOR_BTN_PRESSED,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
    make_selectable,
)


# Minimum number of bigram occurrences to display
_DISPLAY_MIN_COUNT = 10

# Practice types to analyze (transition training cares about natural typing)
_ANALYSIS_PRACTICE_TYPES = ["random_words", "sentences", "bigram_words"]


class BigramChart(QWidget):
    """Bigram analysis view with error-rate and transition-time tables.

    Signals:
        bigrams_selected: Emitted with list of (prev_char, expected_char)
            tuples when the user confirms their selection.
    """

    bigrams_selected = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._error_data: list[tuple[str, str, int, int, float]] = []
        self._time_data: list[tuple[str, str, float, int]] = []
        self._selected: set[tuple[str, str]] = set()
        self._max_targets = 3
        self._repo: Repository | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Top bar: description + refresh button
        top_layout = QHBoxLayout()

        desc = QLabel(
            "Bigram transition analysis — identify error-prone or slow "
            "letter transitions.  Select 1-3 bigrams, then start a "
            "transition training run."
        )
        desc.setFont(app_font(10))
        desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        desc.setWordWrap(True)
        make_selectable(desc)
        top_layout.addWidget(desc, stretch=1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFont(app_font(10))
        self._refresh_btn.setMinimumHeight(28)
        self._refresh_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_BTN_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_BTN_PRESSED};
            }}
            """
        )
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        top_layout.addWidget(self._refresh_btn)

        layout.addLayout(top_layout)

        # Tables side by side
        tables_layout = QHBoxLayout()

        # Error-prone bigrams table
        error_group = QVBoxLayout()
        error_label = QLabel("Error-Prone Bigrams")
        error_label.setFont(app_font(12, bold=True))
        error_group.addWidget(error_label)

        self._error_table = self._create_table(
            ["Bigram", "Errors", "Total", "Error Rate"]
        )
        self._error_table.itemSelectionChanged.connect(
            self._on_error_selection_changed
        )
        error_group.addWidget(self._error_table)
        tables_layout.addLayout(error_group)

        # Slow bigrams table
        time_group = QVBoxLayout()
        time_label = QLabel("Slow Bigrams")
        time_label.setFont(app_font(12, bold=True))
        time_group.addWidget(time_label)

        self._time_table = self._create_table(
            ["Bigram", "Trimmed Mean (ms)", "Count"]
        )
        self._time_table.itemSelectionChanged.connect(
            self._on_time_selection_changed
        )
        time_group.addWidget(self._time_table)
        tables_layout.addLayout(time_group)

        layout.addLayout(tables_layout)

        # Selection summary + action button
        bottom_layout = QHBoxLayout()

        self._selection_label = QLabel("No bigrams selected")
        self._selection_label.setFont(app_font(11))
        self._selection_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        make_selectable(self._selection_label)
        bottom_layout.addWidget(self._selection_label)

        bottom_layout.addStretch()

        self._start_btn = QPushButton("Train Selected Bigrams")
        self._start_btn.setFont(app_font(12, bold=True))
        self._start_btn.setMinimumHeight(36)
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start_clicked)
        self._update_button_style()
        bottom_layout.addWidget(self._start_btn)

        layout.addWidget(QWidget())  # spacer
        layout.addLayout(bottom_layout)

    def _create_table(self, headers: list[str]) -> QTableWidget:
        """Create a styled table widget."""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFont(app_font(11))
        v_header = table.verticalHeader()
        if v_header is not None:
            v_header.setVisible(False)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {COLOR_BG_DARK};
                alternate-background-color: {COLOR_BG_SECONDARY};
                gridline-color: #333333;
                color: {COLOR_TEXT_PRIMARY};
            }}
            QTableWidget::item:selected {{
                background-color: {COLOR_BTN_PRIMARY};
                color: {COLOR_TEXT_BRIGHT};
            }}
            QHeaderView::section {{
                background-color: {COLOR_BG_SECONDARY};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid #333333;
                padding: 4px;
            }}
            """
        )
        header = table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
            header.setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
        return table

    def refresh(self, repo: Repository) -> None:
        """Reload bigram data from DB and repopulate tables."""
        self._repo = repo
        self._selected.clear()
        self._refresh_error_table(repo)
        self._refresh_time_table(repo)
        self._update_selection_display()
        print(
            f"[BigramChart] refresh done: "
            f"{self._error_table.rowCount()} error rows, "
            f"{self._time_table.rowCount()} time rows"
        )

    def _on_refresh_clicked(self) -> None:
        """Handle manual refresh button click."""
        if self._repo is not None:
            print("[BigramChart] manual refresh triggered")
            self.refresh(self._repo)
        else:
            print("[BigramChart] manual refresh: no repo available yet")

    def _refresh_error_table(self, repo: Repository) -> None:
        """Populate the error-prone bigrams table."""
        self._error_data = repo.get_bigram_error_rates(
            min_count=_DISPLAY_MIN_COUNT,
            practice_types=_ANALYSIS_PRACTICE_TYPES,
        )
        print(
            f"[BigramChart] error query returned {len(self._error_data)} rows "
            f"(min_count={_DISPLAY_MIN_COUNT}, "
            f"practice_types={_ANALYSIS_PRACTICE_TYPES})"
        )

        self._error_table.setRowCount(len(self._error_data))
        for row, (prev_c, exp_c, errors, total, rate) in enumerate(
            self._error_data
        ):
            bigram_label = _format_bigram(prev_c, exp_c)
            self._error_table.setItem(
                row, 0, QTableWidgetItem(bigram_label)
            )
            self._error_table.setItem(
                row, 1, _right_aligned_item(str(errors))
            )
            self._error_table.setItem(
                row, 2, _right_aligned_item(str(total))
            )
            self._error_table.setItem(
                row, 3, _right_aligned_item(f"{rate * 100:.1f}%")
            )

    def _refresh_time_table(self, repo: Repository) -> None:
        """Populate the slow bigrams table."""
        raw = repo.get_bigram_transition_times(
            min_count=_DISPLAY_MIN_COUNT,
            practice_types=_ANALYSIS_PRACTICE_TYPES,
        )
        print(
            f"[BigramChart] time query returned {len(raw)} rows "
            f"(min_count={_DISPLAY_MIN_COUNT}, "
            f"practice_types={_ANALYSIS_PRACTICE_TYPES})"
        )

        # Compute trimmed mean for each bigram
        self._time_data = []
        for prev_c, exp_c, rts, count in raw:
            tm = trimmed_mean(rts, fraction=0.10)
            self._time_data.append((prev_c, exp_c, tm, count))

        # Sort by trimmed mean descending (slowest first)
        self._time_data.sort(key=lambda x: x[2], reverse=True)

        self._time_table.setRowCount(len(self._time_data))
        for row, (prev_c, exp_c, tm, count) in enumerate(self._time_data):
            bigram_label = _format_bigram(prev_c, exp_c)
            self._time_table.setItem(
                row, 0, QTableWidgetItem(bigram_label)
            )
            self._time_table.setItem(
                row, 1, _right_aligned_item(f"{tm:.0f}")
            )
            self._time_table.setItem(
                row, 2, _right_aligned_item(str(count))
            )

    def _on_error_selection_changed(self) -> None:
        """Handle selection change in the error table."""
        self._sync_selection_from_tables()

    def _on_time_selection_changed(self) -> None:
        """Handle selection change in the time table."""
        self._sync_selection_from_tables()

    def _sync_selection_from_tables(self) -> None:
        """Merge selections from both tables into _selected."""
        self._selected.clear()

        # From error table
        for row in self._get_selected_rows(self._error_table):
            if row < len(self._error_data):
                prev_c, exp_c = self._error_data[row][0], self._error_data[row][1]
                self._selected.add((prev_c, exp_c))

        # From time table
        for row in self._get_selected_rows(self._time_table):
            if row < len(self._time_data):
                prev_c, exp_c = self._time_data[row][0], self._time_data[row][1]
                self._selected.add((prev_c, exp_c))

        self._update_selection_display()

    def _get_selected_rows(self, table: QTableWidget) -> list[int]:
        """Get unique selected row indices from a table."""
        return list({item.row() for item in table.selectedItems()})

    def _update_selection_display(self) -> None:
        """Update the selection summary label and button state."""
        n = len(self._selected)
        if n == 0:
            self._selection_label.setText("No bigrams selected")
            self._selection_label.setStyleSheet(
                f"color: {COLOR_TEXT_SECONDARY};"
            )
        else:
            bigram_strs = [
                _format_bigram(a, b) for a, b in sorted(self._selected)
            ]
            text = f"Selected: {', '.join(bigram_strs)}"
            if n > self._max_targets:
                text += f"  (max {self._max_targets} — deselect some)"
                self._selection_label.setStyleSheet("color: #cc8800;")
            else:
                self._selection_label.setStyleSheet(
                    f"color: {COLOR_TEXT_PRIMARY};"
                )
            self._selection_label.setText(text)

        self._start_btn.setEnabled(0 < n <= self._max_targets)
        self._update_button_style()

    def _update_button_style(self) -> None:
        """Update button appearance based on enabled state."""
        if self._start_btn.isEnabled():
            self._start_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {COLOR_BTN_PRIMARY};
                    color: {COLOR_TEXT_BRIGHT};
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {COLOR_BTN_HOVER};
                }}
                QPushButton:pressed {{
                    background-color: {COLOR_BTN_PRESSED};
                }}
                """
            )
        else:
            self._start_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {COLOR_BTN_DISABLED_BG};
                    color: {COLOR_BTN_DISABLED_TEXT};
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                }}
                """
            )

    def _on_start_clicked(self) -> None:
        """Emit the selected bigrams for transition training."""
        selected_list = sorted(self._selected)
        self.bigrams_selected.emit(selected_list)

    def get_selected_bigrams(self) -> list[tuple[str, str]]:
        """Return the currently selected bigrams."""
        return sorted(self._selected)

    def set_max_targets(self, n: int) -> None:
        """Set the maximum number of selectable bigrams."""
        self._max_targets = n
        self._update_selection_display()


def _format_bigram(a: str, b: str) -> str:
    """Format a bigram pair for display."""
    a_label = "SPC" if a == " " else a
    b_label = "SPC" if b == " " else b
    return f"{a_label}\u2192{b_label}"


def _right_aligned_item(text: str) -> QTableWidgetItem:
    """Create a right-aligned table item."""
    item = QTableWidgetItem(text)
    item.setTextAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    return item
