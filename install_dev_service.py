#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path


LABEL = "com.tweetquant.devserver"
ROOT = Path(__file__).resolve().parent
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = ROOT / ".devserver.log"
ERR_PATH = ROOT / ".devserver.err.log"


def plist_content():
    python_bin = "/usr/bin/python3"
    watcher = str(ROOT / "dev_watch.py")
    workdir = str(ROOT)
    stdout_path = str(LOG_PATH)
    stderr_path = str(ERR_PATH)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{python_bin}</string>
      <string>{watcher}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PORT</key>
      <string>8787</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout_path}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_path}</string>
  </dict>
</plist>
"""


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def main():
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_content(), encoding="utf-8")

    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"

    run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
    run(["launchctl", "bootstrap", domain, str(PLIST_PATH)])
    run(["launchctl", "enable", service], check=False)
    run(["launchctl", "kickstart", "-k", service])

    print(f"Installed {LABEL}")
    print(f"Plist: {PLIST_PATH}")
    print("Open http://127.0.0.1:8787/")


if __name__ == "__main__":
    main()
