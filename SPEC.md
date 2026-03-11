# Typing Trainer -- Technical Specification

## Design Philosophy

This tool is built on motor learning principles, not engagement metrics.
There is no gamification, no badges, no streaks.
The single goal is: correct finger-to-key motor patterns, consolidated to the point of automaticity, then trained for speed.

Speed and accuracy are treated as **separate phases**. Accuracy is never sacrificed for speed. Speed emerges from consolidated accurate patterns.

---

## Definitions

**Run**: A single typing exercise. Has a fixed target text length, mode, and practice type. Produces one set of per-run statistics. Can be failed mid-run if accuracy drops below the fail threshold.

**Session**: One sitting at the keyboard, consisting of one or more runs. Ends when the user closes the tool or is inactive for > 30 minutes. Produces aggregated statistics across its runs. Sessions provide the time-between-practice intervals that consolidation requires.

---

## Core Concepts

### Three Modes

**Phase 1: Relearning**
Goal: establish correct finger-to-key motor mapping with high accuracy.
Advancement criterion: accuracy only.
Speed is measured but never used as a gate.
Backspace is **disabled** -- the user must commit to each keystroke. This prevents a guess-then-correct pattern that undermines motor learning.

**Phase 2: Speed Training**
Goal: increase typing speed while maintaining accuracy.
Only entered after Phase 1 is complete for the full active letter set.
Accuracy threshold is enforced as a hard gate.
Backspace is **enabled** -- accuracy is based on first input per position (corrections are allowed but don't change the score).

**Phase 3: Transition Training**
Goal: improve specific error-prone or slow letter transitions (bigrams).
User-directed: the user identifies problematic bigrams via the analysis tab, selects 1-3 targets, then starts a transition run. Text is generated from real words containing target bigrams interleaved with normal words (contextual interference). Backspace is **enabled** (same as speed mode). Same entry conditions as speed mode (all letters stable + 5 sessions at 95%).

### Error Classification

The tool distinguishes three error types:

- **Cognitive error**: wrong key pressed. This is the primary accuracy metric.
- **Motor overflow**: a key is pressed twice without intention. Detected when the same key fires twice within <80ms **and** the actual character does not match the expected character. Legitimate double-letters (e.g., "ss" in "essen" typed within 80ms) are exempt. Counted separately, excluded from accuracy scoring.
- **Burst repeat**: a key is held or stuck. Detected when 3+ consecutive same-key presses occur within 500ms intervals and >50% are errors. From the 3rd press onward, errors are reclassified as burst repeat and excluded from accuracy, like motor overflow.

All same-key intervals are logged regardless of classification, to enable later per-user calibration of the overflow threshold.

**Swap detection** (diagnostic): Two consecutive cognitive errors where expected/actual characters are transposed (e.g., typed "ne" when target was "en") are flagged as a swap. Both errors still count as cognitive errors -- swaps are a diagnostic metric for identifying sequencing problems.

### Accuracy Definition

```
accuracy = (scored_keystrokes - cognitive_errors) / scored_keystrokes
```

Motor overflow and burst repeat events are excluded from this calculation.
Backspace keypresses are not counted as errors but are logged.
Accuracy is based on **first input per position** -- if backspace is allowed and the user corrects, the original error still counts.

### WPM Definition

```
net_wpm = ((scored_keystrokes - cognitive_errors) / duration_seconds / 5.0) * 60.0
```

WPM is **net**: only correctly typed characters contribute. One "word" = 5 characters (standard convention). Timing starts at the first keystroke, not when the run is initialized.

### Warmup Exclusion

The first N keystrokes of each run (default: 3) are excluded from accuracy scoring, per-letter statistics, and the fail threshold. Position analysis shows elevated error rates at run start (~3.5% at positions 0-4 vs ~1.7% at the productive zone of positions 20-49). Warmup keystrokes are still logged and saved to the database.

---

## Letter Set Management

### Introduction Order

- Letters are introduced **one at a time**.
- The user selects the keyboard layout at setup. For v1, only QWERTZ is supported.
- Introduction order is **curated per language**, balancing QWERTZ ergonomics (home-row first, finger spread, pinky deferred) with corpus frequency. This is not pure frequency order.
  - German: `e n i s r a l t d h u z o g c m b w f k p v j x q y`
  - English: `e n i s r a l t d h o u g c m w f b k p z v j x q y`
- The user can manually override the introduction order.

### Advancement Criterion

A new letter is unlocked when **all** of the following are met simultaneously:

1. **Per-letter accuracy**: Each active letter has >= 95% accuracy in a rolling window of the last 200 keystrokes for that letter
2. **Per-letter data sufficiency**: Each active letter has at least 200 keystrokes in the rolling window
3. **Volume threshold**: At least 500 total cognitive keystrokes have been typed since the last letter was introduced

The rolling window is cumulative across runs and sessions -- it is never reset. Previously stable letters retain their window from before the introduction; only the newly introduced letter needs to accumulate 200 keystrokes.

This system replaced an earlier session-count-based design. The rolling window is more robust: it is not sensitive to session length, doesn't penalize short sessions, and directly measures what matters (sustained accuracy over a meaningful sample).

### Progressive Fail Threshold for New Letters

When a new letter is introduced, the fail threshold during relearning runs is relaxed:
- **First session** with the new letter: fail threshold = 70%
- **Second session**: fail threshold = 80%
- **Third session onward**: standard fail threshold (default 90%)

This gives the user room to learn without being punished for expected early errors.

### Fail Threshold Minimum Error Count

The fail threshold only activates after at least 5 cognitive errors have accumulated in the run. Before that, the run continues regardless of accuracy. This prevents a single accidental double-press or early fumble from immediately ending a run.

### Letter Set State

Each letter in the active set has one of the following states:

- **`introducing`**: Present for < 2 sessions, **or** rolling error rate is above the accuracy threshold (> 5%). A letter stays in this state until it has both >= 2 sessions of practice AND demonstrates adequate accuracy (rolling error rate <= 5%). This prevents promotion of struggling letters.
- **`consolidating`**: Past the introducing phase, not yet stable. Requires accuracy >= 95% across the last 3 sessions to advance to stable.
- **`stable`**: Accuracy >= 95% across last 3 sessions. The target state.
- **`degraded`**: Was stable, but rolling error rate has risen above 5%. Recovers to stable when rolling error rate drops to <= 4% (hysteresis gap prevents oscillation). The 4% recovery threshold = 5% entry threshold * 0.8 (configurable via `degraded_recovery_margin`).

This state is visible to the user at all times via a color-coded letter overview.

### Space Character

Space is always available and is not part of the letter introduction system. It is not tracked in the per-letter state machine (no LetterStats, no rolling window). Space errors count toward overall run accuracy but not toward any letter's advancement criteria.

---

## Session Structure

### Run Configuration

User sets before each run:
- **Run length**: number of target keystrokes (minimum: 50, step size: 10)
  - Default for relearning: 60 (targets the productive zone before fatigue onset)
  - Default for speed: 100 (linguistic context in words/sentences reduces cognitive load)
  - Switching modes resets the spin box to the mode default
- **Mode**: `relearning` or `speed`
- **Practice type**: depends on mode (see below)

### Rest Between Runs

After each run, a 30-second rest countdown is shown. The user can skip it at any time (the Continue button is always enabled). Rest is advisory, not enforced.

### Practice Types

**Random strings** (relearning only):
Sequences of characters drawn from the active letter set, weighted by training need. No real words. Spaces inserted every 3-6 characters. Maximum 2 consecutive identical characters. Purpose: force explicit key lookup without word-pattern shortcuts.

**Random words** (relearning and speed):
Real words from the target language corpus, filtered to contain only letters in the active set. Words are weighted by the **maximum** letter weight among their characters -- any word containing a high-need letter gets prioritized (mean-based weighting was found to dilute the signal).

**Sentences** (speed only):
Unfiltered real text from the corpus. Available only when all target letters are in `stable` state. Currently a placeholder (produces word sequences rather than grammatical sentences).

**Bigram words** (transition only):
Real words from the corpus selected to contain specific target bigram transitions, interleaved with normal words for contextual interference. ~40% of text comes from words containing target bigrams, ~60% from normal words. Words are filtered to the active letter set; if fewer than 20 bigram words match after filtering, filtering is relaxed for bigram words only.

**Mode restrictions**:
- Relearning: `random_strings`, `random_words`
- Speed: `random_words`, `sentences`
- Transition: `bigram_words` (fixed, no choice)

### Case Handling (v1)

All training is **lowercase only**. Capital letters and shift key handling are deferred to a future version.

---

## Weighting Algorithm

The weighting system is **need-based and additive**. There is no corpus frequency component -- allocation is purely based on training need.

### Per-Letter Weight

```
weight(letter) = 1.0 + state_bonus + accuracy_gap_bonus + volume_deficit_bonus
```

**State bonus** (based on current letter state):
| State | Bonus |
|---|---|
| `introducing` | 3.0 |
| `degraded` | 2.0 |
| `consolidating` | 1.0 |
| `stable` (recently) | 0.0–1.0 (decaying) |
| `stable` (settled) | 0.0 |

**Recently-stable consolidation bonus:** Letters that just reached `stable` state get an additional bonus that linearly decays to 0 over `recently_stable_sessions` (default 10) sessions. This ensures recently-stabilized letters continue getting meaningful practice to solidify the motor pattern, rather than immediately dropping to minimum weight.

Formula: `bonus = weight_recently_stable × (1 - sessions_in_current_state / recently_stable_sessions)` for sessions_in_current_state < recently_stable_sessions, else 0.

**Accuracy gap bonus** (based on how far below the accuracy threshold):
```
accuracy_gap_bonus = max(0, (rolling_error_rate - error_threshold) * 50)
```
Where `error_threshold = 1 - advancement_accuracy` (default 0.05). The multiplier 50 means each 1% of error rate above threshold adds 0.5 bonus weight.

Examples at default settings:
| Error rate | Accuracy | Bonus |
|---|---|---|
| 5% | 95% | 0.0 (at threshold) |
| 10% | 90% | 2.5 |
| 15% | 85% | 5.0 |
| 20% | 80% | 7.5 |

**Volume deficit bonus:** Letters whose rolling keystroke count has not yet filled the `advancement_accuracy_window` (default 200) get an additional bonus so they accumulate enough data to produce reliable accuracy readings (and stop blocking the introduction of the next letter).

The bonus uses a cosine fade centred on the window size:
- **Full bonus** (`weight_volume_deficit`, default 1.0) until 85% of window (170 keystrokes)
- **Half bonus** (0.5) at exactly the window size (200 keystrokes)
- **Zero** at 115% of window (230 keystrokes)

The fade zone is `window ± 15%`. This avoids a linear taper that would produce a discouraging slow creep toward the threshold.

| Keystrokes | Bonus (at default weight 1.0) |
|---|---|
| 0–170 | 1.00 |
| 185 | ~0.85 |
| 200 | 0.50 |
| 215 | ~0.15 |
| 230+ | 0.00 |

**No weight cap on individual letters.** Instead, a **share cap** prevents any single letter from dominating:

### Share Cap

After computing raw weights, the text generator clamps the maximum share any single letter can occupy to `max_letter_share` (default 35%). If any letter's raw share exceeds this, its weight is clamped and the freed weight is redistributed proportionally among uncapped letters.

The effective cap is `max(max_letter_share, 1/n)` where n is the number of active letters, ensuring the cap never drops below equal share.

This prevents massed repetition. Motor learning research shows interleaved practice builds more durable motor patterns than blocked drilling of a single item.

### Word Weighting (random_words mode)

In random_words mode, each word's weight equals the **maximum** letter weight among its characters. This ensures any word containing a high-need letter is prioritized, avoiding the dilution problem of mean-based weighting (where a 6-letter word with one struggling letter barely differs from an all-stable word).

---

## Spaced Repetition

The tool maintains a consolidation model across sessions:

- Each letter has a `last_practiced` timestamp and a `stability_score`
- New letters start at `stability_score = 0.3` (below the 0.5 review threshold, so they are immediately flagged for practice)
- After a good session (per-letter accuracy >= 95%), stability increases by +0.2 (capped at 1.0)
- After a bad session (per-letter accuracy < 95%), stability decreases by -0.1 (floored at 0.0). Only applies to letters actually practiced in the session.
- If a `stable` letter's stability drops below 0.5 due to bad sessions, it reverts to `consolidating` (triggering more focused practice)
- Stability also decays over time using a half-life model
- At session start, the tool shows which letters are **due for review** based on decay

**Stability progression for a new letter** (with consistent good practice):
0.3 -> 0.5 (crosses review threshold) -> 0.7 -> 0.9 -> 1.0

The asymmetric +0.2/-0.1 means building stability requires more evidence than losing it: two good sessions to recover from one bad session.

**Decay function** (Ebbinghaus-inspired):
```
stability(t) = stability_0 * e^(-ln(2) * t / half_life)
```

| State | Half-life |
|---|---|
| `introducing`, `consolidating`, `degraded` | 24 hours |
| `stable` | 72 hours |

If a letter's stability drops below 0.5, its state reverts to `consolidating` and the user is notified.

---

## Error Handling During a Run

- Errors are **permanently highlighted** in the text display: the wrong character is shown in red at the error position
- The run is never interrupted for a single error
- A **running accuracy display** is shown during the run (updated after each keystroke)
- If accuracy drops below the **fail threshold** AND the run has accumulated at least 5 cognitive errors, the run **ends immediately** with a failure state
  - Standard fail threshold: 90% in relearning, 95% in speed mode
  - Progressive threshold applies for newly introduced letters (see above)
- On failure: the user is shown per-letter error rates and can immediately start a new run

The tool does **not** require pressing the correct key after an error. The next character in sequence is always the expected one. Rationale: requiring correct-after-wrong trains an artificial correction pattern that does not transfer to real typing.

### Run Abort (Escape)

The user can abort a run at any time by pressing Escape (double-press confirmation). Aborted runs are discarded entirely -- nothing is saved to the database, no state changes occur. There is no penalty for aborting.

### Return Key

The Return key starts a new run from the configuration screen and continues from the summary screen. This allows the user to chain runs without mouse interaction.

---

## Phase 2: Speed Training

### Entry Condition

Speed training is available only when:
- All target letters are in `stable` state
- Full letter set accuracy >= 95% across last 5 consecutive sessions

### Mechanism

- The tool tracks a **target WPM** (starts at 30, persisted across sessions)
- Accuracy threshold is enforced: 95%
- If accuracy drops below threshold during a run (after 5 errors): run fails
- If run completes above threshold: target WPM increases by 2
- If run fails: target WPM decreases by 4
- Backspace is enabled; accuracy is based on first input per position

The +2/-4 ratio produces a 33% failure rate at equilibrium (67% success), which falls within the 60-80% success range recommended by motor learning research for optimal skill acquisition. The previous +2/-1 ratio produced 67% failure -- too punishing.

### Per-Key Speed Diagnostics

In speed mode, the tool tracks **per-key reaction time** (time from previous keypress to this keypress).

After each run, the user sees:
- Mean reaction time per key
- Keys with reaction time > 1.5x the run median are flagged as speed bottlenecks
- Historical trend of reaction time per key across sessions

---

## Analytics

The tool provides 9 analytics chart tabs, accessible via the Analysis tab (disabled during typing runs, refreshed on tab switch):

1. **Accuracy**: Per-run accuracy over time (line chart)
2. **WPM**: Per-run WPM over time, split by practice type with color-coded lines. Failed runs marked with red X.
3. **Per-Letter Accuracy**: Rolling accuracy per letter over time (multi-line chart with letter selector)
4. **Per-Letter RT**: Mean reaction time per letter over time (multi-line chart with letter selector)
5. **Errors**: Stacked bar chart of error rate per letter, broken down by error type (spatial, same-finger, mirror, other) using QWERTZ physical layout adjacency
6. **Confusion Matrix**: Top-15 confusion pairs bar chart (normalized by expected-letter keystrokes) + grid heatmap. Color-coded by error type.
7. **Swaps**: Horizontal bar chart of most frequently swapped bigrams
8. **Position**: Error rate by position within runs (5-char buckets) with Wilson score 95% confidence interval error bars and average reference line
9. **Bigrams**: Two tables showing error-prone bigrams (sorted by error rate) and slow bigrams (sorted by trimmed mean transition time, 10% trimmed). Only analyzes `random_words`, `sentences`, and `bigram_words` practice types with minimum 10 occurrences. User selects 1-3 bigrams to target, then clicks "Train Selected Bigrams" to switch to transition training mode.

### Error Type Classification

Cognitive errors are classified by physical cause using QWERTZ layout geometry:
- **Spatial**: Adjacent key on the physical layout (accounting for row stagger)
- **Same finger**: Different key assigned to the same finger
- **Mirror**: Corresponding key on the opposite hand (e.g., left index vs right index)
- **Other**: None of the above

Priority: spatial > same_finger > mirror > other.

---

## Data Storage

### Format

All data is stored in a local **SQLite** database. No cloud sync, no internet required. The database and config file are stored in a `training-data/` directory within the project, which is gitignored.

### Captured Data

Every keystroke is logged with:
- Timestamp (millisecond resolution)
- Expected character
- Actual character typed
- Error classification (`correct`, `cognitive_error`, `motor_overflow`, `burst_repeat`)
- Reaction time (ms since previous keystroke)
- Position in target text
- Backspace flag

All same-key intervals are logged regardless of motor overflow classification, to enable later threshold calibration.

### Raw vs Derived Columns

The `keystrokes` table separates raw measurements from computed fields:

**Raw measurement columns** (immutable once written):
- `position`, `timestamp_ms`, `expected_char`, `actual_char`, `is_backspace`

**Derived columns** (recomputable via `reclassify_all_runs()`):
- `error_type` — reclassified by ErrorClassifier from raw columns
- `reaction_time_ms` — recomputed from `timestamp_ms` differences between cursor-advancing keystrokes

**Deprecated columns** (retained for historical data):
- `prev_char` — superseded by self-join on `(run_id, position-1)`. New keystrokes write `NULL`.

The `runs` table has **denormalized aggregates** that are also recomputed during reclassification:
- `total_keystrokes`, `cognitive_errors`, `motor_overflow_errors`, `burst_repeat_count`, `swap_count`, `accuracy`

### Reclassification

`reclassify_all_runs()` re-runs ErrorClassifier on all raw keystroke data and updates derived columns and run aggregates. It is:
- **Idempotent**: running it twice produces the same result
- **Automatic**: runs once as a v6 schema migration on existing databases
- **Correct**: mirrors engine.py's `prev_timestamp` tracking (only cursor-advancing keystrokes update the previous timestamp)

Use cases: fixing historical misclassifications (e.g. motor overflow false positives on legitimate double-letters), applying updated classification logic retroactively.

### Corpus Files

Word lists are stored as plain text files, one word per line. Separate files per language (e.g., `corpus_en.txt`, `corpus_de.txt`). Adding words is done by editing the file directly. Placeholder lists are included.

---

## Configuration

All thresholds are user-configurable via JSON file. Missing keys use defaults.

### Advancement

| Parameter | Default | Description |
|---|---|---|
| `advancement_accuracy` | 0.95 | Per-letter accuracy required to unlock a new letter |
| `advancement_accuracy_window` | 200 | Rolling window size (keystrokes per letter) |
| `advancement_min_keystrokes` | 500 | Minimum total keystrokes since last introduction |

### Fail Thresholds

| Parameter | Default | Description |
|---|---|---|
| `fail_threshold_min_errors` | 5 | Minimum cognitive errors before fail check activates |
| `fail_threshold_relearning` | 0.90 | Accuracy floor during relearning |
| `fail_threshold_speed` | 0.95 | Accuracy floor during speed mode |
| `fail_threshold_introducing_s1` | 0.70 | Fail threshold for 1st session with new letter |
| `fail_threshold_introducing_s2` | 0.80 | Fail threshold for 2nd session with new letter |
| `fail_threshold_transition` | 0.95 | Accuracy floor during transition training |

### Run Defaults

| Parameter | Default | Description |
|---|---|---|
| `run_length_default_relearning` | 60 | Default keystrokes per relearning run |
| `run_length_default_speed` | 100 | Default keystrokes per speed run |
| `run_length_default_transition` | 80 | Default keystrokes per transition run |
| `run_length_minimum` | 50 | Minimum keystrokes per run |
| `warmup_keystrokes` | 3 | Keystrokes excluded from scoring at run start |

### Speed Training

| Parameter | Default | Description |
|---|---|---|
| `speed_increment` | 2 | WPM increase on successful speed run |
| `speed_decrement` | 4 | WPM decrease on failed speed run |

### Text Generation

| Parameter | Default | Description |
|---|---|---|
| `max_letter_share` | 0.35 | Maximum share of chars any single letter can occupy |

### Bigram Transition Training

| Parameter | Default | Description |
|---|---|---|
| `bigram_min_count` | 10 | Minimum occurrences to display a bigram in analysis |
| `bigram_target_share` | 0.40 | Target share of chars from bigram-containing words (~40%) |
| `bigram_max_targets` | 3 | Maximum bigrams selectable for a single transition run |
| `bigram_trimmed_mean_fraction` | 0.10 | Fraction to trim from each tail for trimmed mean RT |

### Error Classification

| Parameter | Default | Description |
|---|---|---|
| `motor_overflow_window_ms` | 80 | Time window (ms) for double-press detection |
| `burst_max_interval_ms` | 500 | Max interval (ms) for burst repeat detection |

### Session Management

| Parameter | Default | Description |
|---|---|---|
| `session_timeout_minutes` | 30 | Inactivity timeout for session boundary |
| `rest_suggestion_seconds` | 30 | Suggested rest between runs |

### Degradation

| Parameter | Default | Description |
|---|---|---|
| `degraded_recovery_margin` | 0.8 | Multiplier for DEGRADED -> STABLE recovery threshold |

### Spaced Repetition

| Parameter | Default | Description |
|---|---|---|
| `half_life_consolidating_hours` | 24.0 | Stability decay half-life for non-stable letters |
| `half_life_stable_hours` | 72.0 | Stability decay half-life for stable letters |
| `stability_revert_threshold` | 0.5 | Stability below which a letter reverts to consolidating |

### Paths and Language

| Parameter | Default | Description |
|---|---|---|
| `corpus_dir` | `data` | Directory containing corpus files |
| `db_path` | `typing_trainer.db` | SQLite database filename |
| `language` | `de` | Active language (`en` or `de`) |

---

## Technical Requirements

- Desktop application: Python + PyQt6 + pyqtgraph
- Project managed with `uv` + `pyproject.toml`
- All data stored locally in SQLite
- Keyboard layout: QWERTZ only in v1
- Input captured at keystroke level with millisecond timestamps
- No dependency on internet connection
- Corpus: plain text files, one word per line
- Target languages: English and German
- Type checking: pyright (strict, 0 errors)
- Testing: pytest

---

## Explicitly Out of Scope (v1)

- Multiplayer or competitive modes
- Games
- Audio feedback
- On-screen keyboard visualization
- Mobile support
- Cloud sync
- Capital letters / shift key
- Multiple keyboard layouts (QWERTZ only)
- Sentence corpus (current `sentences` mode uses word sequences)
- Adaptive run length
- Fatigue detection / enforced rest
- Any feature whose primary purpose is engagement rather than learning

---

## Phase 3: Transition Training

### Overview

A third run mode (**Transition**) that trains weak bigrams (letter-to-letter transitions) using real words from the corpus. Typing is fundamentally about transitions, not isolated letters — the per-letter system can miss transition-level patterns (e.g., `n→e` confusion at 26 occurrences).

### Motor Learning Principles

- **Real words only**: Transitions trained in word context transfer better than isolated bigram drilling. Linguistic processing primes motor sequences.
- **No isolated drilling**: Never generate "th th th th". The motor reset between repetitions breaks chaining context.
- **Interleaved targets**: 1-3 target bigrams per run, embedded in varied word contexts. Contextual interference improves long-term retention.
- **User-directed selection**: The user analyzes their data and selects which bigrams to target. Self-directed practice improves learning outcomes.

### Entry Conditions

Same as speed mode:
- All letters in `stable` state
- At least 5 sessions with aggregate accuracy ≥ 95%
- Bigrams selected (1-3) from the analysis view

### Flow

1. User opens **Analysis → Bigrams** tab
2. Two tables show error-prone bigrams (sorted by error rate) and slow bigrams (sorted by trimmed mean transition time)
3. Only `random_words`, `sentences`, and `bigram_words` practice types are analyzed (not `random_strings`)
4. Minimum 10 occurrences per bigram to appear
5. User selects 1-3 bigrams across either table, clicks "Train Selected Bigrams"
6. App switches to Training tab, auto-selects Transition mode
7. Practice type is fixed to `bigram_words`
8. Run proceeds like speed mode (backspace enabled, fail threshold 95%)

### Text Generation

- ~40% of characters come from words containing at least one target bigram
- ~60% come from normal words (contextual interference)
- Words are filtered to the active letter set
- If fewer than 20 bigram words match after filtering, bigram word filtering is relaxed (uses full corpus for bigram words only)
- No isolated bigram drilling — all practice uses complete real words

### Metrics

- **Bigram error rate**: `(prev_char, expected_char)` pairs, where error_type IN ('correct', 'cognitive_error'). Normalized as errors/total.
- **Bigram transition time**: Raw reaction times collected per bigram, then computed as trimmed mean (10%) in Python. Only correct keystrokes with non-null RT.
- `prev_char` is the *actual* character typed (not expected). On correct keystrokes (97%+), this equals the expected character, so bigram RT data is clean.

### Database

- Index: `idx_keystrokes_bigram ON keystrokes(prev_char, expected_char, error_type, is_backspace)` — covers both error-rate and transition-time queries
- No new tables needed — all data comes from existing `keystrokes` table
