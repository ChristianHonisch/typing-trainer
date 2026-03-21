# AGENTS.md — Coding Agent Instructions

## Project Overview

Desktop typing trainer built on motor learning principles.
Tech stack: Python 3.14+, PyQt6, pyqtgraph, SQLite. Managed with `uv`.

```
src/typing_trainer/
  main.py              # Entry point, profile management
  config.py            # All tunable parameters (dataclass)
  core/                # Engine, text generator, letter manager, error classifier
  models/              # Data structures (letter state, run result, keyboard layout)
  storage/             # SQLite database + repository layer
  ui/                  # PyQt6 widgets, theme, charts/
data/                  # Keyboard layouts (JSON), word corpora
training-data/         # Per-user profiles (config.json + DB each)
```

Authoritative specification: `SPEC.md` (600+ lines).
Review documents: `review-findings.md`, `motor-learning-review.md`, `ui-ux-review.md`.

## Build, Run, Test Commands

```bash
# Install dependencies
uv sync

# Run the application
uv run typing-trainer

# Run ALL tests (must pass before any change is complete)
.venv/Scripts/python.exe -m pytest tests/ -q --tb=short

# Run a single test file
.venv/Scripts/python.exe -m pytest tests/test_repository.py -q --tb=short

# Run a single test class
.venv/Scripts/python.exe -m pytest tests/test_repository.py::TestLastNFilter -q --tb=short

# Run a single test method
.venv/Scripts/python.exe -m pytest tests/test_repository.py::TestLastNFilter::test_swap_pairs_last_n -q --tb=short

# Type checking (must show 0 errors)
npx pyright src/ tests/
```

**Both pyright and pytest must pass with 0 errors after every change.**

## LSP False Positives

Claude Code's built-in LSP does NOT read `pyrightconfig.json`. You will see
false errors for unresolved imports: `PyQt6`, `pyqtgraph`, `typing_trainer.*`.
**Ignore these.** Only `npx pyright src/ tests/` is authoritative.

## Code Style

### Imports

- `from __future__ import annotations` as the first import in ALL source files.
- PEP 8 grouping: `__future__` → stdlib → third-party → local, separated by blank lines.
- Alphabetical within each group.

### Naming

- `snake_case` for variables, functions, methods, module-level non-constants.
- `PascalCase` for classes.
- `UPPER_CASE` for module-level constants.
- Private members prefixed with `_`.

### Type Annotations

- Full annotations on all function signatures and dataclass fields.
- `# type: ignore[specific-code]` only — never bare `# type: ignore`.
- Type ignores are confined to the UI layer (PyQt6 stub limitations).
- Use `if x is None: raise RuntimeError(...)` — never `assert` for runtime checks.

### Docstrings

- Every module, class, and public method has a docstring.
- Dataclass fields use attribute docstrings (string literal after the field).
- reStructuredText-style inline code with double backticks.

### Formatting

- No linter/formatter is configured. Follow existing patterns.
- Two blank lines between top-level definitions.
- Section comments: `# --- Section Name ---` within classes.
- Colors defined in `ui/theme.py` — never hardcode hex in other files.

## Architecture

### Data Flow

`main.py` loads profile → creates `Config` + `Database` → passes to `MainWindow`.
`MainWindow` owns all core objects: `TypingEngine`, `TextGenerator`, `LetterManager`,
`SpacedRepetition`, `SpeedManager`, `Repository`.

### Keyboard Layout

Layouts are JSON files in `data/keyboards/`. Loaded via `load_keyboard(name)` →
`KeyboardLayout` dataclass with derived geometry (adjacency, row/column/finger maps).
Injected into `TextGenerator`, `LetterManager`, and chart widgets that classify errors.

### Config & Profiles

`Config` is a `@dataclass` with `save(path)` / `load(path)` methods (JSON).
Per-profile: `training-data/profiles/<name>/config.json` + `typing_trainer.db`.
Active profile tracked in `training-data/active_profile.txt`.

### Database

`Database` wraps SQLite. Schema version in `SCHEMA_VERSION` constant.
Migrations run automatically in `Database.initialize()`.
`Repository` provides all query methods — no raw SQL outside this class.

### Error Classification

`classify_error(expected, actual, layout)` returns one of 5 categories
with this priority: `mirror > same_column > same_finger > same_row > other`.
Categories are defined by the keyboard layout JSON (mirror pairs, columns, fingers, rows).

### Chart Pattern

All charts follow the same structure:
1. `__init__` calls `_setup_ui()` — creates plot widget + empty state label.
2. `refresh(repo)` — fetches data, shows empty label if none, calls `_redraw()`.
3. Empty state: `self._empty_label.setVisible(True)` + `self._plot.setVisible(False)`.
4. Charts that classify errors receive `KeyboardLayout` via constructor.

### Display Modes

Three levels: `Basic` (training only), `Nerd` (+ sidebar, core analytics),
`Extreme Nerd` (+ deep analysis charts, intra-run speed). Controlled by
`set_display_mode(mode)` methods on widgets.

## Key Domain Rules

- **Backspace disabled in relearning mode** — by design, not a bug.
- **Only Learn Keys runs** (`mode='relearning' AND practice_type='random_strings'`)
  count toward letter unlocking (accuracy AND keystroke volume).
- `datetime.now()` is timezone-naive — accepted for v1.
- Stored timestamps are local time. SQL queries use `date(start_time)` (no
  `'localtime'` modifier on stored values) vs `date('now', 'localtime')`.
- The `KeyboardLayout` object is the single source of truth for physical
  key positions, finger assignments, and mirror pairs.

## Testing

- 410+ tests in `tests/`, covering `core/`, `models/`, `storage/`. No UI tests.
- Use `tmp_path` fixture for isolated DB instances in repository tests.
- Use `monkeypatch` for path overrides (profile/migration tests).
- Test helpers are defined per-class (acknowledged duplication in test_repository.py).
- Empty test methods (`pass` only) should not exist — remove or implement.

## Data Files

| Path | Description |
|------|-------------|
| `data/keyboards/*.json` | Keyboard layout definitions (QWERTZ, future QWERTY) |
| `data/corpus_de.txt` | German word corpus (~800 words) |
| `data/corpus_en.txt` | English word corpus (~950 words) |
| `training-data/profiles/<name>/` | Per-user: `config.json` + `typing_trainer.db` |
| `training-data/active_profile.txt` | Name of the active profile |

## Common Pitfalls

1. **pyqtgraph dual Y-axis**: Requires separate `ViewBox`, manual geometry sync
   via `sigResized`, and range sync via `sigRangeChanged`. Use `if x is None: return`
   guards (not `assert`).
2. **`stepMode` in pyqtgraph**: Use `stepMode="right"` for staircase lines where
   the value applies until the next data point.
3. **SQLite `julianday` arithmetic**: Can lose sub-second precision. Use `±1s`
   tolerance in time-based test assertions.
4. **Qt wheel events on spinboxes**: Override with
   `spin.wheelEvent = lambda e: e.ignore()  # type: ignore[assignment]`
   to prevent accidental value changes when scrolling the page.
5. **Profile switching**: Must end session, save config, close DB, reload all
   core objects, refresh all UI. See `MainWindow._on_profile_switch()`.
