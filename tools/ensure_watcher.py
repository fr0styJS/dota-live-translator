"""Watchdog for the Dota watcher. Runs every minute from Task Scheduler.

The watcher only starts at logon (Startup shortcut). If it is killed or crashes
mid-session nothing brings it back, and Dota then opens with no translator.
This script is the safety net: if no instance of watch_dota.py is running, start
one hidden. It is idempotent - watch_dota.py also holds a single-instance mutex.

Never opens a console window: pythonw + CREATE_NO_WINDOW, and it prints nothing.
"""
import os, subprocess, sys, time, pathlib
import psutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
WATCHER = ROOT / "tools" / "watch_dota.py"
LOG = ROOT / "logs" / "watchdog.log"


def log(msg: str) -> None:
  try:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
      f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
  except Exception:
    pass


def watcher_alive() -> bool:
  me = os.getpid()
  for p in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
      if p.info["pid"] == me:
        continue
      if (p.info.get("name") or "").lower() not in ("python.exe", "pythonw.exe"):
        continue
      if "watch_dota.py" in " ".join(p.info.get("cmdline") or []):
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      continue
  return False


def main() -> int:
  if watcher_alive():
    return 0
  try:
    subprocess.Popen([str(VENV_PYW), str(WATCHER)], cwd=str(ROOT),
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log("watcher missing - restarted")
    return 0
  except Exception as e:
    log(f"restart failed: {e!r}")
    return 1


if __name__ == "__main__":
  sys.exit(main())
