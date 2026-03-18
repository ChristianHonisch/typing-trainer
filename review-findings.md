# Code Review Findings

Date: 2026-03-15

## Critical (fix now)

### 1. Interactive legend color mutation bug
**File:** `src/typing_trainer/ui/charts/interactive_legend.py:100-105`
**Description:** `pen.color()` returns a reference to the pen's internal QColor. Calling `color.setAlpha(self._dim_alpha)` mutates the original pen color stored in `_original_pens`. After highlight/restore cycles, pen colors get permanently corrupted (alpha stuck at 50 instead of 255).
**Fix:** Clone the color before mutating: `color = QColor(pen.color())`
**Status:** Fixed

### 2. MASTERED letters block speed mode
**File:** `src/typing_trainer/core/speed_manager.py:79-81`
**Description:** `all(s.state == LetterState.STABLE for s in active_letters.values())` rejects MASTERED letters. Once any letter reaches MASTERED, speed mode becomes inaccessible.
**Fix:** Change to `s.state in (LetterState.STABLE, LetterState.MASTERED)`
**Status:** Fixed

## Major (fix soon)

### 3. Debug print statements in production
**File:** `src/typing_trainer/ui/charts/bigram_chart.py:224-278`
**Description:** 5 `print(f"[BigramChart] ...")` statements write to stdout in production.
**Fix:** Remove all print statements.
**Status:** Fixed

### 4. Missing database index on keystrokes
**File:** `src/typing_trainer/storage/database.py:99-101`
**Description:** Most per-letter queries filter by `(expected_char, error_type, is_backspace)` but there's no composite index. These queries do full table scans on the `keystrokes` table, which grows large over time.
**Fix:** Add index: `CREATE INDEX IF NOT EXISTS idx_keystrokes_expected_error ON keystrokes(expected_char, error_type, is_backspace);`
**Status:** Fixed

### 5. `assert` used for runtime checks (stripped in -O mode)
**Files:**
- `src/typing_trainer/ui/charts/accuracy_chart.py:54,64,72-73`
- `src/typing_trainer/ui/charts/wpm_chart.py:75,86,93-95`
- `src/typing_trainer/storage/repository.py:79,158`
**Description:** `assert x is not None` is silently removed when Python runs with `-O`. If the asserted condition fails in optimized mode, the code proceeds with `None`, causing downstream crashes.
**Fix:** Replace with `if x is None: raise RuntimeError(...)` or early return.
**Status:** Fixed

### 6. N+1 query pattern in per-letter methods
**File:** `src/typing_trainer/storage/repository.py:524-647`
**Description:** `get_per_letter_rolling_accuracy`, `_relearning` variant, and `get_per_letter_error_window` each loop over letters and issue one SQL query per letter. With 26 letters, that's 26 queries per method call.
**Fix:** Batch into a single query with `WHERE expected_char IN (...)` and `GROUP BY`, or use a single query ordered by `(expected_char, id DESC)` and partition in Python.
**Status:** Open (mitigated by new index #4; per-letter loop kept for simplicity)

### 7. DRY violation: 3 near-identical rolling accuracy methods
**File:** `src/typing_trainer/storage/repository.py:524-647`
**Description:** `get_per_letter_rolling_accuracy` and `get_per_letter_rolling_accuracy_relearning` are near-identical (~35 lines each). The only difference is an extra JOIN + WHERE clause. `get_per_letter_error_window` has the same duplication with its `learn_keys_only` flag.
**Fix:** Consolidated into `_query_recent_keystrokes()` private helper + unified `get_per_letter_rolling_accuracy(learn_keys_only=False)`. Removed `get_per_letter_rolling_accuracy_relearning`.
**Status:** Fixed

### 8. Encapsulation violation in main_window
**File:** `src/typing_trainer/ui/main_window.py:512`
**Description:** `self._config_widget._preset_combo.findText("Smooth Pairs")` reaches into a private member. If `RunConfigWidget` changes internally, this silently breaks.
**Fix:** Add a public method `RunConfigWidget.select_preset(name: str)` and call that.
**Status:** Fixed

### 9. `finish_run()` overwrites end_time
**File:** `src/typing_trainer/core/engine.py:346`
**Description:** `finish_run()` unconditionally sets `end_time = datetime.now()`. If the run already finished (e.g., via fail threshold), the accurate end time is overwritten with a later timestamp.
**Fix:** Guard with `if self.state.end_time is None:`
**Status:** Fixed

### 10. `_state_bonus` match has no default case
**File:** `src/typing_trainer/models/letter_state.py:143-177`
**Description:** The `match/case` on `self.state` covers all current enum members but has no wildcard. If a new enum member is added, the function returns `None`, causing `TypeError` in arithmetic.
**Fix:** Add `case _: return 0.0`
**Status:** Fixed

### 11. Swap detection false positives
**File:** `src/typing_trainer/storage/repository.py:969-1005`
**Description:** The `LAG()` window function operated over pre-filtered `cognitive_error` rows only. Two cognitive errors that were 50 keystrokes apart in the actual stream would be treated as "consecutive," producing false swap detections.
**Fix:** Restructured CTE to apply `LAG()` over ALL keystrokes first (`with_lag`), then filter for pairs where both current and previous are `cognitive_error`. Both `last_n` and non-`last_n` branches fixed.
**Status:** Fixed

## Minor (address when touching these files)

### Code duplication
- `accuracy_chart.py` / `wpm_chart.py`: ~50 lines identical right Y-axis setup
- `per_letter_chart.py` / `per_letter_rt_chart.py`: identical `_LETTER_COLORS` palette and checkbox management (~25 lines each)
- `error_heatmap.py` / `confusion_matrix_chart.py` / `swap_chart.py`: identical "last N keys" filter controls
- `run_config_widget.py` / `run_summary_widget.py`: duplicated rest timer logic
- `text_generator.py`: identical text-trimming logic in 3 methods
- `test_repository.py`: ~400 lines of duplicated test helpers across 12 classes; file is 2700+ lines

### Dead code
- ~~`main_window.py:84-85`: `_last_run_result` and `_last_speed_result` set but never read~~ **Fixed**
- ~~`confusion_matrix_chart.py:290`: `count_matrix` built but never used~~ **Fixed**
- ~~`error_heatmap.py:170`: `total_errors` list built but never used~~ **Fixed**
- `error_classifier.py`: `swap_count` tracked redundantly in both classifier and engine state

### God methods (too long / too many responsibilities)
- `main_window.py:363-498`: `_refresh_dashboard` ~120 lines, 7+ responsibilities
- `run_summary_widget.py:431-669`: `_update_speed_chart` ~240 lines
- `run_speed_chart.py:191-377`: `_redraw()` 186 lines
- `repository.py:1500-1715`: `bootstrap_mastery` 215 lines, mixed concerns

### Other minor issues
- `error_types.py:114-115`: `classify_error("a", "a")` silently returns `"other"` for non-errors
- `run_result.py:119-133`: `compute_wpm` can return negative if data is corrupt
- `repository.py:32-55`: datetime parsing requires microseconds — should use `datetime.fromisoformat()`
- `test_error_types.py:113-114,160-162`: empty test methods with `pass` only
- No unit tests for any of the 14 chart files
- `analytics_widget.py:146-163`: refreshes all 13 charts even when hidden
- `config.py`: no validation of loaded values (e.g., `advancement_accuracy: 2.0` would be accepted)
- `main.py:14`: `DATA_DIR` path computation assumes running from source tree, not installed package
- `engine.py:282`: `backspace_count` incremented even when backspace is disabled (relearning mode)

### Style
- Inconsistent import locations (`defaultdict` local in some methods, top-level in others)
- Hardcoded colors outside `theme.py` (`#44aaff`, `#888888`, etc.)
- `letter_state.py` contains `ErrorType`, `DisplayMode`, `RunMode`, `PracticeType` — file name doesn't match scope
- No `__all__` exports in any module
- All `datetime.now()` calls are timezone-naive

## TODO (design questions)

### Mastery criteria too lenient
The current mastery system increments `mastery_score` by `qualifying_ks / mastery_ks_required` each session. This can reach the threshold in ~2-3 sessions for common letters. Consider requiring sustained high precision over multiple sessions or a time-based gate (e.g., STABLE for >= 7 days).
