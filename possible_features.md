# Possible Future Features

## Swap Error Enhancements

Swap errors (adjacent letter transpositions, e.g., typing "ne" instead of "en") are
currently tracked as a diagnostic metric. Each swap counts as 2 cognitive errors.
Analysis of training data found 9 swap events across 48 runs.

### Swap-Aware Accuracy

Count a transposition as 1 cognitive error instead of 2. The motor planning mistake
is a single sequencing error (wrong finger order), not two independent wrong-key
errors. This would reduce the accuracy penalty by 1 error per swap.

**Implementation**: In the engine, when a swap is detected, retroactively change the
first keystroke of the pair from COGNITIVE_ERROR to a new SWAP_FIRST type (excluded
from error count), keeping only the second as COGNITIVE_ERROR. Or simply subtract 1
from cognitive_errors when a swap is detected.

### Swap Drill Practice Type

Generate text that specifically targets commonly swapped letter pairs. For example,
if "e/n" swaps are frequent, generate text with many "en" and "ne" bigrams to build
correct sequencing.

**Implementation**: Track per-pair swap frequencies in the database. Add a new
practice type that constructs text emphasizing problem bigrams. Could alternate
between the two orderings (e.g., "en ne en ne") for focused motor pattern training.

### Per-Pair Swap Frequency Tracking

Store which letter pairs get transposed most often. Display in session dashboard
as a diagnostic (e.g., "Most swapped pairs: e/n (5x), i/s (2x)").

**Implementation**: Add a `swap_pairs` table with columns (letter_a, letter_b, count).
Increment on each detected swap. Query for dashboard display.

## Burst Detection Enhancements

### Adaptive Burst Threshold

The current burst_max_interval_ms (500ms) is fixed. A user-adaptive threshold could
be computed from the distribution of same-key intervals in the user's data. For
example, set the threshold at the 95th percentile of intentional same-key intervals.

### Burst Recovery Assistance

When a burst is detected during a run, show a brief visual indicator ("Key held -
release and retry") to help the user recover. Currently bursts are silently absorbed.
