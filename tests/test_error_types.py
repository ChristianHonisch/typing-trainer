"""Tests for keyboard loading and motor-learning error classification."""

from typing_trainer.models.error_types import classify_error
from typing_trainer.models.keyboard_layout import load_keyboard


QWERTZ = load_keyboard("qwertz")


class TestKeyboardLayout:
    def test_rows_cover_all_letters(self):
        row_letters = {ch for row in QWERTZ.rows for ch in row}
        assert row_letters == set("abcdefghijklmnopqrstuvwxyz")

    def test_columns_cover_all_letters(self):
        col_letters = {ch for col in QWERTZ.columns for ch in col}
        assert col_letters == set("abcdefghijklmnopqrstuvwxyz")

    def test_adjacency_is_symmetric(self):
        for key, neighbors in QWERTZ.adjacency.items():
            for neighbor in neighbors:
                assert key in QWERTZ.adjacency[neighbor]

    def test_known_mirror_pairs(self):
        assert QWERTZ.mirror_pairs["t"] == "z"
        assert QWERTZ.mirror_pairs["g"] == "h"
        assert QWERTZ.mirror_pairs["b"] == "n"
        assert QWERTZ.mirror_pairs["x"] is None


class TestClassifyError:
    def test_mirror_pairs_have_highest_priority(self):
        assert classify_error("t", "z", QWERTZ) == "mirror"
        assert classify_error("g", "h", QWERTZ) == "mirror"
        assert classify_error("b", "n", QWERTZ) == "mirror"
        assert classify_error("d", "k", QWERTZ) == "mirror"

    def test_same_column_wrong_row(self):
        assert classify_error("q", "a", QWERTZ) == "same_column"
        assert classify_error("e", "c", QWERTZ) == "same_column"
        assert classify_error("z", "n", QWERTZ) == "same_column"

    def test_same_finger_wrong_column(self):
        assert classify_error("r", "t", QWERTZ) == "same_finger"
        assert classify_error("f", "g", QWERTZ) == "same_finger"
        assert classify_error("z", "u", QWERTZ) == "same_finger"
        assert classify_error("h", "j", QWERTZ) == "same_finger"

    def test_same_row_wrong_finger(self):
        assert classify_error("q", "w", QWERTZ) == "same_row"
        assert classify_error("e", "r", QWERTZ) == "same_row"
        assert classify_error("a", "s", QWERTZ) == "same_row"
        assert classify_error("x", "c", QWERTZ) == "same_row"

    def test_other(self):
        assert classify_error("e", "n", QWERTZ) == "other"
        assert classify_error(" ", "e", QWERTZ) == "other"
        assert classify_error("e", "e", QWERTZ) == "other"

    def test_priority_mirror_over_same_finger(self):
        # t/z are same finger (index) and mirror; mirror wins.
        assert classify_error("t", "z", QWERTZ) == "mirror"

    def test_priority_same_column_over_same_finger(self):
        # q/a are same column and same finger; same_column wins.
        assert classify_error("q", "a", QWERTZ) == "same_column"

    def test_priority_same_finger_over_same_row(self):
        # r/t share both same row and same finger; same_finger wins.
        assert classify_error("r", "t", QWERTZ) == "same_finger"
