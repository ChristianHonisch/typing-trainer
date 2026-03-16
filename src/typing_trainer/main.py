"""Entry point for the typing trainer application."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from typing_trainer.config import Config

# Training data directory — self-contained within the project
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "training-data"
PROFILES_DIR = DATA_DIR / "profiles"
ACTIVE_PROFILE_FILE = DATA_DIR / "active_profile.txt"


def get_profile_dir(profile_name: str) -> Path:
    """Get the directory for a named profile."""
    return PROFILES_DIR / profile_name


def list_profiles() -> list[str]:
    """List all available profile names (sorted)."""
    if not PROFILES_DIR.exists():
        return []
    return sorted(d.name for d in PROFILES_DIR.iterdir() if d.is_dir())


def get_active_profile() -> str:
    """Read the active profile name from disk."""
    if ACTIVE_PROFILE_FILE.exists():
        name = ACTIVE_PROFILE_FILE.read_text(encoding="utf-8").strip()
        if name and (PROFILES_DIR / name).is_dir():
            return name
    # Fall back to first available or "default"
    profiles = list_profiles()
    return profiles[0] if profiles else "default"


def set_active_profile(name: str) -> None:
    """Persist the active profile name."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_PROFILE_FILE.write_text(name, encoding="utf-8")


def delete_profile(name: str) -> None:
    """Delete a profile directory and all its data."""
    profile_dir = get_profile_dir(name)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)


def _migrate_if_needed() -> None:
    """Move existing flat training-data/ layout into profiles/default/.

    Called once on upgrade from the old single-user layout.
    """
    if PROFILES_DIR.exists():
        return  # Already migrated

    old_config = DATA_DIR / "config.json"
    old_db = DATA_DIR / "typing_trainer.db"

    if not old_config.exists() and not old_db.exists():
        return  # Fresh install, nothing to migrate

    default_dir = PROFILES_DIR / "default"
    default_dir.mkdir(parents=True, exist_ok=True)

    if old_config.exists():
        shutil.move(str(old_config), str(default_dir / "config.json"))
    if old_db.exists():
        shutil.move(str(old_db), str(default_dir / "typing_trainer.db"))
    # Move WAL sidecar files
    for wal_file in DATA_DIR.glob("typing_trainer.db-*"):
        shutil.move(str(wal_file), str(default_dir / wal_file.name))
    # Move backup if present
    backup = DATA_DIR / "typing_trainer_backup.db"
    if backup.exists():
        shutil.move(str(backup), str(default_dir / backup.name))

    # Mark the migrated profile's wizard as completed (existing user)
    config_path = default_dir / "config.json"
    config = Config.load(config_path)
    config.wizard_completed = True
    config.db_path = str(default_dir / "typing_trainer.db")
    config.save(config_path)

    set_active_profile("default")


def main() -> None:
    """Launch the typing trainer application."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_if_needed()

    profile_name = get_active_profile()
    profile_dir = get_profile_dir(profile_name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    config_path = profile_dir / "config.json"
    config = Config.load(config_path)
    config.db_path = str(profile_dir / "typing_trainer.db")

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Typing Trainer")
    app.setFont(QFont("Consolas", 11))

    # Show wizard for new / incomplete profiles
    if not config.wizard_completed:
        from typing_trainer.ui.new_user_wizard import NewUserWizard

        wizard = NewUserWizard(profile_name)
        if wizard.exec():
            config.language = wizard.language
            config.wizard_completed = True
            config.save(config_path)
        else:
            # User cancelled — exit
            sys.exit(0)

    # Create and show main window
    from typing_trainer.ui.main_window import MainWindow

    window = MainWindow(config, profile_name, profile_dir)
    window.show()

    exit_code = app.exec()
    config.save(config_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
