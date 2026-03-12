"""Analytics container with sub-tabs for different chart types.

Sub-tabs:
  - Accuracy: per-run accuracy over time
  - WPM: per-run WPM over time
  - Per-Letter: rolling accuracy per letter with selector
  - Per-Letter RT: mean reaction time per letter with selector
  - Errors: stacked error rate per letter, by error type
  - Confusion Matrix: top confusion pairs bar chart + grid heatmap
  - Swaps: transposition error bigram bar chart
  - Position: error rate by position with Wilson CI error bars
"""

from __future__ import annotations

from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.charts.accuracy_chart import AccuracyChart
from typing_trainer.ui.charts.bigram_chart import BigramChart
from typing_trainer.ui.charts.confusion_matrix_chart import ConfusionMatrixChart
from typing_trainer.ui.charts.error_heatmap import ErrorHeatmap
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


class AnalyticsWidget(QWidget):
    """Container for all analytics charts, organized in sub-tabs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._tabs = QTabWidget()
        self._tabs.setFont(app_font(11))
        self._tabs.setStyleSheet(
            f"""
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
        )

        self._accuracy_chart = AccuracyChart()
        self._wpm_chart = WpmChart()
        self._per_letter_chart = PerLetterChart()
        self._per_letter_rt_chart = PerLetterRtChart()
        self._error_heatmap = ErrorHeatmap()
        self._confusion_matrix = ConfusionMatrixChart()
        self._swap_chart = SwapChart()
        self._position_chart = PositionChart()
        self._bigram_chart = BigramChart()
        self._run_speed_chart = RunSpeedChart()

        self._tabs.addTab(self._accuracy_chart, "Accuracy")
        self._tabs.addTab(self._wpm_chart, "WPM")
        self._tabs.addTab(self._per_letter_chart, "Per-Letter")
        self._tabs.addTab(self._per_letter_rt_chart, "Per-Letter RT")
        self._tabs.addTab(self._error_heatmap, "Errors")
        self._tabs.addTab(self._confusion_matrix, "Confusion Matrix")
        self._tabs.addTab(self._swap_chart, "Swaps")
        self._tabs.addTab(self._position_chart, "Position")
        self._tabs.addTab(self._bigram_chart, "Bigrams")
        self._tabs.addTab(self._run_speed_chart, "Run Speed")

        layout.addWidget(self._tabs)

    @property
    def bigram_chart(self) -> BigramChart:
        """Access the bigram chart widget (for signal wiring)."""
        return self._bigram_chart

    def refresh(self, repo: Repository) -> None:
        """Refresh all charts with current data."""
        self._accuracy_chart.refresh(repo)
        self._wpm_chart.refresh(repo)
        self._per_letter_chart.refresh(repo)
        self._per_letter_rt_chart.refresh(repo)
        self._error_heatmap.refresh(repo)
        self._confusion_matrix.refresh(repo)
        self._swap_chart.refresh(repo)
        self._position_chart.refresh(repo)
        self._bigram_chart.refresh(repo)
        self._run_speed_chart.refresh(repo)
