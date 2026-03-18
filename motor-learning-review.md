# Motor Learning Review

Date: 2026-03-15

Deep review of the typing trainer from a motor learning science perspective.

## What the System Gets Right

The overall design is strongly aligned with motor learning science. Standout decisions:

1. **Backspace-disabled in relearning** — forces error processing, prevents correction-chaining motor patterns
2. **First-input-only scoring** — measures feedforward motor program quality, not correction ability
3. **Motor overflow / burst repeat exclusion** — cleanly separates execution noise from cognitive errors
4. **Need-based text weighting** with 35% share cap — implements interleaved practice with contextual interference
5. **Tiered fail thresholds** (70%→80%→90%→95%) — aligned with challenge point framework
6. **Transparent advancement criteria** — specific, actionable feedback about what needs improvement
7. **Degradation → Consolidating (not → Stable)** — recovered letters must re-prove themselves
8. **Error sub-categorization** (spatial/same-finger/mirror) — diagnostic value for self-directed learners
9. **Speed staircase** converging at 67% success — within the 60-80% optimal challenge range

---

## Issues Worth Addressing

### High Priority (affect learning quality)

#### 1. Learn Keys defaults to 120 keystrokes — contradicts fatigue evidence

`run_config_widget.py:68` sets Learn Keys to 120, but `config.py:51-58` documents that fatigue sets in around position 50, with the default at 60. Random strings are the most cognitively demanding practice type. 120 keystrokes means ~60 keystrokes under fatigue, where errors get "baked in" to motor patterns — exactly what the system is designed to prevent.

**Recommendation:** Default Learn Keys to 60 (or at most 80).

#### 2. Mastery is reached too quickly

Already noted as a TODO. With common letters getting ~100 keystrokes/session, mastery threshold (0.8) is reached in ~12 sessions (~2 weeks). Motor automaticity research (Driskell et al., 1992) suggests months of distributed practice for deep encoding.

**Recommendation:** Require sustained stability duration (e.g., STABLE for ≥14 days) AND keystroke volume, not just volume alone.

#### 3. No within-session fatigue management

No max session duration, no escalating rest intervals, no adaptive run length. The system allows unlimited massed practice, which contradicts the distributed practice research it cites. Practicing under mental fatigue reinforces errors.

**Recommendation:** At minimum, suggest longer breaks after N consecutive runs. Better: increase rest suggestion duration as the session progresses (e.g., 10s → 15s → 20s).

#### 4. Spaced repetition half-lives are too short for motor skills

24 hours for consolidating, 72 hours for stable. Motor skill retention is far more durable than declarative memory — procedural memory persists for weeks without practice (Arthur et al., 1998). A 24h half-life means skipping one day flags letters for review. This creates false urgency and could be demoralizing.

**Recommendation:** 48–72h for consolidating, 168h (1 week) for stable. Mastery decay (14–90 days) is more reasonable.

#### 5. Random strings are used throughout all of relearning, even after 20+ letters

Random strings force explicit key lookup during the cognitive stage — correct for early learning. But once 15+ letters are active, the user is well past the cognitive stage for the early letters. Random strings at that point provide poor transfer to real typing (specificity of practice, Proteau 1992). Speed comes from motor program chaining in linguistic contexts, not from character-by-character visual search.

**Recommendation:** Consider auto-transitioning from random strings to random words (or a mix) once the majority of letters are stable. Or: let Learn Keys use random words for stable/mastered letters while keeping random strings only for introducing/consolidating letters.

### Medium Priority (affect user experience and suboptimal learning)

#### 6. Run-over-run delta uses red/green coloring

`run_summary_widget.py:375-376` colors accuracy/WPM changes vs. previous run. Normal run-to-run variation is 5-15% even for skilled typists. Red "-3.2%" on a normal fluctuation induces performance anxiety and outcome focus instead of process focus (Wulf & Lewthwaite, 2016).

**Recommendation:** Compare against a rolling average rather than single previous run, or show delta without color coding.

#### 7. Error sub-categorization hidden from beginners (Basic mode)

`run_summary_widget.py:232` hides per-letter breakdown in Basic mode. But beginners in the cognitive stage benefit most from diagnostic feedback about error types (spatial vs same-finger vs mirror). Hiding this information to "reduce complexity" may actually slow learning.

**Recommendation:** Show a simplified error summary even in Basic mode — e.g., "3 spatial errors, 1 mirror error" without the full per-letter table.

#### 8. Speed diagnostics don't feed back into text generation

Per-key reaction times are computed and displayed but don't influence practice allocation. A letter that is accurate but slow gets no extra practice in normal mode. Speed bottlenecks need targeted practice.

**Recommendation:** Add an optional RT-based weight component (e.g., letters with mean RT > 1.5× median get a small weight bonus).

#### 9. No expanding review intervals

Classic spaced repetition increases intervals after each successful recall (1 day → 3 → 7 → 21 days). This system has only two fixed half-lives. A letter stable for 50 sessions decays at the same rate as one just promoted to stable.

**Recommendation:** Scale stability half-life with `sessions_in_current_state` or `mastery_score`.

#### 10. Transition training entry conditions are too strict

Requiring ALL letters stable + 5 sessions at 95% locks out bigram training until very late. Bigram-level problems (e.g., "th" being consistently slow) are visible from early training but not actionable until the user clears a high global bar.

**Recommendation:** Consider allowing limited transition practice earlier, perhaps gated per-bigram (both letters must be stable) rather than requiring the entire alphabet to be stable.

### Low Priority (polish and edge cases)

11. **Warmup of 3 keystrokes is shorter than cited evidence** — data shows elevated error through position 4. Bump to 5.
12. **80ms motor overflow threshold is static** — calibration infrastructure (SameKeyInterval logging) exists but is unused. Could auto-calibrate per-user.
13. **No indication of expected character at error positions** — learner sees red "d" but must remember it should have been "f". A subtle annotation would close this feedback loop.
14. **"Need N keystrokes" exactness could create perfectionism pressure** — consider softer framing like "approaching threshold."
15. **No session volume guidance** — learner has no idea if 500 keystrokes/session is good. A simple recommendation would help.
16. **500ms burst interval is very generous** — tightening to 200-300ms would better match true "stuck key" behavior.

---

## What's Missing (design-level gaps)

These are features that motor learning research supports but the system doesn't implement:

1. **No rhythm/consistency metric** — IKI variability (coefficient of variation) is a key indicator of motor automaticity. The system tracks mean RT but not consistency.

2. **No proactive interference management** — when a new letter is introduced, nearby letters (same finger, adjacent) should get a weight boost to prevent regression. Currently, interference is only detected retroactively via degradation.

3. **No power law of practice modeling** — the system uses linear/discrete state transitions. No learning curve visualization showing diminishing returns or plateaus, which is critical for motivation and self-regulation.

4. **No feedback fading** — the same level of concurrent feedback (accuracy %, colored characters) is provided at all skill levels. Motor learning research suggests fading feedback over time builds stronger internal representations.

5. **No sleep/consolidation awareness** — motor skills consolidate during sleep (Walker et al., 2002). The system treats a 12-hour daytime gap identically to a 12-hour overnight gap.

---

## Detailed Analysis by Module

### Engine (`core/engine.py`)

**First-input-only scoring (lines 222-237):** Excellent. Captures the quality of the feedforward motor command, not the feedback correction loop.

**Warmup exclusion (line 224, config line 83-90):** 3 keystrokes is likely too few — cited data shows elevated error through position 4. A warmup of 5 would align with the cited evidence.

**Motor overflow exclusion from accuracy (lines 186-199):** Strong design choice. Separates motor execution noise from cognitive-spatial mapping error — precisely the distinction motor learning researchers make.

**Fail threshold with minimum errors (lines 262-268):** Requiring 5 errors minimum before aborting is sensible but doesn't scale with run length — on a 50-keystroke run, 5 errors is already 10%, meaning the fail threshold (90%) can only trigger near the very end.

### Error Classifier (`core/error_classifier.py`)

**80ms motor overflow window:** Partially grounded. Keyboard debounce literature and typing research (Salthouse, 1986; Logan & Crump, 2011) establish that unintentional double-taps typically occur under 50ms. 80ms is reasonable but sits in a gray zone. The code wisely exempts legitimate double-letters (line 113-115) — critical and well-implemented.

**Burst repeat detection (lines 181-246):** Novel and useful heuristic. The 500ms `burst_max_interval_ms` is generous — a half-second gap between same-key presses is long enough to be deliberate. Consider tightening to 200-300ms.

**Swap detection (lines 152-163):** Transposition errors are tracked diagnostically but still counted as cognitive errors. Defensible for learners building spatial maps, but for advanced users swaps reflect timing/coordination issues more than knowledge deficits.

### Text Generator (`core/text_generator.py`)

**Need-based weighting (`_compute_weights`, lines 273-309):** Allocates practice purely on training need — state bonus + accuracy gap + volume deficit. Well-supported adaptive practice allocation.

**Share cap (`_apply_share_cap`, lines 311-372):** 35% limit with waterfilling redistribution. The docstring explicitly cites the interleaved vs massed practice literature. Solid implementation of contextual interference.

**Anti-repetition constraints (lines 78-88):** Global no-repeat + per-hand no-repeat forces distributed practice at the character level. Consistent with contextual interference principle.

**Random strings break ecological validity (lines 67-189):** `_generate_random_strings` produces sequences with no linguistic structure. While justified during early cognitive stage (forcing explicit key lookup), motor learning research on specificity of practice (Proteau, 1992) shows that practice under conditions dissimilar to the target task transfers poorly. The system allows random_strings throughout all of relearning, even after 20+ letters are active.

**No bigram-level awareness outside transition mode:** In `_generate_random_words`, words are weighted only by their max letter weight. No consideration of which letter *transitions* appear in the word.

### Letter Manager (`core/letter_manager.py`)

**Gradual introduction (part-whole practice):** Starts with 2 letters, adds one at a time. Classic part-practice aligned with cognitive load theory.

**Accuracy-gated progression:** Requires ALL active letters to meet accuracy criteria before introducing a new one. The triple gate (per-letter accuracy + data sufficiency + volume threshold) is unusually rigorous.

**Degradation detection and recovery:** Recovery must go through consolidation (not directly back to stable). Structural guard against premature promotion.

**Asymmetric stability updates (lines 306-309):** +0.2 for good, -0.1 for bad. Building stability requires more sustained evidence than losing it — aligned with empirical finding that motor pattern encoding is slow but degradation can be fast.

**No interaction between letters during state transitions:** Each letter's state is computed independently. Motor interference between physically adjacent letters is real but not proactively managed — only detected retroactively via degradation.

**Session-level state updates ignore run granularity:** If a session contains 10 runs where the first 5 are bad and the last 5 are great, the per-letter error rate is averaged across the whole session. This masks within-session learning.

### Spaced Repetition (`core/spaced_repetition.py`)

**Ebbinghaus forgetting curve:** Standard exponential decay model. Motor skills decay more slowly than declarative memory, and the half-lives (24h consolidating, 72h stable) are too aggressive for motor skills (see high-priority issue #4).

**State-dependent decay rates:** Consolidating letters decay faster than stable letters. Models the empirical finding that newly learned motor patterns are more fragile.

**No expanding review intervals:** Classic spaced repetition increases intervals after each success. This system has only two fixed half-lives — a letter stable for 50 sessions decays at the same rate as one just promoted.

### Speed Manager (`core/speed_manager.py`)

**Staircase method:** +2 WPM on success, -4 WPM on failure converges on 67% success. Well within the 60-80% optimal challenge range.

**Fixed step sizes ignore power law of practice:** At 30 WPM, +2 is a 6.7% increase; at 80 WPM, +2 is 2.5%. The absolute step size should scale with current target.

**Speed diagnostics don't feed back into text generation:** Per-key reaction times are computed and displayed but don't influence practice allocation.

**No rhythm/consistency metric:** WPM is an average over the whole run. Doesn't capture typing rhythm (coefficient of variation of IKI). Consistent rhythm is a key indicator of motor automaticity.

### Typing Widget (`ui/typing_widget.py`)

**Backspace-disabled in relearning:** The most consequential motor learning design decision, well-justified:
- Forces error acknowledgment over error erasure
- Prevents error chaining (backspace-and-retype creates a competing motor sequence)
- Maintains forward momentum in sequential motor planning
- Honest measurement (first-input-only scoring makes backspace pointless anyway)

**Error display showing the wrong character:** If the target was "f" and you typed "d", you see a red "d". Correct for motor learning — highlights the specific incorrect key-to-position mapping. However, there's no indication of what the correct character was after you move past it.

**Weak letter highlighting (lines 265-267):** Pale yellow for weak upcoming letters is a gentle attentional cue — feedforward cueing without changing the task structure. Aligned with attention allocation theories (Wulf, 2007).

**Real-time accuracy display:** Concurrent feedback is defensible for a complex task in the cognitive stage where the learner cannot self-detect errors. The color coding may cause self-monitoring pressure ("choking").

### Run Summary (`ui/run_summary_widget.py`)

**Error sub-categorization (spatial/same-finger/mirror/other):** Excellent for motor learning — tells the learner what kind of motor program error they're making. However, hidden in Basic mode where beginners need it most.

**Run-over-run delta with color coding:** Green/red signaling after every run creates an implicit performance outcome focus rather than process focus. Normal variation is 5-15% — red "-3.2%" may catastrophize noise.

### Session Dashboard (`ui/session_dashboard.py`)

**Transparent goal-setting:** The learner knows exactly what's required for advancement, can see progress, gets specific blocker information. Strongly supported by motor learning research (Locke & Latham, 2002).

**"Need N keystrokes" computation:** Specific and actionable, but the exactness could create perfectionism pressure — if a learner knows they need 14 perfect keystrokes and makes an error at keystroke 12, the psychological reset is demotivating.

### Training Weight System (`models/letter_state.py`)

**Weight formula:** `base + state_bonus + accuracy_gap_bonus + volume_deficit_bonus`

Well-tuned need-based allocation:
- New letter gets ~6× the representation of a mastered letter
- Accuracy gap bonus creates proportional remediation
- Volume deficit bonus with cosine fade prevents abrupt frequency changes
- `recently_stable` bonus (linear decay over 10 sessions) provides continued practice after criterion

**Critique:** The `recently_stable` bonus decays linearly, but motor learning consolidation follows a power law (Newell & Rosenbloom, 1981). An exponential decay would better match. Practical impact over 10 sessions is likely small.

---

## References

- Arthur, W., et al. (1998). Factors that influence skill decay and retention: A quantitative review and analysis. *Human Performance*, 11(1), 57–101.
- Bönstrup, M., et al. (2019). A rapid form of offline consolidation in skill learning. *Current Biology*, 29(8), 1346–1351.
- Cepeda, N. J., et al. (2006). Distributed practice in verbal recall tasks. *Review of Educational Research*, 76(3), 354–380.
- Driskell, J. E., et al. (1992). Effect of overlearning on retention. *Journal of Applied Psychology*, 77(5), 615–622.
- Fischer, S., et al. (2002). Sleep forms memory for finger skills. *Proceedings of the National Academy of Sciences*, 99(18), 11987–11991.
- Fitts, P. M. (1954). The information capacity of the human motor system in controlling the amplitude of movement. *Journal of Experimental Psychology*, 47(6), 381–391.
- Grudin, J. T. (1983). Error patterns in novice and skilled transcription typing. *Cognitive Aspects of Skilled Typewriting*, 121–143.
- Lee, T. D., & Genovese, E. D. (1988). Distribution of practice in motor skill acquisition: Learning and performance effects reconsidered. *Research Quarterly for Exercise and Sport*, 59(4), 277–287.
- Locke, E. A., & Latham, G. P. (2002). Building a practically useful theory of goal setting and task motivation. *American Psychologist*, 57(9), 705–717.
- Logan, G. D., & Crump, M. J. (2011). Hierarchical control of cognitive processes: The case for skilled typewriting. *Psychology of Learning and Motivation*, 54, 1–27.
- Newell, A., & Rosenbloom, P. S. (1981). Mechanisms of skill acquisition and the law of practice. *Cognitive Skills and Their Acquisition*, 1(1981), 1–55.
- Proteau, L. (1992). On the specificity of learning and the role of visual information for movement control. *Advances in Psychology*, 85, 67–103.
- Rumelhart, D. E., & Norman, D. A. (1982). Simulating a skilled typist: A study of skilled cognitive-motor performance. *Cognitive Science*, 6(1), 1–36.
- Salthouse, T. A. (1986). Perceptual, cognitive, and motoric aspects of transcription typing. *Psychological Bulletin*, 99(3), 303–319.
- Salmoni, A. W., et al. (1984). Knowledge of results and motor learning: A review and critical reappraisal. *Psychological Bulletin*, 95(3), 355–386.
- Shea, J. B., & Morgan, R. L. (1979). Contextual interference effects on the acquisition, retention, and transfer of a motor skill. *Journal of Experimental Psychology: Human Learning and Memory*, 5(2), 179–187.
- Walker, M. P., et al. (2002). Practice with sleep makes perfect: Sleep-dependent motor skill learning. *Neuron*, 35(1), 205–211.
- Wulf, G. (2007). *Attention and Motor Skill Learning*. Human Kinetics.
- Wulf, G., & Lewthwaite, R. (2016). Optimizing performance through intrinsic motivation and attention for learning: The OPTIMAL theory of motor learning. *Psychonomic Bulletin & Review*, 23(5), 1382–1414.
