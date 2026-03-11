"""Keyboard layout definitions and letter introduction order.

v1 supports QWERTZ only.  Introduction order is curated for each
language, balancing ergonomics (home-row first, spread across fingers,
pinky keys deferred) with corpus frequency.
"""

from __future__ import annotations


# Finger assignments for QWERTZ layout.
# Maps each lowercase letter to the finger that should press it.
# Fingers numbered 0-9: 0=left pinky, 4=left thumb, 5=right thumb,
# 6=right index, 9=right pinky.
QWERTZ_FINGER_MAP: dict[str, int] = {
    # Left pinky (0)
    "q": 0, "a": 0, "y": 0,
    # Left ring (1)
    "w": 1, "s": 1, "x": 1,
    # Left middle (2)
    "e": 2, "d": 2, "c": 2,
    # Left index (3)
    "r": 3, "f": 3, "v": 3, "t": 3, "g": 3, "b": 3,
    # Right index (6)
    "z": 6, "h": 6, "n": 6, "u": 6, "j": 6, "m": 6,
    # Right middle (7)
    "i": 7, "k": 7,
    # Right ring (8)
    "o": 8, "l": 8,
    # Right pinky (9)
    "p": 9,
}

# Letter frequencies in German text (approximate, from large corpora).
# Lowercase only. Values are relative frequencies summing to ~1.0.
GERMAN_LETTER_FREQUENCIES: dict[str, float] = {
    "e": 0.1639, "n": 0.0978, "i": 0.0755, "s": 0.0727, "r": 0.0700,
    "a": 0.0651, "t": 0.0615, "d": 0.0508, "h": 0.0476, "u": 0.0435,
    "l": 0.0344, "c": 0.0306, "g": 0.0301, "m": 0.0253, "o": 0.0251,
    "b": 0.0189, "w": 0.0189, "f": 0.0166, "k": 0.0121, "z": 0.0113,
    "p": 0.0079, "v": 0.0067, "j": 0.0027, "x": 0.0003, "q": 0.0002,
    "y": 0.0004,
}

# Letter frequencies in English text (approximate).
ENGLISH_LETTER_FREQUENCIES: dict[str, float] = {
    "e": 0.1270, "t": 0.0906, "a": 0.0817, "o": 0.0751, "i": 0.0697,
    "n": 0.0675, "s": 0.0633, "h": 0.0609, "r": 0.0599, "d": 0.0425,
    "l": 0.0403, "c": 0.0278, "u": 0.0276, "m": 0.0241, "w": 0.0236,
    "f": 0.0223, "g": 0.0202, "y": 0.0197, "p": 0.0193, "b": 0.0129,
    "v": 0.0098, "k": 0.0077, "j": 0.0015, "x": 0.0015, "q": 0.0010,
    "z": 0.0007,
}


def get_letter_frequencies(language: str) -> dict[str, float]:
    """Get letter frequency table for a language.

    Args:
        language: 'de' for German, 'en' for English.

    Returns:
        Dict mapping lowercase letters to their relative frequencies.
    """
    if language == "de":
        return dict(GERMAN_LETTER_FREQUENCIES)
    elif language == "en":
        return dict(ENGLISH_LETTER_FREQUENCIES)
    else:
        raise ValueError(f"Unsupported language: {language}. Use 'de' or 'en'.")


# Curated introduction orders for QWERTZ layout.
#
# Design principles:
#   1. Start with high-frequency letters on easy keys.
#   2. Spread across different fingers early (one new finger per letter).
#   3. Home-row keys before reaches on the same finger.
#   4. Pinky keys deferred (weakest finger).
#   5. Language-specific frequency breaks ties.
#
# QWERTZ note: z is top-row right-index (easy), y is bottom-row left-pinky
# (hard).  This is the opposite of QWERTY, so z comes much earlier and y
# much later than in QWERTY-derived orders (e.g. keybr).

GERMAN_INTRODUCTION_ORDER: list[str] = [
    # Tier 1 — core, one new finger each
    "e",  # L-middle  (top, DE #1)
    "n",  # R-index   (home, DE #2)
    "i",  # R-middle  (top, DE #3)
    "s",  # L-ring    (home, DE #4)
    "r",  # L-index   (top, DE #5)
    # Tier 2 — fill remaining fingers
    "a",  # L-pinky   (home, DE #6)
    "l",  # R-ring    (home, DE #11 but new finger)
    "t",  # L-index   (top, DE #7)
    "d",  # L-middle  (home, DE #8)
    "h",  # R-index   (home, DE #9)
    # Tier 3 — common extensions
    "u",  # R-index   (top, DE #10)
    "z",  # R-index   (top — easy on QWERTZ!, DE #20 but frequent in DE)
    "o",  # R-ring    (top, DE #15)
    "g",  # L-index   (home, DE #13)
    "c",  # L-middle  (bottom, DE #12)
    # Tier 4 — less common
    "m",  # R-index   (bottom, DE #14)
    "b",  # L-index   (bottom, DE #16)
    "w",  # L-ring    (top, DE #17)
    "f",  # L-index   (home, DE #18)
    "k",  # R-middle  (home, DE #19)
    # Tier 5 — rare
    "p",  # R-pinky   (top, DE #21)
    "v",  # L-index   (bottom, DE #22)
    "j",  # R-index   (home, DE #23)
    "x",  # L-ring    (bottom, DE #24)
    "q",  # L-pinky   (top, DE #25)
    "y",  # L-pinky   (bottom — hardest key on QWERTZ, DE #26)
]

ENGLISH_INTRODUCTION_ORDER: list[str] = [
    # Tier 1 — core, one new finger each
    "e",  # L-middle  (top, EN #1)
    "n",  # R-index   (home, EN #6 but different hand than e)
    "i",  # R-middle  (top, EN #5)
    "s",  # L-ring    (home, EN #7)
    "r",  # L-index   (top, EN #9)
    # Tier 2 — fill remaining fingers
    "a",  # L-pinky   (home, EN #3)
    "l",  # R-ring    (home, EN #11 but new finger)
    "t",  # L-index   (top, EN #2)
    "d",  # L-middle  (home, EN #10)
    "h",  # R-index   (home, EN #8)
    # Tier 3 — common extensions
    "o",  # R-ring    (top, EN #4)
    "u",  # R-index   (top, EN #13)
    "g",  # L-index   (home, EN #17)
    "c",  # L-middle  (bottom, EN #12)
    "m",  # R-index   (bottom, EN #14)
    # Tier 4 — less common
    "w",  # L-ring    (top, EN #15)
    "f",  # L-index   (home, EN #16)
    "b",  # L-index   (bottom, EN #20)
    "k",  # R-middle  (home, EN #22)
    "p",  # R-pinky   (top, EN #19)
    # Tier 5 — rare
    "z",  # R-index   (top — easy on QWERTZ, EN #26)
    "v",  # L-index   (bottom, EN #21)
    "j",  # R-index   (home, EN #23)
    "x",  # L-ring    (bottom, EN #24)
    "q",  # L-pinky   (top, EN #25)
    "y",  # L-pinky   (bottom — hardest key on QWERTZ, EN #18 but hard key)
]


def get_introduction_order(language: str) -> list[str]:
    """Get the curated letter introduction order for a language.

    The order balances QWERTZ ergonomics (home-row first, finger spread,
    pinky deferred) with corpus frequency.  The user can override it via
    ``LetterManager.set_introduction_order()``.

    Args:
        language: 'de' or 'en'.

    Returns:
        List of 26 lowercase letters in introduction order.
    """
    if language == "de":
        return list(GERMAN_INTRODUCTION_ORDER)
    elif language == "en":
        return list(ENGLISH_INTRODUCTION_ORDER)
    else:
        raise ValueError(f"Unsupported language: {language}. Use 'de' or 'en'.")
