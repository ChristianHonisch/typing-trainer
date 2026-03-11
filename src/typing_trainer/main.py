"""Entry point for the typing trainer application."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from typing_trainer.config import Config
from typing_trainer.ui.main_window import MainWindow

# Training data directory — self-contained within the project
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "training-data"
CONFIG_PATH = DATA_DIR / "config.json"


def main() -> None:
    """Launch the typing trainer application."""
    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load or create config (set db_path to data dir if still default)
    config = Config.load(CONFIG_PATH)
    if config.db_path == "typing_trainer.db":
        config.db_path = str(DATA_DIR / "typing_trainer.db")

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Typing Trainer")

    # Set default font
    from PyQt6.QtGui import QFont

    app.setFont(QFont("Consolas", 11))

    # Create and show main window
    window = MainWindow(config)
    window.show()

    # Save config on exit
    exit_code = app.exec()
    config.save(CONFIG_PATH)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
