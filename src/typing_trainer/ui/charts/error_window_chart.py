"""Error window chart for the analysis tab.

Shows the rolling accuracy window for each active letter as a horizontal
strip.  Red ``x`` markers indicate cognitive errors; the x-axis is the
position within the window (0 = oldest, window-1 = newest).

A text annotation to the right of each row shows either a green
checkmark (letter meets the advancement accuracy) or the number of
additional correct keystrokes needed before the excess errors age out
of the window.
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from typing_trainer.config import Config
from typing_trainer.storage.repository import Repository
from typing_trainer.ui.theme import (
    COLOR_BG_DARK,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    app_font,
)


class ErrorWindowChart(QWidget):
    """Per-letter error window visualisation."""

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(COLOR_BG_DARK)
        self._plot.showGrid(x=True, y=False, alpha=0.15)
        self._plot.setLabel(
            "bottom", "Position in window (oldest \u2192 newest)",
            color=COLOR_TEXT_PRIMARY,
        )
        self._plot.getAxis("left").setTextPen(COLOR_TEXT_SECONDARY)
        self._plot.getAxis("bottom").setTextPen(COLOR_TEXT_SECONDARY)
        layout.addWidget(self._plot)

    def refresh(self, repo: Repository) -> None:
        """Redraw with current data from the repository."""
        self._plot.clear()

        window = self._config.advancement_accuracy_window
        threshold = self._config.advancement_accuracy
        max_errors = math.floor(window * (1.0 - threshold))

        # Get all letters that have data
        all_error_rates = repo.get_per_letter_error_rates()
        letters = sorted(all_error_rates.keys())
        if not letters:
            return

        error_window = repo.get_per_letter_error_window(letters, window)
        if not error_window:
            return

        # Filter to letters that actually have data, sort alphabetically
        letters_with_data = sorted(error_window.keys())
        if not letters_with_data:
            return

        n_letters = len(letters_with_data)

        # ── Collect scatter data ──
        err_x: list[float] = []
        err_y: list[float] = []

        # ── Text annotations ──
        annotations: list[tuple[float, float, str, str]] = []  # x, y, text, color

        for row_idx, letter in enumerate(letters_with_data):
            sequence = error_window[letter]
            seq_len = len(sequence)

            # Find error positions
            error_positions = [i for i, is_err in enumerate(sequence) if is_err]
            n_errors = len(error_positions)

            for pos in error_positions:
                err_x.append(float(pos))
                err_y.append(float(row_idx))

            # Compute annotation
            if n_errors <= max_errors:
                annotations.append((
                    float(seq_len + 2), float(row_idx),
                    "\u2713", COLOR_SUCCESS,
                ))
            else:
                # How many correct keystrokes needed?
                # We need to push out enough old errors so that only
                # max_errors remain.  The errors that need to age out
                # are the oldest (excess) errors.  Once the window
                # slides past the last of these, we're clear.
                excess = n_errors - max_errors
                # error_positions is in oldest-first order
                # The (excess)th oldest error is at index (excess - 1)
                last_excess_pos = error_positions[excess - 1]
                # Keystrokes needed = enough new keystrokes to push
                # the window start past last_excess_pos.
                # Current window covers positions [0, seq_len-1].
                # After K new keystrokes the window covers
                # [K, K+seq_len-1] (if seq_len == window) or the
                # window simply grows until it hits the limit.
                if seq_len >= window:
                    # Window is full — each new keystroke shifts it by 1
                    keystrokes_needed = last_excess_pos + 1
                else:
                    # Window not yet full — new keystrokes extend it
                    # until it reaches window size, then start shifting.
                    # Need the window to grow to window size AND then
                    # shift past last_excess_pos.
                    grow_room = window - seq_len
                    keystrokes_needed = max(0, last_excess_pos + 1 - grow_room)

                annotations.append((
                    float(max(seq_len, window) + 2), float(row_idx),
                    f"need {keystrokes_needed}", COLOR_WARNING,
                ))

        # ── Draw error markers ──
        if err_x:
            self._plot.plot(
                np.array(err_x, dtype=np.float64),
                np.array(err_y, dtype=np.float64),
                pen=None,
                symbol="x",
                symbolSize=9,
                symbolBrush=COLOR_ERROR,
                symbolPen=pg.mkPen(COLOR_ERROR, width=2),
            )

        # ── Draw threshold line ──
        # Vertical line at the window boundary
        self._plot.addLine(
            x=window,
            pen=pg.mkPen(COLOR_TEXT_MUTED, width=1, style=Qt.PenStyle.DashLine),
        )

        # ── Text annotations ──
        for ax, ay, text, color in annotations:
            ti = pg.TextItem(text, color=color, anchor=(0, 0.5))
            ti.setFont(app_font(10, bold=True))
            ti.setPos(ax, ay)
            self._plot.addItem(ti)

        # ── Y-axis: letter labels ──
        left_axis = self._plot.getAxis("left")
        ticks = [(float(i), letter.upper()) for i, letter in enumerate(letters_with_data)]
        left_axis.setTicks([ticks, []])  # suppress auto/minor ticks
        left_axis.setStyle(tickFont=app_font(11))

        # ── Ranges ──
        x_max = max(window + 20, max((a[0] for a in annotations), default=window) + 60)
        self._plot.getViewBox().setXRange(-2, x_max, padding=0)
        self._plot.getViewBox().setYRange(-0.8, n_letters - 0.2, padding=0)
