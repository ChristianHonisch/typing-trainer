"""Speed training management.

Tracks WPM targets and adjusts them based on run outcomes.
Checks entry conditions for speed mode.
Computes per-key reaction time diagnostics.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from typing_trainer.config import Config
from typing_trainer.models.letter_state import LetterState, LetterStats
from typing_trainer.models.run_result import RunResult
from typing_trainer.models.session import Session


@dataclass
class SpeedEntryCheck:
    """Result of checking whether speed training is available."""

    available: bool = False
    reasons: list[str] = field(default_factory=list)
    all_stable: bool = False
    qualifying_sessions: int = 0
    sessions_needed: int = 5


@dataclass
class KeySpeedDiagnostic:
    """Per-key speed analysis from a run."""

    letter: str
    mean_rt_ms: float
    is_bottleneck: bool = False
    """True if mean RT > 1.5x the run median."""


@dataclass
class SpeedRunResult:
    """Speed-specific analysis of a run."""

    target_wpm: float
    achieved_wpm: float
    accuracy: float
    passed: bool
    new_target_wpm: float
    per_key_diagnostics: list[KeySpeedDiagnostic] = field(default_factory=list)
    run_median_rt_ms: float = 0.0


class SpeedManager:
    """Manages speed training progression."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.target_wpm: float = 30.0
        self.best_wpm: float = 0.0

    def check_entry_conditions(
        self,
        active_letters: dict[str, LetterStats],
        recent_sessions: list[Session],
    ) -> SpeedEntryCheck:
        """Check whether speed training is available.

        Conditions:
        1. All active letters are in 'stable' state
        2. Full letter set accuracy >= 95% across last 5 sessions
        """
        check = SpeedEntryCheck(sessions_needed=5)

        # Check all stable
        if not active_letters:
            check.reasons.append("No active letters.")
            return check

        all_stable = all(
            s.state == LetterState.STABLE for s in active_letters.values()
        )
        check.all_stable = all_stable
        if not all_stable:
            non_stable = [
                f"'{s.letter}' ({s.state.value})"
                for s in active_letters.values()
                if s.state != LetterState.STABLE
            ]
            check.reasons.append(
                f"Letters not stable: {', '.join(non_stable)}"
            )

        # Check 5 consecutive sessions at 95%+
        qualifying = 0
        for session in recent_sessions[:5]:
            if session.aggregate_accuracy >= self.config.advancement_accuracy:
                qualifying += 1
            else:
                break
        check.qualifying_sessions = qualifying

        if qualifying < 5:
            check.reasons.append(
                f"Need 5 consecutive sessions at {self.config.advancement_accuracy:.0%}+ accuracy, "
                f"have {qualifying}."
            )

        check.available = all_stable and qualifying >= 5
        return check

    def process_speed_run(self, result: RunResult) -> SpeedRunResult:
        """Analyze a speed run and adjust WPM target.

        Args:
            result: The completed run result.

        Returns:
            SpeedRunResult with analysis and new target.
        """
        passed = (
            result.accuracy >= self.config.fail_threshold_speed
            and not result.failed
            and result.completed
        )

        # Adjust target
        if passed:
            new_target = self.target_wpm + self.config.speed_increment
        else:
            new_target = max(10.0, self.target_wpm - self.config.speed_decrement)

        # Per-key reaction time diagnostics
        diagnostics, median_rt = self._compute_diagnostics(result)

        # Update best WPM
        if passed and result.wpm > self.best_wpm:
            self.best_wpm = result.wpm

        speed_result = SpeedRunResult(
            target_wpm=self.target_wpm,
            achieved_wpm=result.wpm,
            accuracy=result.accuracy,
            passed=passed,
            new_target_wpm=new_target,
            per_key_diagnostics=diagnostics,
            run_median_rt_ms=median_rt,
        )

        self.target_wpm = new_target
        return speed_result

    def _compute_diagnostics(
        self, result: RunResult
    ) -> tuple[list[KeySpeedDiagnostic], float]:
        """Compute per-key reaction time diagnostics.

        Returns:
            Tuple of (diagnostics_list, run_median_rt_ms).
        """
        # Collect all reaction times for the median
        all_rts: list[float] = []
        for stats in result.per_letter.values():
            all_rts.extend(stats.reaction_times)

        if not all_rts:
            return [], 0.0

        median_rt = statistics.median(all_rts)
        bottleneck_threshold = median_rt * 1.5

        diagnostics: list[KeySpeedDiagnostic] = []
        for letter in sorted(result.per_letter.keys()):
            stats = result.per_letter[letter]
            if stats.mean_reaction_time_ms is not None:
                diagnostics.append(
                    KeySpeedDiagnostic(
                        letter=letter,
                        mean_rt_ms=stats.mean_reaction_time_ms,
                        is_bottleneck=stats.mean_reaction_time_ms > bottleneck_threshold,
                    )
                )

        # Sort by mean RT descending (slowest first)
        diagnostics.sort(key=lambda d: d.mean_rt_ms, reverse=True)
        return diagnostics, median_rt
