"""Tests for text generation."""

from pathlib import Path

from typing_trainer.config import Config
from typing_trainer.core.text_generator import TextGenerator
from typing_trainer.models.letter_state import LetterState, LetterStats, PracticeType


def make_active_letters(*letters: str) -> dict[str, LetterStats]:
    """Create an active letter set with default stats."""
    return {
        letter: LetterStats(letter=letter, state=LetterState.CONSOLIDATING)
        for letter in letters
    }


class TestRandomStrings:
    def test_generates_correct_length(self):
        config = Config()
        gen = TextGenerator(config)
        active = make_active_letters("e", "n", "i", "s", "r")

        text = gen.generate(PracticeType.RANDOM_STRINGS, 100, active)
        assert len(text) == 100

    def test_only_uses_active_letters_and_spaces(self):
        config = Config()
        gen = TextGenerator(config)
        letters = {"e", "n", "i"}
        active = make_active_letters(*letters)

        text = gen.generate(PracticeType.RANDOM_STRINGS, 200, active)
        for char in text:
            assert char in letters or char == " "

    def test_contains_spaces(self):
        config = Config()
        gen = TextGenerator(config)
        active = make_active_letters("a", "b", "c", "d")

        text = gen.generate(PracticeType.RANDOM_STRINGS, 100, active)
        assert " " in text

    def test_spaces_at_reasonable_intervals(self):
        """Spaces should appear every 3-6 characters."""
        config = Config()
        gen = TextGenerator(config)
        active = make_active_letters("a", "b", "c", "d", "e")

        text = gen.generate(PracticeType.RANDOM_STRINGS, 500, active)
        segments = text.split(" ")
        # Most segments should be 3-6 chars (allowing some variance)
        lengths = [len(s) for s in segments if s]  # filter empty
        assert all(1 <= length <= 7 for length in lengths)

    def test_empty_active_set_returns_empty(self):
        config = Config()
        gen = TextGenerator(config)
        text = gen.generate(PracticeType.RANDOM_STRINGS, 100, {})
        assert text == ""

    def test_weighting_favors_introducing_letters(self):
        """Letters in 'introducing' state should appear more often."""
        config = Config()
        gen = TextGenerator(config)

        active = {
            "e": LetterStats(
                letter="e", state=LetterState.STABLE, rolling_error_rate=0.02
            ),
            "x": LetterStats(
                letter="x", state=LetterState.INTRODUCING, rolling_error_rate=0.10
            ),
        }

        # Generate a long text and count frequencies
        text = gen.generate(PracticeType.RANDOM_STRINGS, 2000, active, language="de")
        chars_only = text.replace(" ", "")
        x_count = chars_only.count("x")
        e_count = chars_only.count("e")

        # Need-based weighting (no language frequency):
        # e: stable, 2% error -> weight = 1.0 + 0 + 0 = 1.0
        # x: introducing, 10% error -> weight = 1.0 + 4.0 + 2.5 = 7.5
        # Raw share would be ~88%, but capped at effective cap.
        # With 2 letters the effective cap is max(0.35, 1/2) = 50%,
        # so x gets 50% — still less than the uncapped 88%.
        assert x_count > 0
        total_chars = len(chars_only)
        x_share = x_count / total_chars
        # x should be around 50% (capped), not 88% (uncapped massing)
        assert 0.40 < x_share < 0.60, f"x share {x_share:.2%} outside expected range"

    def test_text_never_ends_with_space(self):
        """Generated text should never end with a space character."""
        config = Config()
        gen = TextGenerator(config)
        active = make_active_letters("e", "n")
        for _ in range(50):
            text = gen.generate(PracticeType.RANDOM_STRINGS, 100, active)
            assert not text.endswith(" "), f"Text ends with space: ...'{text[-5:]}'"

    def test_no_more_than_two_consecutive_identical(self):
        """Random strings should never have 3+ identical characters in a row."""
        config = Config()
        gen = TextGenerator(config)
        # Use a small letter set to maximize collision chance
        active = make_active_letters("e", "n")

        for _ in range(20):
            text = gen.generate(PracticeType.RANDOM_STRINGS, 500, active)
            for i in range(len(text) - 2):
                if text[i] != " ":
                    assert not (
                        text[i] == text[i + 1] == text[i + 2]
                    ), f"Found 3+ consecutive '{text[i]}' at position {i}: ...{text[max(0,i-2):i+5]}..."

    def test_allows_double_letters(self):
        """Double letters (e.g. 'ee') should still be allowed."""
        config = Config()
        gen = TextGenerator(config)
        active = make_active_letters("e", "n")

        # With only 2 letters and 500 chars, doubles are very likely
        texts = [
            gen.generate(PracticeType.RANDOM_STRINGS, 500, active)
            for _ in range(10)
        ]
        all_text = "".join(texts)
        assert "ee" in all_text or "nn" in all_text


class TestRandomWords:
    def test_generates_words_from_corpus(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("der\ndie\nund\ndas\n")

        config = Config(corpus_dir=str(tmp_path))
        gen = TextGenerator(config)
        active = make_active_letters("d", "e", "r", "i", "u", "n", "a", "s")

        text = gen.generate(
            PracticeType.RANDOM_WORDS, 50, active, language="de"
        )
        assert len(text) > 0
        words = text.split()
        for word in words:
            assert word in {"der", "die", "und", "das"}

    def test_filters_words_by_active_set(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("ab\ncd\nef\n")

        config = Config(corpus_dir=str(tmp_path))
        gen = TextGenerator(config)
        active = make_active_letters("a", "b")

        text = gen.generate(
            PracticeType.RANDOM_WORDS, 50, active, language="de"
        )
        words = text.split()
        for word in words:
            assert word == "ab"  # only word with letters a, b

    def test_falls_back_to_random_strings_when_no_words_match(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("xyz\n")

        config = Config(corpus_dir=str(tmp_path))
        gen = TextGenerator(config)
        active = make_active_letters("a", "b")

        text = gen.generate(
            PracticeType.RANDOM_WORDS, 50, active, language="de"
        )
        # Should fall back to random strings with a/b
        assert len(text) > 0
        for char in text:
            assert char in {"a", "b", " "}

    def test_missing_corpus_falls_back(self):
        config = Config(corpus_dir="/nonexistent/path")
        gen = TextGenerator(config)
        active = make_active_letters("a", "b")

        text = gen.generate(
            PracticeType.RANDOM_WORDS, 50, active, language="de"
        )
        assert len(text) > 0

    def test_word_weighting_favors_words_with_struggling_letter(self, tmp_path: Path):
        """Words containing a high-need letter should appear more often."""
        corpus_file = tmp_path / "corpus_de.txt"
        # 'se' contains struggling 's', 'en' does not
        corpus_file.write_text("se\nen\n")

        config = Config(corpus_dir=str(tmp_path), max_letter_share=1.0)
        gen = TextGenerator(config)
        active = {
            "s": LetterStats(
                letter="s", state=LetterState.DEGRADED, rolling_error_rate=0.15
            ),
            "e": LetterStats(
                letter="e", state=LetterState.STABLE, rolling_error_rate=0.02
            ),
            "n": LetterStats(
                letter="n", state=LetterState.STABLE, rolling_error_rate=0.02
            ),
        }

        words_seen: dict[str, int] = {"se": 0, "en": 0}
        for _ in range(200):
            text = gen.generate(
                PracticeType.RANDOM_WORDS, 5, active, language="de"
            )
            for word in text.split():
                if word in words_seen:
                    words_seen[word] += 1

        # 'se' should appear much more often because max-based weighting
        # gives it the full weight of the struggling 's'
        assert words_seen["se"] > words_seen["en"] * 1.5


class TestKeyboardLayout:
    def test_german_introduction_order(self):
        from typing_trainer.models.keyboard_layout import get_introduction_order

        order = get_introduction_order("de")
        assert order[0] == "e"  # most frequent in German
        assert order[1] == "n"
        assert len(order) == 26

    def test_english_introduction_order(self):
        from typing_trainer.models.keyboard_layout import get_introduction_order

        order = get_introduction_order("en")
        assert order[0] == "e"
        assert order[1] == "n"
        assert len(order) == 26

    def test_frequencies_sum_approximately_to_one(self):
        from typing_trainer.models.keyboard_layout import get_letter_frequencies

        de_freqs = get_letter_frequencies("de")
        en_freqs = get_letter_frequencies("en")

        assert 0.95 < sum(de_freqs.values()) < 1.05
        assert 0.95 < sum(en_freqs.values()) < 1.05


class TestTrainingWeight:
    """Tests for the need-based training_weight() on LetterStats."""

    def test_state_bonuses(self):
        """Each state has a distinct bonus: introducing > degraded > consolidating > stable."""
        s = LetterStats(letter="a", state=LetterState.INTRODUCING)
        assert s._state_bonus() == 3.0

        s.state = LetterState.DEGRADED
        assert s._state_bonus() == 2.0

        s.state = LetterState.CONSOLIDATING
        assert s._state_bonus() == 1.0

        s.state = LetterState.STABLE
        s.sessions_in_current_state = 20  # fully settled
        assert s._state_bonus() == 0.0

    def test_recently_stable_bonus(self):
        """Recently-stable letters get a decaying bonus."""
        s = LetterStats(letter="a", state=LetterState.STABLE, sessions_in_current_state=0)
        assert s._state_bonus() == 1.0  # full bonus at 0 sessions

        s.sessions_in_current_state = 5
        assert abs(s._state_bonus() - 0.5) < 1e-9  # half bonus at 5/10

        s.sessions_in_current_state = 9
        assert abs(s._state_bonus() - 0.1) < 1e-9  # 1/10 at 9 sessions

        s.sessions_in_current_state = 10
        assert s._state_bonus() == 0.0  # fully settled

        s.sessions_in_current_state = 15
        assert s._state_bonus() == 0.0  # still 0

    def test_accuracy_gap_bonus(self):
        """Bonus kicks in when rolling_error_rate exceeds 5%."""
        s = LetterStats(letter="a", rolling_error_rate=0.05)
        assert s._accuracy_gap_bonus() == 0.0  # exactly at baseline

        s.rolling_error_rate = 0.10
        assert s._accuracy_gap_bonus() == 2.5  # (0.10 - 0.05) * 50

        s.rolling_error_rate = 0.20
        assert abs(s._accuracy_gap_bonus() - 7.5) < 1e-9  # (0.20 - 0.05) * 50

        s.rolling_error_rate = 0.02
        assert s._accuracy_gap_bonus() == 0.0  # below threshold, no bonus

    def test_training_weight_stable_accurate(self):
        """A fully-settled stable letter at 97% accuracy gets minimum weight."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=999,
        )
        assert s.training_weight() == 1.0  # 1.0 + 0 + 0 + 0

    def test_training_weight_introducing_fresh(self):
        """A freshly introduced letter (no errors yet) gets state bonus only."""
        s = LetterStats(
            letter="a", state=LetterState.INTRODUCING, rolling_error_rate=0.0,
            rolling_keystroke_count=999,
        )
        assert s.training_weight() == 4.0  # 1.0 + 3.0 + 0 + 0

    def test_training_weight_introducing_struggling(self):
        """An introducing letter at 85% accuracy gets both bonuses."""
        s = LetterStats(
            letter="a", state=LetterState.INTRODUCING, rolling_error_rate=0.15,
            rolling_keystroke_count=999,
        )
        assert s.training_weight() == 9.0  # 1.0 + 3.0 + 5.0 + 0

    def test_training_weight_degraded_high_errors(self):
        """A degraded letter at 80% accuracy gets heavy weight."""
        s = LetterStats(
            letter="a", state=LetterState.DEGRADED, rolling_error_rate=0.20,
            rolling_keystroke_count=999,
        )
        assert s.training_weight() == 10.5  # 1.0 + 2.0 + 7.5 + 0

    def test_training_weight_no_cap(self):
        """Weights are uncapped — extreme error rates produce large weights."""
        s = LetterStats(
            letter="a", state=LetterState.INTRODUCING, rolling_error_rate=0.30,
            rolling_keystroke_count=999,
        )
        # 1.0 + 3.0 + (0.30-0.05)*50 = 1.0 + 3.0 + 12.5 = 16.5
        assert s.training_weight() == 16.5

    def test_training_weight_recently_stable(self):
        """A recently-stable letter gets consolidation bonus."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=0,
            rolling_keystroke_count=999,
        )
        assert s.training_weight() == 2.0  # 1.0 + 1.0 + 0 + 0

        s.sessions_in_current_state = 5
        assert abs(s.training_weight() - 1.5) < 1e-9  # 1.0 + 0.5 + 0 + 0

    def test_training_weight_volume_deficit_full(self):
        """A letter with 0 keystrokes gets the full volume deficit bonus."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=0,
        )
        assert s.training_weight() == 2.0  # 1.0 + 0 + 0 + 1.0

    def test_training_weight_volume_deficit_below_fade_start(self):
        """Volume deficit bonus is full until 85% of window (170 for window=200)."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=100,
        )
        assert s.training_weight() == 2.0  # 1.0 + 0 + 0 + 1.0

        s.rolling_keystroke_count = 170
        assert s.training_weight() == 2.0  # still full bonus at fade_start

    def test_training_weight_volume_deficit_at_window(self):
        """At exactly the window size (200), bonus is 0.5."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=200,
        )
        assert abs(s.training_weight() - 1.5) < 1e-9  # 1.0 + 0 + 0 + 0.5

    def test_training_weight_volume_deficit_above_fade_end(self):
        """At and above fade_end (230 for window=200), bonus is 0."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=230,
        )
        assert s.training_weight() == 1.0  # 1.0 + 0 + 0 + 0

        s.rolling_keystroke_count = 300
        assert s.training_weight() == 1.0

    def test_training_weight_volume_deficit_midpoint(self):
        """At 185 keystrokes (midway through fade), bonus is ~0.75."""
        import math
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=185,
        )
        # t = (185 - 170) / 60 = 0.25, cos(0.25*pi) ≈ 0.707
        expected_bonus = 0.5 * (1.0 + math.cos(math.pi * 0.25))
        assert abs(s.training_weight() - (1.0 + expected_bonus)) < 1e-6

    def test_training_weight_volume_deficit_custom_weight(self):
        """Volume deficit bonus scales with the weight parameter."""
        s = LetterStats(
            letter="a", state=LetterState.STABLE,
            rolling_error_rate=0.03, sessions_in_current_state=20,
            rolling_keystroke_count=0,
        )
        assert s.training_weight(volume_deficit=2.0) == 3.0  # 1.0 + 0 + 0 + 2.0

    def test_training_weight_volume_deficit_stacks_with_state(self):
        """Volume deficit stacks with state and accuracy gap bonuses."""
        s = LetterStats(
            letter="a", state=LetterState.INTRODUCING, rolling_error_rate=0.15,
            rolling_keystroke_count=0,
        )
        # 1.0 + 3.0 (introducing) + 5.0 (gap) + 1.0 (volume) = 10.0
        assert s.training_weight() == 10.0

    def test_scenario_20_stable_plus_1_introducing(self):
        """At 20 settled stable + 1 introducing, the new letter gets ~20% of raw weight."""
        stable = [
            LetterStats(
                letter=chr(ord("a") + i), state=LetterState.STABLE,
                rolling_error_rate=0.03, sessions_in_current_state=20,
                rolling_keystroke_count=999,
            )
            for i in range(20)
        ]
        introducing = LetterStats(
            letter="z", state=LetterState.INTRODUCING, rolling_error_rate=0.0,
            rolling_keystroke_count=0,
        )

        total_weight = sum(s.training_weight() for s in stable) + introducing.training_weight()
        new_share = introducing.training_weight() / total_weight
        # 5.0 / (20*1.0 + 5.0) = 5/25 = 0.20
        assert abs(new_share - 5.0 / 25.0) < 0.01


class TestShareCap:
    """Tests for the max_letter_share cap applied in _compute_weights()."""

    def test_no_cap_when_all_equal(self):
        """Equal weights should not be capped."""
        config = Config(max_letter_share=0.35)
        gen = TextGenerator(config)
        active = {
            letter: LetterStats(
                letter=letter, state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            )
            for letter in "enirs"
        }
        letters, weights = gen._compute_weights(active)
        total = sum(weights)
        shares = [w / total for w in weights]
        # 5 equal letters -> 20% each, all below 35%
        for share in shares:
            assert abs(share - 0.20) < 0.01

    def test_cap_limits_introducing_letter(self):
        """An introducing letter among stable ones must not exceed the cap."""
        config = Config(max_letter_share=0.35)
        gen = TextGenerator(config)
        active = {
            letter: LetterStats(
                letter=letter, state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            )
            for letter in "enirs"
        }
        active["z"] = LetterStats(
            letter="z", state=LetterState.INTRODUCING, rolling_error_rate=0.0,
            rolling_keystroke_count=999,
        )
        letters, weights = gen._compute_weights(active)
        total = sum(weights)
        shares = {lt: w / total for lt, w in zip(letters, weights)}

        # Raw weight of 'z' is 4.0, others are 1.0 each (settled)
        # Raw share would be 4.0/9.0 ≈ 44.4%, capped to 35%
        assert shares["z"] <= 0.35 + 1e-9
        # All other letters should get a proportional share of the remaining
        for lt in "enirs":
            assert shares[lt] > 0.10  # each gets at least 13%

    def test_cap_with_extreme_weight(self):
        """A struggling introducing letter with huge raw weight is still capped."""
        config = Config(max_letter_share=0.35)
        gen = TextGenerator(config)
        active = {
            letter: LetterStats(
                letter=letter, state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            )
            for letter in "en"
        }
        active["z"] = LetterStats(
            letter="z", state=LetterState.INTRODUCING, rolling_error_rate=0.30,
            rolling_keystroke_count=999,
        )
        letters, weights = gen._compute_weights(active)
        total = sum(weights)
        shares = {lt: w / total for lt, w in zip(letters, weights)}

        # Raw weight of 'z' is 16.5, others are 1.0 each (settled)
        # Raw share would be 16.5/18.5 ≈ 89%, capped to 35%
        assert shares["z"] <= 0.35 + 1e-9

    def test_no_cap_when_naturally_below(self):
        """Letters naturally below the cap should keep their raw proportions."""
        config = Config(max_letter_share=0.35)
        gen = TextGenerator(config)
        active = {
            letter: LetterStats(
                letter=letter, state=LetterState.CONSOLIDATING,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            )
            for letter in "enirs"
        }
        letters, weights = gen._compute_weights(active)
        # All CONSOLIDATING with same error rate -> equal weights -> 20% each
        total = sum(weights)
        shares = [w / total for w in weights]
        for share in shares:
            assert abs(share - 0.20) < 0.01

    def test_cap_preserves_total_weight(self):
        """Capping should preserve the total weight sum."""
        config = Config(max_letter_share=0.35)
        gen = TextGenerator(config)
        active = {
            letter: LetterStats(
                letter=letter, state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            )
            for letter in "enirs"
        }
        active["z"] = LetterStats(
            letter="z", state=LetterState.INTRODUCING, rolling_error_rate=0.15,
            rolling_keystroke_count=999,
        )
        letters, weights = gen._compute_weights(active)

        # Total should be preserved
        error_threshold = 1.0 - config.advancement_accuracy
        raw_total = sum(
            s.training_weight(
                error_threshold,
                volume_window=config.advancement_accuracy_window,
                volume_deficit=config.weight_volume_deficit,
            )
            for s in active.values()
        )
        assert abs(sum(weights) - raw_total) < 1e-9

    def test_cap_disabled_at_1(self):
        """max_letter_share=1.0 should effectively disable capping."""
        config = Config(max_letter_share=1.0)
        gen = TextGenerator(config)
        active = {
            "e": LetterStats(
                letter="e", state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            ),
            "z": LetterStats(
                letter="z", state=LetterState.INTRODUCING,
                rolling_error_rate=0.0, rolling_keystroke_count=999,
            ),
        }
        letters, weights = gen._compute_weights(active)
        total = sum(weights)
        shares = {lt: w / total for lt, w in zip(letters, weights)}

        # Raw share of 'z' = 4.0/5.0 = 80%, should be uncapped
        assert shares["z"] > 0.60

    def test_two_letters_both_above_cap(self):
        """When two letters both exceed the cap, both should be clamped."""
        config = Config(max_letter_share=0.25)
        gen = TextGenerator(config)
        # 4 letters so effective cap = max(0.25, 1/4) = 0.25
        active = {
            "e": LetterStats(
                letter="e", state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            ),
            "n": LetterStats(
                letter="n", state=LetterState.STABLE,
                rolling_error_rate=0.03, rolling_keystroke_count=999,
            ),
            "x": LetterStats(
                letter="x", state=LetterState.INTRODUCING,
                rolling_error_rate=0.0, rolling_keystroke_count=999,
            ),
            "y": LetterStats(
                letter="y", state=LetterState.DEGRADED,
                rolling_error_rate=0.20, rolling_keystroke_count=999,
            ),
        }
        letters, weights = gen._compute_weights(active)
        total = sum(weights)
        shares = {lt: w / total for lt, w in zip(letters, weights)}

        # y (DEGRADED + high error) has highest raw weight, should be capped
        assert shares["y"] <= 0.25 + 1e-9


class TestBigramWords:
    """Tests for _generate_bigram_words (BIGRAM_WORDS practice type)."""

    def test_generates_text_with_target_bigrams(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("den\nein\nist\nner\nsen\nres\n")

        config = Config(corpus_dir=str(tmp_path), bigram_target_share=0.40)
        gen = TextGenerator(config)
        gen.set_target_bigrams([("e", "n")])
        active = make_active_letters("d", "e", "n", "i", "s", "t", "r")

        text = gen.generate(PracticeType.BIGRAM_WORDS, 100, active, language="de")
        assert len(text) > 0
        words = text.split()
        # At least some words should contain the target bigram "en"
        bigram_count = sum(1 for w in words if "en" in w)
        assert bigram_count > 0

    def test_falls_back_to_random_words_without_targets(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("den\nein\nist\n")

        config = Config(corpus_dir=str(tmp_path))
        gen = TextGenerator(config)
        gen.set_target_bigrams([])  # no targets
        active = make_active_letters("d", "e", "n", "i", "s", "t")

        text = gen.generate(PracticeType.BIGRAM_WORDS, 50, active, language="de")
        assert len(text) > 0

    def test_max_targets_enforced(self):
        config = Config(bigram_max_targets=3)
        gen = TextGenerator(config)
        gen.set_target_bigrams([
            ("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"), ("i", "j"),
        ])
        assert len(gen._target_bigrams) == 3

    def test_word_contains_bigram_detection(self):
        assert TextGenerator._word_contains_bigram("den", [("e", "n")]) is True
        assert TextGenerator._word_contains_bigram("den", [("d", "e")]) is True
        assert TextGenerator._word_contains_bigram("den", [("n", "d")]) is False
        assert TextGenerator._word_contains_bigram("den", [("e", "d")]) is False
        assert TextGenerator._word_contains_bigram("essen", [("s", "s")]) is True

    def test_bigram_words_interleaved_with_normal(self, tmp_path: Path):
        """~40% bigram words, ~60% normal words (contextual interference)."""
        corpus_file = tmp_path / "corpus_de.txt"
        # Words with "en": den, ren, sen
        # Words without "en": ist, dir, das
        corpus_file.write_text("den\nren\nsen\nist\ndir\ndas\n")

        config = Config(corpus_dir=str(tmp_path), bigram_target_share=0.40)
        gen = TextGenerator(config)
        gen.set_target_bigrams([("e", "n")])
        active = make_active_letters("d", "e", "n", "r", "s", "i", "t", "a")

        # Generate many words and check distribution
        bigram_count = 0
        normal_count = 0
        for _ in range(100):
            text = gen.generate(PracticeType.BIGRAM_WORDS, 30, active, language="de")
            for word in text.split():
                if "en" in word:
                    bigram_count += 1
                else:
                    normal_count += 1

        total = bigram_count + normal_count
        bigram_share = bigram_count / total
        # Should be roughly 40% but with random variance
        assert 0.20 < bigram_share < 0.60, f"Bigram share {bigram_share:.2%}"

    def test_filters_words_by_active_letters(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("den\nxyz\nen\n")

        config = Config(corpus_dir=str(tmp_path))
        gen = TextGenerator(config)
        gen.set_target_bigrams([("e", "n")])
        active = make_active_letters("d", "e", "n")

        text = gen.generate(PracticeType.BIGRAM_WORDS, 50, active, language="de")
        words = text.split()
        # Only words with active letters should appear
        for word in words:
            for c in word:
                assert c in {"d", "e", "n"}, f"Unexpected char '{c}' in word '{word}'"

    def test_text_never_ends_with_space(self, tmp_path: Path):
        corpus_file = tmp_path / "corpus_de.txt"
        corpus_file.write_text("den\nen\nne\n")

        config = Config(corpus_dir=str(tmp_path))
        gen = TextGenerator(config)
        gen.set_target_bigrams([("e", "n")])
        active = make_active_letters("d", "e", "n")

        for _ in range(20):
            text = gen.generate(PracticeType.BIGRAM_WORDS, 50, active, language="de")
            assert not text.endswith(" "), f"Text ends with space: ...'{text[-5:]}'"
