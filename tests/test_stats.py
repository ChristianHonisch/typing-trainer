"""Tests for typing_trainer.core.stats."""

from typing_trainer.core.stats import trimmed_mean


class TestTrimmedMean:
    """Tests for trimmed_mean()."""

    def test_empty_returns_zero(self):
        assert trimmed_mean([]) == 0.0

    def test_single_element(self):
        assert trimmed_mean([42]) == 42.0

    def test_two_elements_plain_mean(self):
        # With 2 elements, trim_count = floor(2*0.1) = 0, so plain mean
        assert trimmed_mean([10, 20]) == 15.0

    def test_small_list_no_trim(self):
        # 5 elements, trim_count = floor(5*0.1) = 0 -> plain mean
        assert trimmed_mean([1, 2, 3, 4, 5]) == 3.0

    def test_ten_elements_trims_one_each_side(self):
        # 10 elements, trim_count = floor(10*0.1) = 1
        # Sorted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
        # Trimmed: [2, 3, 4, 5, 6, 7, 8, 9] -> mean = 44/8 = 5.5
        values = [1, 100, 2, 3, 4, 5, 6, 7, 8, 9]
        assert trimmed_mean(values) == 5.5

    def test_twenty_elements_trims_two_each_side(self):
        # 20 elements, trim_count = floor(20*0.1) = 2
        # Sorted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        # Trimmed: [3..18] -> 16 elements, sum = 168, mean = 10.5
        values = list(range(1, 21))
        assert trimmed_mean(values) == 10.5

    def test_all_same_values(self):
        assert trimmed_mean([7, 7, 7, 7, 7]) == 7.0

    def test_outliers_removed(self):
        # Core values around 100, with extreme outliers
        # 20 elements: trim_count = 2
        values = [1, 2] + [100] * 16 + [9998, 9999]
        result = trimmed_mean(values)
        assert result == 100.0

    def test_custom_fraction(self):
        # 10 elements, fraction=0.20 -> trim_count = 2
        # Sorted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        # Trimmed: [3, 4, 5, 6, 7, 8] -> mean = 33/6 = 5.5
        values = list(range(1, 11))
        assert trimmed_mean(values, fraction=0.20) == 5.5

    def test_fraction_too_large_falls_back_to_plain_mean(self):
        # 4 elements, fraction=0.30 -> trim_count = floor(4*0.3) = 1
        # trim_count*2 = 2 < 4, so it still trims
        # Sorted: [1, 2, 3, 4], trimmed: [2, 3] -> mean = 2.5
        assert trimmed_mean([1, 2, 3, 4], fraction=0.30) == 2.5

    def test_fraction_very_large_uses_plain_mean(self):
        # 4 elements, fraction=0.50 -> trim_count = 2
        # trim_count*2 = 4 >= 4, so plain mean fallback
        assert trimmed_mean([1, 2, 3, 4], fraction=0.50) == 2.5

    def test_integer_inputs(self):
        result = trimmed_mean([100, 200, 300])
        assert isinstance(result, float)
        assert result == 200.0

    def test_float_inputs(self):
        result = trimmed_mean([1.5, 2.5, 3.5])
        assert abs(result - 2.5) < 0.001
