"""Text generation for typing exercises.

Three modes:
- random_strings: weighted random characters, spaces every 3-6 chars
- random_words: real words from corpus, filtered by active letter set
- sentences: unfiltered text from corpus (speed mode only)
"""

from __future__ import annotations

import random
from pathlib import Path

from typing_trainer.config import Config
from typing_trainer.models.keyboard_layout import QWERTZ_FINGER_MAP
from typing_trainer.models.letter_state import LetterStats, PracticeType


class TextGenerator:
    """Generates practice text based on the active letter set and weights."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._word_cache: dict[str, list[str]] = {}  # language -> word list
        self._target_bigrams: list[tuple[str, str]] = []
        """Bigrams to target in BIGRAM_WORDS mode.  Set via
        :meth:`set_target_bigrams` before generating bigram text."""

    def generate(
        self,
        practice_type: PracticeType,
        length: int,
        active_letters: dict[str, LetterStats],
        language: str | None = None,
    ) -> str:
        """Generate practice text.

        Args:
            practice_type: Type of text to generate.
            length: Target number of characters (approximate for word modes).
            active_letters: Current active letter set with stats.
            language: Language for corpus. Defaults to config.language.

        Returns:
            Generated text string.
        """
        if language is None:
            language = self.config.language

        match practice_type:
            case PracticeType.RANDOM_STRINGS:
                text = self._generate_random_strings(length, active_letters, language)
            case PracticeType.RANDOM_WORDS:
                text = self._generate_random_words(length, active_letters, language)
            case PracticeType.SENTENCES:
                text = self._generate_sentences(length, language)
            case PracticeType.BIGRAM_WORDS:
                text = self._generate_bigram_words(
                    length, active_letters, language,
                    self._target_bigrams,
                )
            case _:
                text = ""

        return text.rstrip(" ")

    def _generate_random_strings(
        self,
        length: int,
        active_letters: dict[str, LetterStats],
        language: str,
    ) -> str:
        """Generate random character sequences with spaces every 3-6 chars.

        Characters are drawn from the active letter set, weighted by
        need-based training weight (state bonus + accuracy gap bonus).

        Anti-repetition rules (when enough letters are active):

        **Global no-repeat** (>= ``min_letters_no_repeat`` non-space
        letters): the same letter cannot appear twice in a row, even
        across a space boundary (``a a`` is prevented).

        **Per-hand no-repeat** (>= ``min_hand_letters_no_repeat``
        letters on one hand): the last letter typed by each hand cannot
        be repeated by that hand, regardless of letters the other hand
        typed in between.  Spaces (thumb) are ignored for hand tracking.

        When the constraints are not active (too few letters), the
        fallback rule is: doubles allowed, triples blocked.
        """
        if not active_letters:
            return ""

        letters, weights = self._compute_weights(active_letters)
        if not letters:
            return ""

        # ── Hand membership ──
        left_active: set[str] = set()
        right_active: set[str] = set()
        for lt in letters:
            finger = QWERTZ_FINGER_MAP.get(lt, -1)
            if 0 <= finger <= 3:
                left_active.add(lt)
            elif finger >= 6:
                right_active.add(lt)

        enable_global = len(letters) >= self.config.min_letters_no_repeat
        enable_left = len(left_active) >= self.config.min_hand_letters_no_repeat
        enable_right = len(right_active) >= self.config.min_hand_letters_no_repeat

        # ── State tracking ──
        last_nonspace: str | None = None
        last_left: str | None = None
        last_right: str | None = None

        result: list[str] = []
        chars_since_space = 0
        next_space_at = random.randint(3, 6)

        while len(result) < length:
            is_last_char = len(result) == length - 1
            if chars_since_space >= next_space_at and not is_last_char:
                result.append(" ")
                chars_since_space = 0
                next_space_at = random.randint(3, 6)
            else:
                # Build exclusion set
                exclude: set[str] = set()

                if enable_global and last_nonspace is not None:
                    exclude.add(last_nonspace)

                if enable_left and last_left is not None:
                    exclude.add(last_left)

                if enable_right and last_right is not None:
                    exclude.add(last_right)

                if exclude:
                    filtered = [
                        (lt, wt)
                        for lt, wt in zip(letters, weights)
                        if lt not in exclude
                    ]
                    if filtered:
                        f_letters, f_weights = zip(*filtered)
                        char = random.choices(
                            f_letters, weights=f_weights, k=1
                        )[0]
                    else:
                        # All letters excluded (shouldn't happen with
                        # thresholds >= 4, but safety fallback)
                        char = random.choices(
                            letters, weights=weights, k=1
                        )[0]
                else:
                    char = random.choices(letters, weights=weights, k=1)[0]
                    # Fallback: block triples when constraints are off
                    if (
                        len(letters) > 1
                        and len(result) >= 2
                        and result[-1] == char
                        and result[-2] == char
                    ):
                        fb_filtered = [
                            (lt, wt)
                            for lt, wt in zip(letters, weights)
                            if lt != char
                        ]
                        if fb_filtered:
                            fb_letters, fb_weights = zip(*fb_filtered)
                            char = random.choices(
                                fb_letters, weights=fb_weights, k=1
                            )[0]

                # Update trackers
                last_nonspace = char
                finger = QWERTZ_FINGER_MAP.get(char, -1)
                if 0 <= finger <= 3:
                    last_left = char
                elif finger >= 6:
                    last_right = char

                result.append(char)
                chars_since_space += 1

        return "".join(result[:length])

    def _generate_random_words(
        self,
        length: int,
        active_letters: dict[str, LetterStats],
        language: str,
    ) -> str:
        """Generate text from real words, filtered to active letter set.

        Words are selected weighted toward letters that need practice.
        """
        active_set = set(active_letters.keys())
        words = self._get_filtered_words(active_set, language)

        if not words:
            # Fall back to random strings if no words match
            return self._generate_random_strings(length, active_letters, language)

        # Weight words by their letter composition.
        # Use the maximum letter weight in the word so that any word
        # containing a high-need letter gets prioritized.  Mean-based
        # weighting dilutes the signal (a 6-letter word with one
        # struggling letter barely differs from an all-stable word).
        _, letter_weights_map = self._compute_weights_map(active_letters)
        word_weights = []
        for word in words:
            w = max(letter_weights_map.get(c, 1.0) for c in word)
            word_weights.append(w)

        result_parts: list[str] = []
        current_length = 0

        while current_length < length:
            word = random.choices(words, weights=word_weights, k=1)[0]
            if result_parts:
                result_parts.append(" ")
                current_length += 1
            result_parts.append(word)
            current_length += len(word)

        text = "".join(result_parts)
        # Trim to approximate length (don't cut mid-word if possible)
        if len(text) > length + 10:
            # Find last space before the limit
            cut_point = text.rfind(" ", 0, length + 1)
            if cut_point > 0:
                text = text[:cut_point]
            else:
                text = text[:length]
        return text

    def _generate_sentences(self, length: int, language: str) -> str:
        """Generate text from the full corpus (unfiltered).

        Available only in speed mode when all letters are stable.
        For now, falls back to random words from the full alphabet.
        Sentence-level text requires a different corpus format (paragraphs).
        """
        # Placeholder: return words from corpus without filtering
        words = self._load_corpus(language)
        if not words:
            return ""

        result_parts: list[str] = []
        current_length = 0

        while current_length < length:
            word = random.choice(words)
            if result_parts:
                result_parts.append(" ")
                current_length += 1
            result_parts.append(word)
            current_length += len(word)

        text = "".join(result_parts)
        if len(text) > length + 10:
            cut_point = text.rfind(" ", 0, length + 1)
            if cut_point > 0:
                text = text[:cut_point]
            else:
                text = text[:length]
        return text

    def _compute_weights(
        self,
        active_letters: dict[str, LetterStats],
    ) -> tuple[list[str], list[float]]:
        """Compute need-based letter weights for random selection.

        Each letter's weight = 1.0 + state_bonus + accuracy_gap_bonus.
        No language frequency bias — allocation is purely need-based.

        After computing raw weights, a per-letter share cap is applied
        (default 35%) to prevent massed repetition of any single letter.

        Returns:
            Tuple of (letters, weights) for use with random.choices.
        """
        error_threshold = 1.0 - self.config.advancement_accuracy
        letters: list[str] = []
        weights: list[float] = []

        for letter, stats in active_letters.items():
            letters.append(letter)
            weights.append(
                stats.training_weight(
                    error_threshold,
                    introducing=self.config.weight_introducing,
                    degraded=self.config.weight_degraded,
                    consolidating=self.config.weight_consolidating,
                    recently_stable=self.config.weight_recently_stable,
                    recently_stable_sessions=self.config.recently_stable_sessions,
                    volume_window=self.config.advancement_accuracy_window,
                    volume_deficit=self.config.weight_volume_deficit,
                    mastered=self.config.weight_mastered,
                )
            )

        weights = self._apply_share_cap(weights)
        return letters, weights

    def _apply_share_cap(self, weights: list[float]) -> list[float]:
        """Clamp weights so no single letter exceeds max_letter_share.

        Uses a waterfilling approach: sort by weight descending, then
        greedily determine which entries must be capped.  Once the set
        of capped entries is known, uncapped entries share the remaining
        budget proportionally by their original weights.
        """
        cap = self.config.max_letter_share
        n = len(weights)
        if n <= 1 or cap >= 1.0:
            return weights

        # Cap can't be below equal share — otherwise shares can't sum to 1.0
        effective_cap = max(cap, 1.0 / n)

        total = sum(weights)
        if total <= 0:
            return weights

        shares = [w / total for w in weights]

        # Early exit if nothing exceeds cap
        if all(s <= effective_cap for s in shares):
            return weights

        # Sort indices by share descending to greedily find capped set
        order = sorted(range(n), key=lambda i: shares[i], reverse=True)

        capped_count = 0
        for k, idx in enumerate(order):
            # If we cap k entries, the remaining n-k entries share
            # (1 - k*effective_cap) of the total, proportionally by raw weight.
            remaining_budget = 1.0 - k * effective_cap
            # Sum of raw weights for uncapped entries
            uncapped_weight = sum(weights[order[j]] for j in range(k, n))
            if uncapped_weight <= 0:
                break
            # What share would this entry get if uncapped?
            projected = (weights[idx] / uncapped_weight) * remaining_budget
            if projected > effective_cap:
                capped_count = k + 1
            else:
                break

        if capped_count == 0:
            return weights

        # Apply: cap the top entries, redistribute rest proportionally
        capped_set = set(order[:capped_count])
        remaining_budget = 1.0 - capped_count * effective_cap
        uncapped_weight = sum(weights[i] for i in range(n) if i not in capped_set)

        result = list(weights)
        for i in range(n):
            if i in capped_set:
                result[i] = effective_cap * total
            elif uncapped_weight > 0:
                result[i] = (weights[i] / uncapped_weight) * remaining_budget * total
            # else: keep original (shouldn't happen)

        return result

    def _compute_weights_map(
        self,
        active_letters: dict[str, LetterStats],
    ) -> tuple[list[str], dict[str, float]]:
        """Compute weighted letter map.

        Returns:
            Tuple of (letter_list, weight_dict) where weight_dict maps
            letter -> weight.
        """
        letters, weights = self._compute_weights(active_letters)
        weight_map = dict(zip(letters, weights))
        return letters, weight_map

    def _get_filtered_words(
        self, active_set: set[str], language: str
    ) -> list[str]:
        """Get words from corpus filtered to contain only active letters."""
        all_words = self._load_corpus(language)
        return [
            w
            for w in all_words
            if all(c in active_set or c == " " for c in w.lower())
        ]

    def _load_corpus(self, language: str) -> list[str]:
        """Load word list from corpus file. Cached after first load."""
        if language in self._word_cache:
            return self._word_cache[language]

        corpus_dir = Path(self.config.corpus_dir)
        corpus_file = corpus_dir / f"corpus_{language}.txt"

        if not corpus_file.exists():
            self._word_cache[language] = []
            return []

        with open(corpus_file, "r", encoding="utf-8") as f:
            words = [
                line.strip().lower()
                for line in f
                if line.strip() and not line.startswith("#")
            ]

        self._word_cache[language] = words
        return words

    def set_target_bigrams(self, bigrams: list[tuple[str, str]]) -> None:
        """Set target bigrams for BIGRAM_WORDS text generation.

        Args:
            bigrams: List of (prev_char, next_char) pairs to target.
                Maximum ``config.bigram_max_targets`` entries.  Extra
                entries are silently dropped.
        """
        self._target_bigrams = bigrams[: self.config.bigram_max_targets]

    def _generate_bigram_words(
        self,
        length: int,
        active_letters: dict[str, LetterStats],
        language: str,
        target_bigrams: list[tuple[str, str]],
    ) -> str:
        """Generate text from real words targeting specific bigram transitions.

        ~40% of characters come from words containing target bigrams,
        ~60% from normal words (contextual interference).

        Words are filtered to the active letter set.  If fewer than 20
        corpus words contain a target bigram after filtering, filtering
        is relaxed (all corpus words used).

        Args:
            length: Target number of characters.
            active_letters: Current active letter set.
            language: Corpus language.
            target_bigrams: List of (prev_char, next_char) pairs.
        """
        if not target_bigrams:
            # No targets selected — fall back to normal random words
            return self._generate_random_words(length, active_letters, language)

        active_set = set(active_letters.keys())

        # Find words containing each target bigram
        all_words = self._load_corpus(language)
        filtered_words = [
            w for w in all_words
            if all(c in active_set or c == " " for c in w.lower())
        ]

        # Identify bigram words and normal words
        bigram_words: list[str] = []
        normal_words: list[str] = []

        for word in filtered_words:
            if self._word_contains_bigram(word, target_bigrams):
                bigram_words.append(word)
            else:
                normal_words.append(word)

        # Relaxation: if too few bigram words after filtering by active
        # letters, try the unfiltered corpus for bigram words only.
        # Normal words always stay filtered to active letters.
        min_bigram_words = 20
        if len(bigram_words) < min_bigram_words:
            bigram_words_unfiltered = [
                w for w in all_words
                if self._word_contains_bigram(w, target_bigrams)
            ]
            if len(bigram_words_unfiltered) > len(bigram_words):
                bigram_words = bigram_words_unfiltered

        # If still no bigram words, fall back entirely
        if not bigram_words:
            return self._generate_random_words(length, active_letters, language)

        # If no normal words, use only bigram words (unusual but possible)
        if not normal_words:
            normal_words = bigram_words

        target_share = self.config.bigram_target_share

        result_parts: list[str] = []
        current_length = 0

        while current_length < length:
            # Decide whether to pick a bigram word or normal word
            if random.random() < target_share:
                word = random.choice(bigram_words)
            else:
                word = random.choice(normal_words)

            if result_parts:
                result_parts.append(" ")
                current_length += 1
            result_parts.append(word)
            current_length += len(word)

        text = "".join(result_parts)
        if len(text) > length + 10:
            cut_point = text.rfind(" ", 0, length + 1)
            if cut_point > 0:
                text = text[:cut_point]
            else:
                text = text[:length]
        return text

    @staticmethod
    def _word_contains_bigram(
        word: str, bigrams: list[tuple[str, str]]
    ) -> bool:
        """Check if a word contains any of the target bigrams.

        A bigram (a, b) is present if characters a and b appear
        consecutively in the word (or across a space boundary when
        the bigram includes space).
        """
        w = word.lower()
        for a, b in bigrams:
            for i in range(len(w) - 1):
                if w[i] == a and w[i + 1] == b:
                    return True
        return False

    def clear_cache(self) -> None:
        """Clear the word list cache (e.g., after corpus file changes)."""
        self._word_cache.clear()
