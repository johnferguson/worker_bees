"""Check that the worker_bees folders exist.

Reads top_level_directory and required_folders from
000_worker_bees_queue.toml and checks that every required folder exists
inside the top level directory.

Run it with:  uv run ZZZ_check_folders.py
"""

import sys

from worker_bees_settings import CONFIG_FILE, SettingsError, load_settings


def main():
    try:
        settings = load_settings()
    except SettingsError as error:
        print(error)
        return 1

    if "required_folders" not in settings:
        print(f"required_folders is not set in {CONFIG_FILE.name}")
        return 1

    top_dir = settings["top_dir"]
    print(f"Top level directory: {top_dir}")

    if not top_dir.is_dir():
        print("  MISSING  the top level directory itself")
        return 1

    missing = []
    for name in settings["required_folders"]:
        folder = top_dir / name
        if folder.is_dir():
            print(f"  ok       {folder}")
        else:
            print(f"  MISSING  {folder}")
            missing.append(name)

    if missing:
        print(f"\n{len(missing)} folder(s) missing: {', '.join(missing)}")
        return 1

    print("\nAll folders found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
