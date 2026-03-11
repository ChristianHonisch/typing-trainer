# Future Ideas

Design ideas and features for potential future implementation.

## Weighting System

### Combined share cap for non-stable letters

Cap the **combined** share of all degraded/introducing letters (e.g., max 40% of text). This guarantees stable letters collectively get at least 60% of practice, preventing scenarios where multiple problem letters crowd out normal practice entirely.

### Proportional degraded bonus based on error severity

Make the DEGRADED state bonus proportional to how far the error rate exceeds the degradation threshold, rather than a fixed bonus. A letter barely over the threshold (e.g., 5.1%) would get a smaller bonus than one at 12%. This avoids over-weighting letters that are only marginally degraded.

Formula idea: `degraded_bonus = base_degraded_bonus * min(1.0, (rolling_error_rate - threshold) / threshold)`

## Mastery System

### Long-term mastery score

A second stability dimension (`mastery_score`) that tracks permanent motor pattern encoding, separate from short-term `stability_score`:

- Builds much more slowly: +0.05 per qualifying session, scaled by keystroke volume for the letter (`min(1.0, keystrokes / 100)`)
- Daily cap on mastery gain (e.g., 0.10/day) to prevent grinding in a single sitting
- Requires letter to be in STABLE state and session accuracy >= 95%
- Decays much more slowly: half-life scales with mastery level itself (1 week at mastery=0, 3 months at mastery=1.0)
- Modulates `stability_score` time decay: mastered letters decay stability more slowly
- New MASTERED state when `mastery_score > 0.8`
- ~15-25 days of distributed practice to reach full mastery

### Mastery-gated speed mode

Require minimum mastery (e.g., 0.3) for all letters before entering speed mode. This ensures letters have been practiced across multiple days, not just stabilized in a single session. Concern: could make learning feel very slow if applied too strictly.
