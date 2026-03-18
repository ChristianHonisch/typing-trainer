# UI/UX Review

Date: 2026-03-15

## Critical (user-facing bugs or accessibility failures)

### 1. Upcoming text contrast fails WCAG AA
**Location:** `theme.py:53`, `typing_widget.py:270`
**Description:** `COLOR_TEXT_MUTED` (#666666) on #1e1e1e gives ~3.3:1 contrast ratio. The text users need to read to type fails WCAG AA (requires 4.5:1). Most severe accessibility issue — causes eye strain during extended sessions.
**Fix:** Brighten to #999999 (~5.6:1) or #aaaaaa (~7.8:1).
**Status:** Fixed

### 2. Success green contrast fails WCAG AA
**Location:** `theme.py:21`, `typing_widget.py:259,293`
**Description:** `COLOR_SUCCESS` (#4a9e4a) on #1a1a1a gives ~3.8:1 contrast. Used for correct characters, accuracy display, advancement indicators.
**Fix:** Brighten to #5cb85c (~5.0:1) or #6bc76b (~5.8:1).
**Status:** Fixed

### 3. fix_keys and Failed use identical red in WPM chart
**Location:** `wpm_chart.py:36-37`
**Description:** Both `fix_keys` practice type and "Failed" markers use #ff4444. Impossible to distinguish.
**Fix:** Change fix_keys to a different color (e.g., orange #cc7722).
**Status:** Fixed

### 4. Same Finger and Burst Repeat use identical yellow
**Location:** `error_timeline_chart.py:58-59`
**Description:** Both categories use #cccc44. Visually indistinguishable.
**Fix:** Change Burst Repeat to a distinct color (e.g., dark red #cc4444).
**Status:** Fixed

### 5. Checkbox panel has no scroll area
**Location:** `per_letter_chart.py:64-68`, `per_letter_rt_chart.py:112-116`
**Description:** With 15+ letters, checkboxes below the visible area are inaccessible. The QVBoxLayout on a fixed-width container has no scroll.
**Fix:** Wrap the checkbox container in a QScrollArea.
**Status:** Open

## High (significant usability problems)

### 6. No ensureCursorVisible() in typing widget
**Location:** `typing_widget.py:226-280`
**Description:** Cursor goes off-screen in long texts (200+ keystrokes). The QTextEdit never scrolls to follow the cursor position.
**Fix:** Call `ensureCursorVisible()` or manually scroll after each keystroke.
**Status:** Open

### 7. 8 columns in ~300px sidebar
**Location:** `letter_overview.py:83-95`
**Description:** Column headers like "Keystrokes" and "Rolling Err" are truncated. Data is unreadable at default sidebar width.
**Fix:** Use ResizeToContents for key columns, abbreviate headers, or reduce column count.
**Status:** Open

### 8. No empty state messages on 12 of 13 charts
**Location:** All charts except `swap_chart.py`
**Description:** Blank canvas when there's no data. New users see empty charts with no guidance.
**Fix:** Create a shared `_show_empty_state(plot, message)` helper and use consistently.
**Status:** Fixed (for all charts)

### 9. All letters checked by default in per-letter charts
**Location:** `per_letter_chart.py:111`, `per_letter_rt_chart.py:231`
**Description:** 20+ overlapping lines create unreadable spaghetti.
**Fix:** Default to worst 5-8 letters only.
**Status:** Open

### 10. Only 12 colors for 26 letters
**Location:** `per_letter_chart.py:30-43`, `per_letter_rt_chart.py:44-57`
**Description:** 13th letter reuses 1st color via modulo. Letters become indistinguishable.
**Fix:** Expand palette to 26 distinct colors.
**Status:** Open

### 11. No visual labels on the two analytics tab tiers
**Location:** `analytics_widget.py:86-127`
**Description:** Both QTabWidgets look identical. User can't tell which tier is which.
**Fix:** Add a small header label above each tier (e.g., "Core Analytics" / "Deep Analysis").
**Status:** Fixed

### 12. No QScrollArea on sidebar and summary widget
**Location:** `run_summary_widget.py`, `session_dashboard.py`
**Description:** Content clips on small windows or with many active letters.
**Fix:** Wrap in QScrollArea.
**Status:** Open

### 13. Blue and cyan too similar in run speed chart
**Location:** `run_speed_chart.py:293,301`
**Description:** "Settled" (#44aaff) and "Space" (#44cccc) lines are nearly indistinguishable.
**Fix:** Change Space to a more distinct color (e.g., orange or magenta).
**Status:** Fixed

## Medium (usability friction, inconsistencies)

### 14. Display mode combo not disabled during typing
**Location:** `main_window.py:138-148`
**Description:** User could accidentally change display mode mid-run, causing sidebar to appear/disappear.
**Fix:** Disable the combo during typing runs.
**Status:** Fixed

### 15. Silent preset auto-switch when deselecting letter
**Location:** `run_config_widget.py:618-633`
**Description:** Deselecting any letter in Learn Keys silently switches to Fix Keys preset.
**Fix:** Show a brief notification or toast.
**Status:** Open

### 16. Error sub-type breakdown shown in BASIC mode
**Location:** `run_summary_widget.py:265-324`
**Description:** Spatial/same-finger/mirror breakdown is too technical for Basic users.
**Fix:** Only show error sub-types in Nerd+ mode.
**Status:** Fixed

### 17. Analytics tab names unclear
**Location:** `analytics_widget.py`
**Description:** "Letter %", "Per-Letter RT", "Accuracy (Letter)", "Position", "Errors" are ambiguous or jargon-heavy.
**Fix:** Rename to clearer labels: "Letter Frequency", "Letter Speed", "Per-Letter Accuracy", "Error by Position", "Error Breakdown".
**Status:** Fixed

### 18. Stability shown without context
**Location:** `session_dashboard.py:363-370`
**Description:** "Stability 0.42" is an abstract number. Users don't know if it's good or bad.
**Fix:** Add a description or color threshold (e.g., below 0.5 = "needs review").
**Status:** Open

### 19. Single-hue red heatmap in confusion matrix
**Location:** `confusion_matrix_chart.py:290-301`
**Description:** Hard to read fine-grained differences in a monochrome red heatmap.
**Fix:** Use a sequential colormap (e.g., blue-to-red or viridis).
**Status:** Open

### 20. Dual Y-axis unclear
**Location:** `accuracy_chart.py`, `wpm_chart.py`
**Description:** Grey letter-count line at #888888 is hard to see, no legend explains which line goes with which axis.
**Fix:** Add the letter-count line to the legend, brighten the color.
**Status:** Open

### 21. Locked letters sort to top
**Location:** `letter_overview.py:190-210`
**Description:** Sorting any column ascending puts locked letters (sort value -1.0) above active letters.
**Fix:** Use a sort value that keeps locked letters at the bottom (e.g., `float('inf')`).
**Status:** Open

### 22. Mode label shows raw technical names
**Location:** `typing_widget.py:220-222`
**Description:** Shows "RELEARNING | random strings" instead of "Learn Keys".
**Fix:** Map to user-facing preset names.
**Status:** Fixed

### 23. Run-over-run delta red/green coloring
**Location:** `run_summary_widget.py:372-384`
**Description:** Normal 5-15% variation shows as alarming red, inducing performance anxiety.
**Fix:** Compare against rolling average rather than single previous run, or remove color coding.
**Status:** Open

### 24. 26-entry legend in letter occurrence chart
**Location:** `letter_occurrence_chart.py:100-103`
**Description:** Massive legend overlaps chart data at any reasonable window size.
**Fix:** Show only top-N letters or move legend to a separate panel.
**Status:** Open

### 25. Splitter can collapse tabs to zero
**Location:** `analytics_widget.py:83`
**Description:** User can accidentally hide entire tab tier by dragging splitter.
**Fix:** `setCollapsible(0, False)` and `setCollapsible(1, False)`.
**Status:** Fixed

### 26. Preset descriptions explain what it IS, not what to DO
**Location:** `run_config_widget.py:53-64`
**Description:** "The motor foundation..." doesn't help users decide which preset to choose.
**Fix:** Reword to action-oriented: "Choose this if..."
**Status:** Open

### 27. No data-point tooltips on any chart
**Location:** All charts
**Description:** Hovering over chart data shows nothing. Users can't see exact values.
**Fix:** Add hover tooltips to key chart types.
**Status:** Open

## Low (polish, edge cases, nice-to-have)

28. `main_window.py:122` — 1000×700 minimum size too large for 1366×768 laptops
29. `theme.py:64-65` — Disabled button text (#666666 on #333333) at 1.8:1 contrast
30. No onboarding/welcome message for first launch
31. No keyboard shortcuts for tab switching (Ctrl+1/2)
32. No "Select All / Deselect All" for checkbox panels
33. `run_speed_chart.py:47` — Default window=1 (raw) is too noisy
34. `bigram_chart.py` — Selections lost on refresh without warning
35. No export/copy capability on any chart
36. InteractiveLegend has no click-to-toggle (only hover)
37. `theme.py:122` — `DEBUG_TEXT_SELECTABLE = True` left on in production
38. All 13 charts refresh eagerly even when invisible
39. No debouncing on filter spinner valueChanged
40. `error_window_chart.py:170` — Letter labels uppercase, all other charts lowercase
41. No visual word boundaries in random_words typing text
