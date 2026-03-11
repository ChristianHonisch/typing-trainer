"""Configuration dataclass with all tunable parameters."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Config:
    """All configurable parameters for the typing trainer.

    Every threshold and tuning parameter from the spec is here.
    Values can be loaded from / saved to a JSON file.
    """

    # --- Advancement criteria ---
    advancement_accuracy: float = 0.95
    """Per-letter accuracy required to unlock a new letter."""

    advancement_min_keystrokes: int = 500
    """Minimum total cognitive keystrokes with current letter set before advancement."""

    advancement_accuracy_window: int = 200
    """Rolling window size (keystrokes per letter) for computing per-letter accuracy."""

    # --- Fail thresholds ---
    fail_threshold_min_errors: int = 5
    """Minimum cognitive errors before fail threshold can abort a run.

    The first N-1 errors are always tolerated regardless of accuracy.
    On the Nth error, if accuracy is below the fail threshold, the run
    is aborted.  This prevents accidental double-key presses or early
    fumbles from immediately ending a run.
    """

    fail_threshold_relearning: float = 0.90
    """Accuracy floor during a relearning run (standard)."""

    fail_threshold_speed: float = 0.95
    """Accuracy floor during a speed run."""

    fail_threshold_introducing_s1: float = 0.70
    """Fail threshold for first session with a new letter."""

    fail_threshold_introducing_s2: float = 0.80
    """Fail threshold for second session with a new letter."""

    # --- Run defaults ---
    run_length_default_relearning: int = 60
    """Default number of target keystrokes per run in relearning mode.

    Random strings are cognitively intense — error rate analysis shows
    a sweet spot at positions 20-50, with fatigue setting in around
    position 50.  60 captures warmup + productive zone while stopping
    before significant fatigue.
    """

    run_length_default_speed: int = 100
    """Default number of target keystrokes per run in speed mode.

    Words and sentences provide linguistic context that reduces cognitive
    load, allowing longer focused runs.
    """

    run_length_minimum: int = 50
    """Minimum number of target keystrokes per run."""

    # --- Speed training ---
    speed_increment: int = 2
    """WPM increase on successful speed run."""

    speed_decrement: int = 4
    """WPM decrease on failed speed run.

    With +2/-4 the equilibrium failure rate is 2/(2+4) = 33%, giving a
    67% success rate at the user's true speed ceiling.  Motor-learning
    literature recommends 60-80% success for optimal skill acquisition.
    """

    # --- Warmup ---
    warmup_keystrokes: int = 3
    """Number of keystrokes at the start of a run that are excluded from
    accuracy scoring.  Position analysis shows elevated error rates at
    run start (~3.5% at positions 0-4 vs ~1.7% at positions 20-49).
    Warmup keystrokes are still logged and saved to the database but do
    not count toward run accuracy, per-letter stats, or the fail
    threshold.
    """

    # --- Text generation ---
    max_letter_share: float = 0.35
    """Maximum share of characters any single letter can occupy in generated
    text.  Prevents massed repetition of introducing/degraded letters.

    Motor-learning research shows interleaved practice (mixing items) builds
    more durable motor patterns than massed practice (drilling one item).
    A 35% cap ensures at least ~65% of characters come from other letters,
    maintaining contextual interference even for the neediest letter.
    """

    # --- Training weight bonuses ---
    weight_introducing: float = 3.0
    """State bonus for letters in INTRODUCING state."""
    weight_degraded: float = 2.0
    """State bonus for letters in DEGRADED state."""
    weight_consolidating: float = 1.0
    """State bonus for letters in CONSOLIDATING state."""
    weight_recently_stable: float = 1.0
    """Maximum consolidation bonus for recently-stable letters.
    Linearly decays to 0 over ``recently_stable_sessions`` sessions."""
    recently_stable_sessions: int = 10
    """Number of sessions in STABLE state before the consolidation bonus
    fully decays.  A letter stable for fewer sessions gets proportionally
    more practice to solidify the motor pattern."""

    weight_volume_deficit: float = 1.0
    """Bonus for letters whose rolling keystroke count has not yet filled
    the ``advancement_accuracy_window``.  Full bonus until 85% of the
    window, then a cosine fade to 0 at 115% of the window (i.e. the
    bonus is 0.5 at exactly the window size).  This ensures recently-
    introduced letters accumulate enough data to produce reliable
    accuracy readings before the bonus disappears."""

    # --- Error classification ---
    motor_overflow_window_ms: int = 80
    """Time window (ms) for detecting motor overflow (unintentional double-press)."""

    burst_max_interval_ms: int = 500
    """Max inter-press interval (ms) for consecutive same-key presses to be
    considered part of a burst (key held/stuck). Bursts of 3+ same-key presses
    where >50% are errors have subsequent errors reclassified as BURST_REPEAT."""

    # --- Session management ---
    session_timeout_minutes: int = 30
    """Inactivity timeout (minutes) that defines a session boundary."""

    rest_suggestion_seconds: int = 30
    """Suggested rest between runs (seconds)."""

    # --- Degradation hysteresis ---
    degraded_recovery_margin: float = 0.8
    """Multiplier for the DEGRADED -> STABLE recovery threshold.

    To exit DEGRADED, the rolling error rate must be at or below
    ``(1 - advancement_accuracy) * degraded_recovery_margin``.  At the
    default values (0.95 accuracy, 0.8 margin) the recovery threshold
    is 4% instead of the 5% entry threshold, creating a 1% hysteresis
    gap that prevents rapid state oscillation.
    """

    # --- Bigram transition training ---
    bigram_min_count: int = 10
    """Minimum number of occurrences of a bigram before it appears in
    the analysis view.  Ensures sufficient data for reliable error rate
    and transition time estimates."""

    bigram_target_share: float = 0.40
    """Target share of characters in bigram_words text that come from
    words containing the target bigrams (~40%).  The remaining ~60%
    are normal words (contextual interference)."""

    bigram_max_targets: int = 3
    """Maximum number of bigrams the user can select for a single
    transition training run.  Motor learning: 1-3 targets provides
    contextual interference without overwhelming working memory."""

    run_length_default_transition: int = 80
    """Default number of target keystrokes per run in transition mode.

    Intermediate between relearning (60) and speed (100): long enough
    to get meaningful bigram repetitions, short enough to maintain focus
    on the specific transitions being trained.
    """

    fail_threshold_transition: float = 0.95
    """Accuracy floor during a transition training run.

    Same as speed mode — transition training targets automated bigrams,
    requiring the same maturity level as speed work.
    """

    bigram_trimmed_mean_fraction: float = 0.10
    """Fraction of extreme values to trim from each end when computing
    trimmed mean transition times.  10% = remove top/bottom 10%,
    keeping the middle 80%.  Resists outliers from pauses, distractions,
    or OS interrupts."""

    # --- Spaced repetition ---
    half_life_consolidating_hours: float = 24.0
    """Stability decay half-life for consolidating letters (hours)."""

    half_life_stable_hours: float = 72.0
    """Stability decay half-life for stable letters (hours)."""

    stability_revert_threshold: float = 0.5
    """Stability score below which a letter reverts to consolidating."""

    # --- Paths ---
    corpus_dir: str = "data"
    """Directory containing corpus files."""

    db_path: str = "typing_trainer.db"
    """Path to the SQLite database file."""

    # --- Language ---
    language: str = "de"
    """Active language for corpus and letter frequency ('en' or 'de')."""

    def save(self, path: Path) -> None:
        """Save configuration to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path) -> Config:
        """Load configuration from a JSON file.

        Missing keys use defaults. Unknown keys are ignored.
        Returns defaults if the file is missing or corrupt.
        """
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return cls()
        # Only use keys that are valid fields
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
