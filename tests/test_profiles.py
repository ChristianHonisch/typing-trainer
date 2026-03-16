"""Tests for profile management functions in main.py."""

from __future__ import annotations

import json
from pathlib import Path

from typing_trainer.main import (
    ACTIVE_PROFILE_FILE,
    DATA_DIR,
    PROFILES_DIR,
    _migrate_if_needed,
    delete_profile,
    get_active_profile,
    get_profile_dir,
    list_profiles,
    set_active_profile,
)


class TestProfileHelpers:
    """Tests for profile directory and listing helpers."""

    def test_get_profile_dir(self):
        result = get_profile_dir("alice")
        assert result == PROFILES_DIR / "alice"

    def test_list_profiles_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", tmp_path / "profiles")
        assert list_profiles() == []

    def test_list_profiles(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", profiles_dir)
        (profiles_dir / "bob").mkdir(parents=True)
        (profiles_dir / "alice").mkdir(parents=True)
        assert list_profiles() == ["alice", "bob"]  # sorted

    def test_get_active_profile_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "typing_trainer.main.ACTIVE_PROFILE_FILE", tmp_path / "active.txt"
        )
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", tmp_path / "profiles")
        assert get_active_profile() == "default"

    def test_get_active_profile_reads_file(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        (profiles_dir / "alice").mkdir(parents=True)
        active_file = tmp_path / "active.txt"
        active_file.write_text("alice", encoding="utf-8")
        monkeypatch.setattr("typing_trainer.main.ACTIVE_PROFILE_FILE", active_file)
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", profiles_dir)
        assert get_active_profile() == "alice"

    def test_set_active_profile(self, tmp_path, monkeypatch):
        monkeypatch.setattr("typing_trainer.main.DATA_DIR", tmp_path)
        monkeypatch.setattr(
            "typing_trainer.main.ACTIVE_PROFILE_FILE", tmp_path / "active.txt"
        )
        set_active_profile("bob")
        assert (tmp_path / "active.txt").read_text(encoding="utf-8") == "bob"

    def test_delete_profile(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        bob_dir = profiles_dir / "bob"
        bob_dir.mkdir(parents=True)
        (bob_dir / "config.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", profiles_dir)
        delete_profile("bob")
        assert not bob_dir.exists()


class TestMigration:
    """Tests for _migrate_if_needed() — old layout to profiles/."""

    def test_migration_creates_default_profile(self, tmp_path, monkeypatch):
        # Set up old-style layout
        monkeypatch.setattr("typing_trainer.main.DATA_DIR", tmp_path)
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr(
            "typing_trainer.main.ACTIVE_PROFILE_FILE", tmp_path / "active.txt"
        )

        old_config = tmp_path / "config.json"
        old_config.write_text('{"language": "en"}', encoding="utf-8")
        old_db = tmp_path / "typing_trainer.db"
        old_db.write_text("fake-db", encoding="utf-8")

        _migrate_if_needed()

        default_dir = tmp_path / "profiles" / "default"
        assert default_dir.exists()
        assert (default_dir / "typing_trainer.db").exists()
        assert (default_dir / "config.json").exists()
        assert not old_config.exists()  # moved
        assert not old_db.exists()  # moved

        # Config should have wizard_completed = True
        migrated_config = json.loads(
            (default_dir / "config.json").read_text(encoding="utf-8")
        )
        assert migrated_config["wizard_completed"] is True

    def test_migration_skips_if_profiles_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr("typing_trainer.main.DATA_DIR", tmp_path)
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", profiles_dir)

        old_config = tmp_path / "config.json"
        old_config.write_text('{"language": "en"}', encoding="utf-8")

        _migrate_if_needed()

        # Old config should still be there (not migrated)
        assert old_config.exists()

    def test_migration_noop_on_fresh_install(self, tmp_path, monkeypatch):
        monkeypatch.setattr("typing_trainer.main.DATA_DIR", tmp_path)
        monkeypatch.setattr("typing_trainer.main.PROFILES_DIR", tmp_path / "profiles")

        _migrate_if_needed()

        # Nothing created
        assert not (tmp_path / "profiles").exists()
