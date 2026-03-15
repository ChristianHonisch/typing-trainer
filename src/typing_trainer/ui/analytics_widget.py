"""Analytics container with two tiers of chart tabs.

Nerd-tier tabs (upper):
  - Accuracy, Accuracy (Letter), WPM, Per-Letter RT, Bigrams,
    Error Timeline, Letter %

Extreme-Nerd-tier tabs (lower):
  - Errors, Confusion Matrix, Swaps, Position, Run Speed, Error Window

In Nerd display mode only the upper tier is shown.
In Extreme Nerd mode both tiers are visible.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QSplitter, QTabWidget, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt

from typing_trainer.config import Config
from typing_trainer.models.letter_state import DisplayMode
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.charts.accuracy_chart import AccuracyChart
from typing_trainer.ui.charts.bigram_chart import BigramChart
from typing_trainer.ui.charts.confusion_matrix_chart import ConfusionMatrixChart
from typing_trainer.ui.charts.error_heatmap import ErrorHeatmap
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

_TAB_STYLE = f"""
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
    QTabWidget::pane {{
        border: 1px solid {COLOR_BG_TERTIARY};
        background: {COLOR_BG_DARK};
    }}
"""


class AnalyticsWidget(QWidget):
    """Container for all analytics charts, organized in two tab tiers."""

    def __init__(
        self,
        config: Config | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config or Config()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Vertical splitter: nerd tabs on top, extreme tabs on bottom
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Nerd-tier tabs (upper) ---
        self._nerd_tabs = QTabWidget()
        self._nerd_tabs.setFont(app_font(11))
        self._nerd_tabs.setStyleSheet(_TAB_STYLE)

        self._accuracy_chart = AccuracyChart()
        self._per_letter_chart = PerLetterChart()
        self._wpm_chart = WpmChart()
        self._per_letter_rt_chart = PerLetterRtChart()
        self._bigram_chart = BigramChart()
        self._error_timeline_chart = ErrorTimelineChart()
        self._letter_occurrence_chart = LetterOccurrenceChart()

        self._nerd_tabs.addTab(self._accuracy_chart, "Accuracy")
        self._nerd_tabs.addTab(self._per_letter_chart, "Per-Letter Accuracy")
        self._nerd_tabs.addTab(self._wpm_chart, "WPM")
        self._nerd_tabs.addTab(self._per_letter_rt_chart, "Letter Speed")
        self._nerd_tabs.addTab(self._bigram_chart, "Bigrams")
        self._nerd_tabs.addTab(self._error_timeline_chart, "Error Timeline")
        self._nerd_tabs.addTab(self._letter_occurrence_chart, "Letter Frequency")

        self._splitter.addWidget(self._nerd_tabs)

        # --- Extreme-Nerd-tier tabs (lower) ---
        self._extreme_label = QLabel("  Deep Analysis")
        self._extreme_label.setFont(app_font(9))
        self._extreme_label.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; padding: 2px 0px;"
        )
        self._splitter.addWidget(self._extreme_label)

        self._extreme_tabs = QTabWidget()
        self._extreme_tabs.setFont(app_font(11))
        self._extreme_tabs.setStyleSheet(_TAB_STYLE)

        self._error_heatmap = ErrorHeatmap()
        self._confusion_matrix = ConfusionMatrixChart()
        self._swap_chart = SwapChart()
        self._position_chart = PositionChart()
        self._run_speed_chart = RunSpeedChart()
        self._error_window_chart = ErrorWindowChart(self._config)

        self._extreme_tabs.addTab(self._error_heatmap, "Error Breakdown")
        self._extreme_tabs.addTab(self._confusion_matrix, "Confusion Matrix")
        self._extreme_tabs.addTab(self._swap_chart, "Swaps")
        self._extreme_tabs.addTab(self._position_chart, "Error by Position")
        self._extreme_tabs.addTab(self._run_speed_chart, "Run Speed")
        self._extreme_tabs.addTab(self._error_window_chart, "Error Window")

        self._splitter.addWidget(self._extreme_tabs)

        # Prevent collapsing either tier to zero
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setCollapsible(2, False)

        layout.addWidget(self._splitter)

    @property
    def bigram_chart(self) -> BigramChart:
        """Access the bigram chart widget (for signal wiring)."""
        return self._bigram_chart

    def set_display_mode(self, mode: DisplayMode) -> None:
        """Show/hide tab tiers based on the display mode.

        - NERD: upper tabs only
        - EXTREME_NERD: both tiers
        - BASIC: caller hides the entire AnalyticsWidget
        """
        self._nerd_tabs.setVisible(mode != DisplayMode.BASIC)
        self._extreme_label.setVisible(mode == DisplayMode.EXTREME_NERD)
        self._extreme_tabs.setVisible(mode == DisplayMode.EXTREME_NERD)

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
