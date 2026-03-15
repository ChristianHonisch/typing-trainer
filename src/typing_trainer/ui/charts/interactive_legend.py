"""Reusable hover-interactive legend for pyqtgraph charts.

When the user hovers over a legend entry, the corresponding plot line
is highlighted (thicker pen) and all other lines are dimmed.  Leaving
the legend restores the original appearance.

Supports an optional second set of curves (``extra_curves``) so that a
single legend can control lines across two plot panels simultaneously
(e.g. the split-axis per-letter RT chart).
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor


class InteractiveLegend:
    """Adds hover-to-highlight behaviour to a standard pyqtgraph legend.

    Usage::

        legend = plot_widget.addLegend(...)
        curves = {"label": plot_data_item, ...}
        interactive = InteractiveLegend(legend, curves)

    For dual-panel charts, pass a second dict of curves that share the
    same label names::

        interactive = InteractiveLegend(legend, panel1_curves,
                                        extra_curves=panel2_curves)

    The caller keeps a reference to this object for the lifetime of the
    chart (otherwise the event filter gets garbage-collected).
    """

    def __init__(
        self,
        legend: pg.LegendItem,
        curves: dict[str, pg.PlotDataItem],
        extra_curves: dict[str, pg.PlotDataItem] | None = None,
        normal_width: float = 1.5,
        highlight_width: float = 3.5,
        dim_alpha: int = 50,
    ) -> None:
        self._legend = legend
        self._curves = curves
        self._extra_curves = extra_curves or {}
        self._normal_width = normal_width
        self._highlight_width = highlight_width
        self._dim_alpha = dim_alpha

        # Store original pens so we can restore them
        self._original_pens: dict[str, Any] = {}
        for name, curve in curves.items():
            self._original_pens[name] = curve.opts["pen"]

        self._extra_original_pens: dict[str, Any] = {}
        for name, curve in self._extra_curves.items():
            self._extra_original_pens[name] = curve.opts["pen"]

        # Install hover events on each legend entry (sample + label)
        for sample, label in legend.items:
            name = label.text
            if name not in curves:
                continue
            sample.setAcceptHoverEvents(True)
            label.setAcceptHoverEvents(True)
            sample.installSceneEventFilter(self._make_filter(name, legend))
            label.installSceneEventFilter(self._make_filter(name, legend))

    def _make_filter(
        self,
        name: str,
        parent: pg.LegendItem,
    ) -> _HoverFilter:
        return _HoverFilter(name, self, parent)

    def _apply(
        self,
        curve_dict: dict[str, pg.PlotDataItem],
        pen_dict: dict[str, Any],
        highlighted_name: str | None,
    ) -> None:
        """Set pens on a dict of curves.

        If *highlighted_name* is ``None`` all pens are restored to their
        originals.  Otherwise the named curve is highlighted and the
        rest are dimmed.
        """
        for curve_name, curve in curve_dict.items():
            pen = pen_dict.get(curve_name)
            if pen is None:
                continue
            if highlighted_name is None:
                curve.setPen(pen)
            elif curve_name == highlighted_name:
                new_pen = pg.mkPen(pen.color(), width=self._highlight_width)
                curve.setPen(new_pen)
            else:
                color = QColor(pen.color())  # clone to avoid mutating original
                color.setAlpha(self._dim_alpha)
                new_pen = pg.mkPen(color, width=self._normal_width)
                curve.setPen(new_pen)

    def highlight(self, name: str) -> None:
        """Highlight *name* and dim everything else."""
        self._apply(self._curves, self._original_pens, name)
        if self._extra_curves:
            self._apply(self._extra_curves, self._extra_original_pens, name)

    def restore(self) -> None:
        """Restore all curves to their original pens."""
        self._apply(self._curves, self._original_pens, None)
        if self._extra_curves:
            self._apply(self._extra_curves, self._extra_original_pens, None)


class _HoverFilter(pg.GraphicsWidget):
    """Scene event filter that detects hover enter/leave on a legend item."""

    def __init__(
        self,
        name: str,
        handler: InteractiveLegend,
        parent: pg.LegendItem,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._handler = handler

    def sceneEventFilter(self, watched: Any, event: Any) -> bool:
        if event.type() == QEvent.Type.GraphicsSceneHoverEnter:
            self._handler.highlight(self._name)
            return False
        if event.type() == QEvent.Type.GraphicsSceneHoverLeave:
            self._handler.restore()
            return False
        return False
