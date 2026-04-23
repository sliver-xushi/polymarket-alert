#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WATCH_DIRS = [ROOT / "public", ROOT / "api"]
WATCH_FILES = [ROOT / "server.py", ROOT / "vercel.json", ROOT / "README.md"]
IGNORE_DIRS = {".git", "__pycache__", "data", ".venv", "venv"}
IGNORE_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".db", ".db-shm", ".db-wal", ".log"}
CHECK_INTERVAL = 1.0
RESTART_COOLDOWN = 0.4


def iter_watch_files():
    for path in WATCH_FILES:
        if path.exists() and path.is_file():
            yield path
    for directory in WATCH_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in IGNORE_SUFFIXES:
                continue
            yield path


def snapshot():
    snap = {}
    for path in iter_watch_files():
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        snap[str(path)] = stat.st_mtime_ns
    return snap


def terminate_process(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def start_server():
    env = os.environ.copy()
    env.setdefault("PORT", "8787")
    return subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env)


def main():
    proc = None

    def shutdown(*_args):
        terminate_process(proc)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("TweetQuant dev watcher starting...")
    print("Watching:", ", ".join(str(path.relative_to(ROOT)) for path in WATCH_DIRS + WATCH_FILES if path.exists()))
    print("Open http://127.0.0.1:8787/")

    proc = start_server()
    last_snapshot = snapshot()

    while True:
        time.sleep(CHECK_INTERVAL)

        if proc.poll() is not None:
            print(f"Server exited with code {proc.returncode}, restarting...")
            time.sleep(RESTART_COOLDOWN)
            proc = start_server()
            last_snapshot = snapshot()
            continue

        current_snapshot = snapshot()
        if current_snapshot != last_snapshot:
            print("Change detected, restarting local server...")
            terminate_process(proc)
            time.sleep(RESTART_COOLDOWN)
            proc = start_server()
            last_snapshot = current_snapshot


if __name__ == "__main__":
    main()
