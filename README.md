# Typing Trainer

A desktop typing trainer built on motor learning principles. No gamification, no badges, no streaks — just systematic training to build correct finger-to-key motor patterns, consolidate them to automaticity, then push for speed.

<!-- TODO: Add screenshot -->

## Philosophy

Speed and accuracy are treated as separate phases. Accuracy is never sacrificed for speed. The tool introduces letters one at a time, enforces accuracy thresholds before progression, and only unlocks speed training once all active letters are consolidated. Speed emerges from correct patterns, not from rushing through errors.

## Features

- **Three training phases**: Relearning (accuracy-first, backspace disabled) → Speed (adaptive WPM staircase) → Transition (bigram-targeted practice)
- **Adaptive letter introduction**: Curated QWERTZ-optimized order, auto-advances when per-letter rolling accuracy reaches 95%
- **Error classification**: Cognitive errors, motor overflow (<80ms same-key), burst repeats (stuck keys), swap detection (transposed pairs)
- **Letter state machine**: Introducing → Consolidating → Stable → Mastered, with automatic degradation on accuracy drops
- **Mastery system**: Long-term motor pattern tracking with Ebbinghaus-curve decay modeling — mastery builds over ~60 sessions of qualifying practice
- **Speed staircase**: +2 WPM on pass, -4 WPM on fail — converges to a 67% success equilibrium
- **Transition training**: Select slow or error-prone bigrams from analytics, practice with contextual interference (target bigrams in real words)
- **Analytics dashboard**: Accuracy trends, WPM history, per-letter breakdown, error type distribution, bigram heatmap, position analysis
- **Spaced repetition**: Time-based decay on unused letters with configurable half-lives
- **QWERTZ layout** with German and English language support (lowercase only in v1)
- **Dark theme**, keyboard-driven UI (Return to continue, Escape to abort)

## Requirements

- Python >= 3.14
- PyQt6 >= 6.7
- pyqtgraph >= 0.13

## Installation

```bash
# Clone the repository
git clone https://github.com/ChristianHonisch/typing-trainer.git
cd typing-trainer

# Install dependencies with uv
uv sync

# Run the application
uv run typing-trainer
```

If you don't have `uv`, install it first:

```bash
pip install uv
```

## Usage

### Getting started

The trainer starts with two letters (`e` and `n` for German). Type the displayed text as accurately as possible. New letters are introduced automatically when:

- Every active letter has >= 95% accuracy over a rolling 200-keystroke window
- At least 500 total keystrokes have been typed since the last introduction

### Training modes

**Relearning** — The default mode. Backspace is disabled to force commitment to each keystroke. Focus entirely on accuracy. Runs fail automatically if accuracy drops below the threshold.

**Speed** — Unlocks when all letters reach Stable state and the last 5 sessions have >= 95% accuracy. An adaptive WPM target increases on success and decreases on failure. Backspace is enabled, but accuracy is still scored on first input per position.

**Transition** — Same entry conditions as Speed. Open the Analysis tab, find slow or error-prone bigrams in the heatmap, select 1-3 targets, and start a transition run. The generated text interleaves words containing target bigrams with normal words.

### Keyboard shortcuts

- **Return/Enter** — Start a run from the config screen, or continue from the summary screen
- **Escape** (double-press) — Abort the current run (discarded, not saved)

## Configuration

Settings are stored in `training-data/config.json`, created automatically on first launch. Key parameters:

| Parameter | Default | Description |
|---|---|---|
| `language` | `"de"` | `"de"` for German, `"en"` for English |
| `advancement_accuracy` | `0.95` | Per-letter accuracy threshold for advancement |
| `advancement_accuracy_window` | `200` | Rolling window size (keystrokes per letter) |
| `advancement_min_keystrokes` | `500` | Minimum keystrokes before next letter introduction |
| `session_timeout_minutes` | `30` | Inactivity timeout for session boundaries |
| `rest_suggestion_seconds` | `30` | Rest countdown between runs |
| `default_run_length` | `50` | Default number of characters per run |

See [SPEC.md](SPEC.md) for the full parameter reference and design rationale.

## Data Storage

All training data is self-contained in the `training-data/` directory:

- `typing_trainer.db` — SQLite database with sessions, runs, keystrokes, letter states, and speed state
- `config.json` — User configuration

The database is portable. Copy the `training-data/` folder to migrate to another machine. Schema migrations run automatically on startup.

## Development

### Project structure

```
src/typing_trainer/
  config.py              # All tunable parameters
  main.py                # Entry point
  models/                # Data structures (letter state, run result, session, error types)
  core/                  # Engine, text generator, letter manager, error classifier, speed manager
  storage/               # SQLite database + repository layer
  ui/                    # PyQt6 widgets, theme, charts
tests/                   # 326 tests
```

### Running tests

```bash
uv run pytest tests/ -q --tb=short
```

### Type checking

```bash
npx pyright src/ tests/
```

The project targets 0 pyright errors. Type stubs for PyQt6 and pyqtgraph are configured via `pyrightconfig.json`.

## License

TBD
