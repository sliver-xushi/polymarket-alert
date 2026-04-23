#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path


LABEL = "com.tweetquant.devserver"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def main():
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"

    subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
    subprocess.run(["launchctl", "disable", service], check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"Removed {LABEL}")


if __name__ == "__main__":
    main()
