"""Settings shared by all the worker_bees scripts.

Every script reads 000_worker_bees_queue.toml through here, so it is read
the same way everywhere.
"""

import os
import tomllib
from pathlib import Path

HERE = Path(__file__).parent  # the worker_bees folder
CONFIG_FILE = HERE / "000_worker_bees_queue.toml"
SCHEDULE_FILE = HERE / "001_worker_bees_crontab.txt"


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


def machine_path(settings, key):
    """Return the path in settings[key], or None if it isn't set.

    On Linux (including WSL) key + '_linux' is used instead when it is set,
    because Windows paths look different there.
    """
    if os.name != "nt" and f"{key}_linux" in settings:
        key = f"{key}_linux"
    if key not in settings:
        return None
    return Path(settings[key])


def load_settings():
    """Return the settings file as a dict, plus two Paths:

    'top_dir'      the top level directory, which holds the queue folders
    'scripts_dir'  where job scripts are looked up (the worker_bees folder
                   if scripts_directory isn't set)
    """
    settings = load_toml(CONFIG_FILE)
    top_dir = machine_path(settings, "top_level_directory")
    if top_dir is None:
        raise SettingsError(f"top_level_directory is not set in {CONFIG_FILE.name}")
    settings["top_dir"] = top_dir
    scripts_dir = machine_path(settings, "scripts_directory")
    # a relative scripts_directory starts from the worker_bees folder
    settings["scripts_dir"] = HERE / scripts_dir if scripts_dir else HERE
    return settings


def folder(settings, key):
    """Return the path of a folder named in the settings, e.g. folder(settings, "queue_folder")."""
    if key not in settings:
        raise SettingsError(f"{key} is not set in {CONFIG_FILE.name}")
    path = settings["top_dir"] / settings[key]
    if not path.is_dir():
        raise SettingsError(f"Folder not found: {path}  (ZZZ_check_folders.py can help)")
    return path
