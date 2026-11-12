"""Settings shared by all the worker_bees scripts.

Every script reads 000_worker_bees_queue.toml through here, so it is read
the same way everywhere.
"""

import os
import tomllib
from pathlib import Path

HERE = Path(__file__).parent  # the worker_bees folder
CONFIG_FILE = HERE / "000_worker_bees_queue.toml"
SCHEDULE_FILE = HERE / "001_worker_bees_schedule.toml"


class SettingsError(Exception):
    """A problem in a settings file that someone needs to fix."""


def load_toml(path):
    if not path.exists():
        raise SettingsError(f"File not found: {path}")
    try:
        # utf-8-sig copes with the invisible marker Notepad sometimes adds
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(f"Could not read {path.name}: {error}")


def load_settings():
    """Return the settings file as a dict, plus 'top_dir': the top level directory as a Path.

    On Linux (including WSL) top_level_directory_linux is used instead of
    top_level_directory when it is set.
    """
    settings = load_toml(CONFIG_FILE)
    key = "top_level_directory"
    if os.name != "nt" and "top_level_directory_linux" in settings:
        key = "top_level_directory_linux"
    if key not in settings:
        raise SettingsError(f"{key} is not set in {CONFIG_FILE.name}")
    settings["top_dir"] = Path(settings[key])
    return settings


def folder(settings, key):
    """Return the path of a folder named in the settings, e.g. folder(settings, "queue_folder")."""
    if key not in settings:
        raise SettingsError(f"{key} is not set in {CONFIG_FILE.name}")
    path = settings["top_dir"] / settings[key]
    if not path.is_dir():
        raise SettingsError(f"Folder not found: {path}  (ZZZ_check_folders.py can help)")
    return path
