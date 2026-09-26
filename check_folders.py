"""Check that the worker_bees folders exist.

Reads top_level_directory from 000_worker_bees_queue.toml (in the same
folder as this script) and checks that it contains the queue, running,
failed and finished folders.

Run it with:  uv run check_folders.py
"""

import sys
import tomllib
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "000_worker_bees_queue.toml"
FOLDERS = ["queue", "running", "failed", "finished"]


def main():
    if not CONFIG_FILE.exists():
        print(f"Config file not found: {CONFIG_FILE}")
        return 1

    # utf-8-sig copes with the invisible marker Notepad sometimes adds
    try:
        settings = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        print(f"Could not read {CONFIG_FILE}: {error}")
        return 1
    if "top_level_directory" not in settings:
        print(f"top_level_directory is not set in {CONFIG_FILE}")
        return 1

    top_dir = Path(settings["top_level_directory"])
    print(f"Top level directory: {top_dir}")

    if not top_dir.is_dir():
        print("  MISSING  the top level directory itself")
        return 1

    missing = []
    for name in FOLDERS:
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
