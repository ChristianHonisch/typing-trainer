"""Error rate by absolute position within runs.

Shows how error rate varies across keystroke positions, with Wilson
score 95% confidence interval error bars.  Helps identify warm-up
effects (elevated errors at start) and fatigue effects (elevated
errors toward end).

Position is absolute (character index), not relative to run length,
because fatigue is time/keystroke-based rather than proportional.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_INFO,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)

_BUCKET_SIZE = 5
_Z = 1.96  # 95% confidence


def _wilson_interval(
    errors: int, total: int, z: float = _Z
) -> tuple[float, float, float]:
    """Compute Wilson score confidence interval for a proportion.

    Args:
        errors: Number of errors (successes in binomial terms).
        total: Total trials.
        z: Z-score for desired confidence level (1.96 for 95%).

    Returns:
        ``(center, lower, upper)`` as proportions (0-1).
    """
    if total == 0:
        return 0.0, 0.0, 0.0

    p = errors / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = z * (p * (1.0 - p) / total + z2 / (4.0 * total * total)) ** 0.5 / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return center, lower, upper


class PositionChart(QWidget):
    """Bar chart of error rate by position with Wilson CI error bars."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=False, y=True, alpha=0.15)
        self._plot.setLabel(
            "left", "Error Rate %", color=COLOR_TEXT_PRIMARY
        )
        self._plot.setLabel(
            "bottom", "Position in Run", color=COLOR_TEXT_PRIMARY
        )
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)

        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Reload data from DB and redraw."""
        self._plot.clear()

        buckets = repo.get_error_rate_by_position(bucket_size=_BUCKET_SIZE)
        if not buckets:
            return

        n = len(buckets)
        # X positions: center of each bucket
        x = np.array(
            [start + _BUCKET_SIZE / 2.0 for start, _, _ in buckets],
            dtype=np.float64,
        )
        rates = np.zeros(n, dtype=np.float64)
        lower = np.zeros(n, dtype=np.float64)
        upper = np.zeros(n, dtype=np.float64)

        for i, (_, errors, total) in enumerate(buckets):
            center, lo, hi = _wilson_interval(errors, total)
            rates[i] = center * 100
            lower[i] = lo * 100
            upper[i] = hi * 100

        # Compute overall average error rate for reference line
        total_errors = sum(e for _, e, _ in buckets)
        total_keystrokes = sum(t for _, _, t in buckets)
        avg_rate = (total_errors / total_keystrokes * 100) if total_keystrokes > 0 else 0.0

        # Bar chart
        bar = pg.BarGraphItem(
            x=x,
            height=rates,
            width=_BUCKET_SIZE * 0.8,
            brush=QColor(COLOR_INFO),
        )
        self._plot.addItem(bar)

        # Error bars (Wilson 95% CI)
        err_bar = pg.ErrorBarItem(
            x=x,
            y=rates,
            top=upper - rates,
            bottom=rates - lower,
            pen=pg.mkPen(COLOR_WARNING, width=1.5),
            beam=_BUCKET_SIZE * 0.3,
        )
        self._plot.addItem(err_bar)

        # Average reference line
        avg_line = pg.InfiniteLine(
            pos=avg_rate,
            angle=0,
            pen=pg.mkPen(COLOR_TEXT_SECONDARY, width=1, style=Qt.PenStyle.DashLine),
        )
        self._plot.addItem(avg_line)

        # Label for the average line
        avg_text = pg.TextItem(
            f"avg {avg_rate:.1f}%",
            color=COLOR_TEXT_SECONDARY,
            anchor=(0.0, 1.0),
        )
        avg_text.setPos(float(x[0]), avg_rate)
        self._plot.addItem(avg_text)

        # X-axis tick labels: "0-4", "5-9", etc.
        tick_labels = [
            (float(x[i]), f"{buckets[i][0]}-{buckets[i][0] + _BUCKET_SIZE - 1}")
            for i in range(n)
        ]
        self._plot.getAxis("bottom").setTicks([tick_labels])
