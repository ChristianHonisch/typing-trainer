# Mastery System Design

## Overview

`mastery_score` (0.0–1.0) tracks long-term motor pattern encoding, separate from `stability_score` (short-term session quality). Mastered letters get reduced training weight (0.5 instead of 1.0), freeing up practice share for letters that still need work. This is critical at scale — at 26 letters all at weight 1.0, the weighting system can't meaningfully differentiate.

## New State: MASTERED

```
introducing → consolidating → stable → mastered
                                ↑          ↓
                                ← degraded ←
```

MASTERED is a state beyond STABLE. It indicates the motor pattern is deeply encoded through sustained, distributed practice.

## Earning Mastery

### Qualifying Condition

A letter qualifies for mastery progress when:
- State is STABLE or MASTERED
- Per-letter rolling accuracy ≥ `advancement_accuracy` (95%)

### Score Increment

After each session, for each qualifying letter:

```
delta = qualifying_keystrokes_this_session / mastery_keystrokes_required
mastery_score = min(1.0, mastery_score + delta)
```

- `mastery_keystrokes_required`: 1500 (configurable)
- At ~19 qualifying keystrokes per session for a settled letter: delta ≈ 0.013
- ~78 sessions (~2.5 months of daily practice) to reach 1.0

### State Transition

STABLE → MASTERED when `mastery_score >= mastery_threshold` (default 0.8).

This occurs at ~1200 qualifying keystrokes, which takes ~63 sessions of daily practice for a settled letter.

## Mastery Decay

Mastery decays over time when the letter isn't practiced, using an Ebbinghaus-inspired exponential:

```
mastery_score(t) = mastery_score_0 × e^(-ln(2) × hours_elapsed / (half_life × 24))
```

The half-life scales linearly with current mastery level:

```
half_life_days = mastery_half_life_min + mastery_score × (mastery_half_life_max - mastery_half_life_min)
```

| Mastery score | Half-life |
|---|---|
| 0.0 | 14 days |
| 0.5 | 52 days |
| 0.8 | 75 days |
| 1.0 | 90 days |

### Equilibrium

With daily practice adding ~0.013 and daily decay at mastery=0.8 being ~0.92% (≈0.0074), the net daily gain is positive (~0.005). Missing 2+ days causes net decay, requiring extra practice to catch up. This naturally rewards consistent distributed practice.

### Interaction with Practice

Decay reduces `mastery_score` but the score recovers when the user practices again (qualifying keystrokes add delta). A user who takes a 2-week break might see mastery drop from 1.0 to ~0.87 (still MASTERED), but a month-long break could drop it below 0.8 (exits MASTERED → STABLE).

## Tracking

`mastery_qualifying_keystrokes` is persisted as a historical record (total lifetime qualifying keystrokes for this letter). It is NOT used to compute `mastery_score` — the score is tracked independently, pushed up by practice and pulled down by decay.

The keystroke count is purely informational (e.g., UI display: "1234 qualifying keystrokes").

## Training Weight

| State | Base weight | Notes |
|---|---|---|
| MASTERED | 0.5 | Reduced to free share for non-mastered letters |
| STABLE (settled) | 1.0 | Sessions in state ≥ recently_stable_sessions |
| STABLE (recently) | 1.0–2.0 | Decaying recently-stable bonus |
| CONSOLIDATING | 2.0 | 1.0 base + 1.0 state bonus |
| DEGRADED | 3.0 | 1.0 base + 2.0 state bonus |
| INTRODUCING | 4.0 | 1.0 base + 3.0 state bonus |

### Effect at Scale (26 letters)

Without mastery (all stable at 1.0):
- Introducing letter: 5.0 / 30.0 = 16.7% share
- Each settled letter: 1.0 / 30.0 = 3.3% share

With mastery (20 mastered at 0.5, 5 stable at 1.0, 1 introducing at 5.0):
- Introducing letter: 5.0 / 20.0 = 25.0% share
- Each stable letter: 1.0 / 20.0 = 5.0% share
- Each mastered letter: 0.5 / 20.0 = 2.5% share

The introducing letter gets 50% more share — much more effective practice allocation.

## Degradation

- **MASTERED → DEGRADED**: Same trigger as STABLE → DEGRADED (rolling error rate > 5%)
- `mastery_score` is NOT reset on degradation — it decays naturally over time
- `mastery_qualifying_keystrokes` freezes (no penalty)
- **DEGRADED → STABLE**: Standard recovery (rolling error rate ≤ 4%)
- **STABLE → MASTERED**: Re-enters MASTERED if `mastery_score ≥ mastery_threshold` (0.8)

A letter that briefly degrades and recovers quickly can return to MASTERED without re-earning all the keystrokes, because the mastery_score may still be above threshold.

## New Config Fields

| Field | Default | Description |
|---|---|---|
| `mastery_keystrokes_required` | 1500 | Qualifying keystrokes for mastery_score delta = 1.0 |
| `mastery_threshold` | 0.8 | mastery_score at which STABLE → MASTERED |
| `mastery_half_life_min_days` | 14 | Decay half-life at mastery_score = 0.0 |
| `mastery_half_life_max_days` | 90 | Decay half-life at mastery_score = 1.0 |
| `weight_mastered` | 0.5 | Base weight for MASTERED letters |

## DB Schema Changes

`letter_states` table — two new columns (v6 migration via ALTER TABLE ADD COLUMN):
- `mastery_score REAL NOT NULL DEFAULT 0.0`
- `mastery_qualifying_keystrokes INTEGER NOT NULL DEFAULT 0`

## Files to Change

| File | Change |
|---|---|
| `config.py` | 5 new config fields |
| `letter_state.py` | MASTERED enum value, `mastery_score` + `mastery_qualifying_keystrokes` fields, `_state_bonus()` MASTERED case, `training_weight()` |
| `letter_manager.py` | STABLE → MASTERED transition, MASTERED → DEGRADED, mastery increment in `update_states_after_session()`, mastery decay at session start |
| `spaced_repetition.py` | Mastery decay function (or inline in letter_manager) |
| `database.py` | v6 migration adding two columns |
| `repository.py` | Read/write mastery fields |
| `main_window.py` | Wire mastery decay at session start |
| `letter_overview.py` | Display mastery_score column |
| `theme.py` | COLOR for MASTERED state |
| `SPEC.md` | Document mastery system |
| Tests | New mastery tests + update existing state transition tests |

## Open Questions

- Should the mastery_score be visible in the UI during runs, or only in the letter overview?
- Should the session dashboard show mastery progress (e.g., "h: 124/1500 qualifying keystrokes")?
- Should there be a notification when a letter reaches MASTERED state?
