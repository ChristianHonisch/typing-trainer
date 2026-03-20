"""Keyboard layout loading and derived geometry helpers.

Layouts are stored as JSON files in ``data/keyboards``. A layout file
contains the finger map, physical rows/columns, mirror pairs, and
language-specific letter frequencies / introduction orders.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class KeyboardLanguageData:
    """Language-specific keyboard data."""

    frequencies: dict[str, float]
    introduction_order: list[str]


@dataclass(frozen=True)
class KeyboardLayout:
    """Fully loaded keyboard layout with derived geometry lookups."""

    name: str
    display_name: str
    rows: list[list[str]]
    row_offsets: list[float]
    columns: list[set[str]]
    fingers: dict[str, int]
    mirror_pairs: dict[str, str | None]
    languages: dict[str, KeyboardLanguageData]
    row_of: dict[str, int]
    column_of: dict[str, int]
    adjacency: dict[str, set[str]]

    def get_frequencies(self, language: str) -> dict[str, float]:
        """Get per-letter frequencies for a language."""
        if language not in self.languages:
            raise ValueError(
                f"Unsupported language '{language}' for layout '{self.name}'"
            )
        return dict(self.languages[language].frequencies)

    def get_introduction_order(self, language: str) -> list[str]:
        """Get introduction order for a language."""
        if language not in self.languages:
            raise ValueError(
                f"Unsupported language '{language}' for layout '{self.name}'"
            )
        return list(self.languages[language].introduction_order)


_KEYBOARD_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "keyboards"
)


def _build_adjacency(
    rows: list[list[str]], row_offsets: list[float]
) -> dict[str, set[str]]:
    """Build adjacency map from row geometry and stagger offsets."""
    pos: dict[str, tuple[int, float]] = {}
    for row_idx, (row_keys, offset) in enumerate(zip(rows, row_offsets)):
        for col_idx, key in enumerate(row_keys):
            pos[key] = (row_idx, col_idx + offset)

    adj: dict[str, set[str]] = {k: set() for k in pos}
    keys = list(pos.keys())
    for i, k1 in enumerate(keys):
        r1, c1 = pos[k1]
        for k2 in keys[i + 1 :]:
            r2, c2 = pos[k2]
            row_dist = abs(r1 - r2)
            col_dist = abs(c1 - c2)

            is_adjacent = False
            if row_dist == 0 and 0 < col_dist <= 1.0:
                is_adjacent = True
            elif row_dist == 1 and col_dist <= 1.0:
                is_adjacent = True

            if is_adjacent:
                adj[k1].add(k2)
                adj[k2].add(k1)

    return adj


def list_keyboards() -> list[str]:
    """List available keyboard layout names."""
    if not _KEYBOARD_DIR.exists():
        return []
    return sorted(path.stem for path in _KEYBOARD_DIR.glob("*.json"))


@lru_cache(maxsize=None)
def load_keyboard(name: str = "qwertz") -> KeyboardLayout:
    """Load a keyboard layout from ``data/keyboards/<name>.json``."""
    path = _KEYBOARD_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(f"Unknown keyboard layout: {name}")

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    rows: list[list[str]] = [list(row) for row in raw["rows"]]
    row_offsets: list[float] = [float(v) for v in raw["row_offsets"]]
    columns = [set(col) for col in raw["columns"]]
    fingers = {str(k): int(v) for k, v in raw["fingers"].items()}
    mirror_pairs = {
        str(k): (None if v is None else str(v)) for k, v in raw["mirror_pairs"].items()
    }

    languages: dict[str, KeyboardLanguageData] = {}
    for lang, payload in raw["languages"].items():
        languages[str(lang)] = KeyboardLanguageData(
            frequencies={str(k): float(v) for k, v in payload["frequencies"].items()},
            introduction_order=[str(ch) for ch in payload["introduction_order"]],
        )

    row_of: dict[str, int] = {}
    for row_idx, row in enumerate(rows):
        for key in row:
            row_of[key] = row_idx

    column_of: dict[str, int] = {}
    for col_idx, col in enumerate(columns):
        for key in col:
            column_of[key] = col_idx

    adjacency = _build_adjacency(rows, row_offsets)

    return KeyboardLayout(
        name=str(raw["name"]),
        display_name=str(raw.get("display_name", raw["name"])),
        rows=rows,
        row_offsets=row_offsets,
        columns=columns,
        fingers=fingers,
        mirror_pairs=mirror_pairs,
        languages=languages,
        row_of=row_of,
        column_of=column_of,
        adjacency=adjacency,
    )


def get_letter_frequencies(
    language: str, layout_name: str = "qwertz"
) -> dict[str, float]:
    """Backward-compatible helper returning frequencies for a layout+language."""
    return load_keyboard(layout_name).get_frequencies(language)


def get_introduction_order(language: str, layout_name: str = "qwertz") -> list[str]:
    """Backward-compatible helper returning introduction order."""
    return load_keyboard(layout_name).get_introduction_order(language)


# Backward-compatible convenience constants for the default QWERTZ layout.
QWERTZ_LAYOUT = load_keyboard("qwertz")
QWERTZ_FINGER_MAP = dict(QWERTZ_LAYOUT.fingers)
QWERTZ_ADJACENCY = {k: set(v) for k, v in QWERTZ_LAYOUT.adjacency.items()}
