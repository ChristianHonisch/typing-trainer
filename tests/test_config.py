"""Tests for configuration loading and saving."""

import json
from pathlib import Path

from typing_trainer.config import Config


class TestConfigDefaults:
    def test_default_values(self):
        config = Config()
        assert config.advancement_accuracy == 0.95
        assert config.advancement_min_keystrokes == 500
        assert config.advancement_accuracy_window == 200
        assert config.fail_threshold_relearning == 0.90
        assert config.fail_threshold_speed == 0.95
        assert config.fail_threshold_introducing_s1 == 0.70
        assert config.fail_threshold_introducing_s2 == 0.80
        assert config.fail_threshold_min_errors == 5
        assert config.motor_overflow_window_ms == 80
        assert config.run_length_default_relearning == 60
        assert config.run_length_default_speed == 100
        assert config.run_length_minimum == 50
        assert config.speed_increment == 2
        assert config.speed_decrement == 4
        assert config.session_timeout_minutes == 30
        assert config.rest_suggestion_seconds == 10
        assert config.degraded_recovery_margin == 0.8
        assert config.max_letter_share == 0.35
        assert config.warmup_keystrokes == 3
        assert config.require_capitalization is True
        assert config.error_handling == "ignore"
        assert config.fail_threshold_enabled is False
        assert config.language == "de"


class TestConfigPersistence:
    def test_save_and_load(self, tmp_path: Path):
        config = Config(language="en", advancement_accuracy=0.90)
        path = tmp_path / "config.json"
        config.save(path)

        loaded = Config.load(path)
        assert loaded.language == "en"
        assert loaded.advancement_accuracy == 0.90
        # Other values should be defaults
        assert loaded.fail_threshold_relearning == 0.90

    def test_load_missing_file_returns_defaults(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        config = Config.load(path)
        assert config.language == "de"
        assert config.advancement_accuracy == 0.95

    def test_load_ignores_unknown_keys(self, tmp_path: Path):
        path = tmp_path / "config.json"
        data = {"language": "en", "unknown_key": "should_be_ignored"}
        with open(path, "w") as f:
            json.dump(data, f)

        config = Config.load(path)
        assert config.language == "en"
        assert not hasattr(config, "unknown_key")

    def test_load_partial_config(self, tmp_path: Path):
        path = tmp_path / "config.json"
        data = {"language": "en"}
        with open(path, "w") as f:
            json.dump(data, f)

        config = Config.load(path)
        assert config.language == "en"
        assert config.advancement_accuracy == 0.95  # default

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "subdir" / "nested" / "config.json"
        config = Config()
        config.save(path)
        assert path.exists()
