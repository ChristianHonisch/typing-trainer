"""Analytics container with two rows of tab labels and a shared plot area.

In Nerd display mode only the upper tab bar is visible.
In Extreme Nerd mode both tab bar rows are visible.
Only one tab is selected across both rows; the shared plot area below
fills all remaining height.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QStackedWidget, QTabBar, QVBoxLayout, QWidget

from typing_trainer.config import Config
from typing_trainer.models.keyboard_layout import KeyboardLayout, load_keyboard
from typing_trainer.models.letter_state import DisplayMode
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.charts.accuracy_chart import AccuracyChart
from typing_trainer.ui.charts.bigram_chart import BigramChart
from typing_trainer.ui.charts.confusion_matrix_chart import ConfusionMatrixChart
from typing_trainer.ui.charts.error_heatmap import ErrorHeatmap
from typing_trainer.ui.charts.keystroke_accuracy_chart import KeystrokeAccuracyChart
from typing_trainer.ui.charts.keystroke_rt_chart import KeystrokeRtChart
from typing_trainer.ui.charts.error_timeline_chart import ErrorTimelineChart
from typing_trainer.ui.charts.error_window_chart import ErrorWindowChart
from typing_trainer.ui.charts.letter_occurrence_chart import LetterOccurrenceChart
from typing_trainer.ui.charts.per_letter_chart import PerLetterChart
from typing_trainer.ui.charts.per_letter_rt_chart import PerLetterRtChart
from typing_trainer.ui.charts.position_chart import PositionChart
from typing_trainer.ui.charts.run_speed_chart import RunSpeedChart
from typing_trainer.ui.charts.swap_chart import SwapChart
from typing_trainer.ui.charts.wpm_chart import WpmChart
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_BG_SECONDARY,
    COLOR_BG_TERTIARY,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    app_font,
)

_TAB_BAR_STYLE = f"""
    QTabBar::tab {{
        background: {COLOR_BG_SECONDARY};
        color: {COLOR_TEXT_SECONDARY};
        padding: 6px 16px;
        border: 1px solid {COLOR_BG_TERTIARY};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {COLOR_BG_DARK};
        color: {COLOR_TEXT_PRIMARY};
    }}
"""

# Inactive bar: selected tab looks the same as unselected
_TAB_BAR_INACTIVE_STYLE = f"""
    QTabBar::tab {{
        background: {COLOR_BG_SECONDARY};
        color: {COLOR_TEXT_SECONDARY};
        padding: 6px 16px;
        border: 1px solid {COLOR_BG_TERTIARY};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {COLOR_BG_SECONDARY};
        color: {COLOR_TEXT_SECONDARY};
    }}
"""

_NERD_TAB_COUNT = 7  # number of tabs in the upper (nerd) row


class AnalyticsWidget(QWidget):
    """Two rows of tab labels with a single shared plot area."""

    def __init__(
        self,
        config: Config | None = None,
        keyboard_layout: KeyboardLayout | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config or Config()
        self._keyboard_layout = keyboard_layout or load_keyboard(
            self._config.keyboard_layout
        )
        self._active_bar = "nerd"
        self._setup_ui()

    def set_runtime_dependencies(
        self,
        config: Config,
        keyboard_layout: KeyboardLayout,
    ) -> None:
        """Update config/layout after a profile or settings change."""
        self._config = config
        self._keyboard_layout = keyboard_layout
        self._error_heatmap.set_keyboard_layout(keyboard_layout)
        self._confusion_matrix.set_keyboard_layout(keyboard_layout)
        self._error_timeline_chart.set_keyboard_layout(keyboard_layout)
        self._error_window_chart._config = config

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)

        # --- Upper tab bar (nerd tier) ---
        self._nerd_bar = QTabBar()
        self._nerd_bar.setFont(app_font(11))
        self._nerd_bar.setStyleSheet(_TAB_BAR_STYLE)
        self._nerd_bar.setDrawBase(False)

        for label in (
            "Accuracy",
            "Per-Letter Accuracy",
            "WPM",
            "Letter Speed",
            "Bigrams",
            "Error Timeline",
            "Letter Frequency",
        ):
            self._nerd_bar.addTab(label)

        self._nerd_bar.tabBarClicked.connect(self._on_nerd_tab_clicked)
        layout.addWidget(self._nerd_bar)

        # --- Lower tab bar (extreme nerd tier) ---
        self._extreme_bar = QTabBar()
        self._extreme_bar.setFont(app_font(11))
        self._extreme_bar.setStyleSheet(_TAB_BAR_STYLE)
        self._extreme_bar.setDrawBase(False)

        for label in (
            "Error Breakdown",
            "Confusion Matrix",
            "Swaps",
            "Error by Position",
            "Run Speed",
            "Error Window",
            "Accuracy by Keystroke",
            "RT by Keystroke",
        ):
            self._extreme_bar.addTab(label)

        self._extreme_bar.tabBarClicked.connect(self._on_extreme_tab_clicked)
        layout.addWidget(self._extreme_bar)

        # --- Shared plot area ---
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(
            f"border: 1px solid {COLOR_BG_TERTIARY}; background: {COLOR_BG_DARK};"
        )

        # Nerd-tier charts (indices 0–6)
        self._accuracy_chart = AccuracyChart()
        self._per_letter_chart = PerLetterChart()
        self._wpm_chart = WpmChart()
        self._per_letter_rt_chart = PerLetterRtChart()
        self._bigram_chart = BigramChart()
        self._error_timeline_chart = ErrorTimelineChart(self._keyboard_layout)
        self._letter_occurrence_chart = LetterOccurrenceChart()

        self._stack.addWidget(self._accuracy_chart)
        self._stack.addWidget(self._per_letter_chart)
        self._stack.addWidget(self._wpm_chart)
        self._stack.addWidget(self._per_letter_rt_chart)
        self._stack.addWidget(self._bigram_chart)
        self._stack.addWidget(self._error_timeline_chart)
        self._stack.addWidget(self._letter_occurrence_chart)

        # Extreme-tier charts (indices 7–14)
        self._error_heatmap = ErrorHeatmap(self._keyboard_layout)
        self._confusion_matrix = ConfusionMatrixChart(self._keyboard_layout)
        self._swap_chart = SwapChart()
        self._position_chart = PositionChart()
        self._run_speed_chart = RunSpeedChart()
        self._error_window_chart = ErrorWindowChart(self._config)
        self._keystroke_accuracy_chart = KeystrokeAccuracyChart()
        self._keystroke_rt_chart = KeystrokeRtChart()

        self._stack.addWidget(self._error_heatmap)
        self._stack.addWidget(self._confusion_matrix)
        self._stack.addWidget(self._swap_chart)
        self._stack.addWidget(self._position_chart)
        self._stack.addWidget(self._run_speed_chart)
        self._stack.addWidget(self._error_window_chart)
        self._stack.addWidget(self._keystroke_accuracy_chart)
        self._stack.addWidget(self._keystroke_rt_chart)

        layout.addWidget(self._stack, stretch=1)

        # Start with nerd tab 0 selected
        self._nerd_bar.setCurrentIndex(0)
        self._stack.setCurrentIndex(0)
        self._apply_bar_styles()

    def _on_nerd_tab_clicked(self, index: int) -> None:
        self._active_bar = "nerd"
        self._apply_bar_styles()
        self._stack.setCurrentIndex(index)

    def _on_extreme_tab_clicked(self, index: int) -> None:
        self._active_bar = "extreme"
        self._apply_bar_styles()
        self._stack.setCurrentIndex(_NERD_TAB_COUNT + index)

    def _apply_bar_styles(self) -> None:
        """Style the active bar with highlight, inactive bar without."""
        self._nerd_bar.setStyleSheet(
            _TAB_BAR_STYLE if self._active_bar == "nerd" else _TAB_BAR_INACTIVE_STYLE
        )
        self._extreme_bar.setStyleSheet(
            _TAB_BAR_STYLE
            if self._active_bar == "extreme"
            else _TAB_BAR_INACTIVE_STYLE
        )

    @property
    def bigram_chart(self) -> BigramChart:
        """Access the bigram chart widget (for signal wiring)."""
        return self._bigram_chart

    def set_display_mode(self, mode: DisplayMode) -> None:
        """Show/hide tab tiers based on the display mode.

        - NERD: upper tab bar only
        - EXTREME_NERD: both tab bar rows
        - BASIC: caller hides the entire AnalyticsWidget
        """
        self._nerd_bar.setVisible(mode != DisplayMode.BASIC)
        self._stack.setVisible(mode != DisplayMode.BASIC)

        was_extreme = self._extreme_bar.isVisible()
        is_extreme = mode == DisplayMode.EXTREME_NERD
        self._extreme_bar.setVisible(is_extreme)

        # If leaving extreme nerd with an extreme tab selected, switch to nerd tab 0
        if was_extreme and not is_extreme:
            if self._active_bar == "extreme":
                self._active_bar = "nerd"
                self._nerd_bar.setCurrentIndex(0)
                self._stack.setCurrentIndex(0)
                self._apply_bar_styles()

    def refresh(self, repo: Repository) -> None:
        """Refresh all charts with current data."""
        # Nerd tier
        self._accuracy_chart.refresh(repo)
        self._per_letter_chart.refresh(repo)
        self._wpm_chart.refresh(repo)
        self._per_letter_rt_chart.refresh(repo)
        self._bigram_chart.refresh(repo)
        self._error_timeline_chart.refresh(repo)
        self._letter_occurrence_chart.refresh(repo)

        # Extreme tier
        self._error_heatmap.refresh(repo)
        self._confusion_matrix.refresh(repo)
        self._swap_chart.refresh(repo)
        self._position_chart.refresh(repo)
        self._run_speed_chart.refresh(repo)
        self._error_window_chart.refresh(repo)
        self._keystroke_accuracy_chart.refresh(repo)
        self._keystroke_rt_chart.refresh(repo)
