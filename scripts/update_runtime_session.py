#!/usr/bin/env python3
"""
Update runtime_session.json from Stormgate game directory.

This script finds the most recent runtime_session.json from the Stormgate
installation and copies it to the assets directory.

The file is located at:
%LOCALAPPDATA%/Stormgate/Saved/Maps/Build/Shipping/<uuid>/_runtime/runtime_session.json

Where <uuid> is a directory that changes with game updates.
"""

import os
import shutil
import sys
from pathlib import Path


def get_stormgate_runtime_path() -> Path | None:
    """Find the most recent runtime_session.json in Stormgate installation."""
    # Get LocalAppData path
    local_appdata = os.environ.get('LOCALAPPDATA')
    if not local_appdata:
        print("Error: LOCALAPPDATA environment variable not found")
        return None

    # Path to Stormgate Shipping directory
    shipping_dir = Path(local_appdata) / "Stormgate" / "Saved" / "Maps" / "Build" / "Shipping"

    if not shipping_dir.exists():
        print(f"Error: Stormgate directory not found at {shipping_dir}")
        return None

    # Find all UUID directories and get the most recently modified one
    uuid_dirs = [d for d in shipping_dir.iterdir() if d.is_dir()]
    if not uuid_dirs:
        print(f"Error: No UUID directories found in {shipping_dir}")
        return None

    # Sort by modification time (most recent first)
    uuid_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    most_recent = uuid_dirs[0]

    # Path to runtime_session.json
    runtime_path = most_recent / "_runtime" / "runtime_session.json"

    if not runtime_path.exists():
        print(f"Error: runtime_session.json not found at {runtime_path}")
        return None

    return runtime_path


def update_runtime_session(dest_dir: Path | None = None) -> bool:
    """Copy runtime_session.json to the assets directory.

    Args:
        dest_dir: Destination directory. Defaults to assets/ in project root.

    Returns:
        True if successful, False otherwise.
    """
    # Find source file
    source_path = get_stormgate_runtime_path()
    if not source_path:
        return False

    # Determine destination
    if dest_dir is None:
        # Default to assets directory relative to this script
        script_dir = Path(__file__).parent.parent
        dest_dir = script_dir / "assets"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "runtime_session.json"

    # Copy file
    print(f"Source: {source_path}")
    print(f"Destination: {dest_path}")

    try:
        shutil.copy2(source_path, dest_path)
        file_size = dest_path.stat().st_size
        print(f"Successfully copied runtime_session.json ({file_size:,} bytes)")
        return True
    except Exception as e:
        print(f"Error copying file: {e}")
        return False


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Update runtime_session.json from Stormgate game directory"
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Destination directory (default: assets/)"
    )
    parser.add_argument(
        "--show-path",
        action="store_true",
        help="Just show the path to runtime_session.json without copying"
    )

    args = parser.parse_args()

    if args.show_path:
        path = get_stormgate_runtime_path()
        if path:
            print(path)
            sys.exit(0)
        sys.exit(1)

    success = update_runtime_session(args.dest)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
