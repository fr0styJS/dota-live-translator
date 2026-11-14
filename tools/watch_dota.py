"""Dota auto-start watcher. Runs hidden at logon via the Startup shortcut.
Every 5s: if dota2.exe runs and backend WS :5112 is down -> launch backend LIVE headless.
When Dota closes: ~10s grace, then backend + overlay are killed.
Never shell out to console apps (tasklist/...) here: this process has no console,
so every such call made Windows spawn a visible terminal host that flashed shut.
"""
import subprocess, time, socket, sys, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"


def _in_project_venv() -> bool:
  try:
    return pathlib.Path(sys.executable).resolve().is_relative_to((ROOT / ".venv").resolve())
  except Exception:
    return False


# Self-heal: double-clicked with system Python? Reopen under the venv interpreter.
if not _in_project_venv():
  try:
    # always headless: never flash a console, whatever launched us
    subprocess.Popen([str(VENV_PYW)] + sys.argv, cwd=str(ROOT),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
  except Exception:
    pass
  raise SystemExit(3)

LOGDIR = str(ROOT / "logs")
os.makedirs(LOGDIR, exist_ok=True)
def log(msg):
  try:
    with open(os.path.join(LOGDIR, "watch.log"), "a", encoding="utf-8") as f:
      f.write(time.strftime("%H:%M:%S") + " " + msg + "\n")
  except Exception:
    pass

# --- single instance ---------------------------------------------------------
# Two watchers racing would double-launch the backend/overlay. The mutex is held
# by the real interpreter and released by the kernel when the process dies, so a
# restart is never blocked by a stale lock.
import ctypes
_k32 = ctypes.windll.kernel32
_MUTEX = _k32.CreateMutexW(None, False, "Local\\dota-translate-watcher")
if _k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
  log("duplicate watcher started - exiting")
  raise SystemExit(0)

# Anything that kills this process silently (hard crash, not a Python exception)
# leaves a stack trace in watch.fault.log; a heartbeat file shows it was alive.
import faulthandler
_faultf = open(os.path.join(LOGDIR, "watch.fault.log"), "a", buffering=1)
faulthandler.enable(file=_faultf, all_threads=True)
HEARTBEAT = os.path.join(LOGDIR, "watch.heartbeat")
def beat(extra=""):
  try:
    with open(HEARTBEAT, "w", encoding="utf-8") as f:
      f.write(f"pid={os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')} {extra}")
  except Exception:
    pass

BACKEND = [str(VENV_PYW), str(ROOT / "backend" / "app.py")]  # live, no --mock
OVERLAY = [str(VENV_PYW), str(ROOT / "ui-overlay" / "overlay.py")]  # on demand, see below
WITH_OVERLAY = True  # subtitle window pops with the backend when Dota opens

def dota_running() -> bool:
  # psutil first: no console window is ever created. tasklist (a console app)
  # spawned from this windowless process used to pop a Terminal host every poll.
  try:
    import psutil
    for p in psutil.process_iter(["name"]):
      try:
        if (p.info.get("name") or "").lower() == "dota2.exe":
          return True
      except Exception:
        continue
    return False
  except Exception:
    pass
  try:
    out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq dota2.exe"],
                                  text=True, stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return "dota2.exe" in out.lower()
  except Exception:
    return False

def ws_up() -> bool:
  s = socket.socket()
  s.settimeout(0.5)
  try:
    s.connect(("127.0.0.1", 5112))
    return True
  except OSError:
    return False
  finally:
    s.close()

def proc_running(fragment: str) -> bool:
  try:
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
      try:
        # interpreters only: a shell that merely mentions the path (or a grep for
        # it) must not count, or the relaunch is skipped for no reason
        if (p.info.get("name") or "").lower() not in ("python.exe", "pythonw.exe"):
          continue
        if fragment in " ".join(p.info.get("cmdline") or []):
          return True
      except Exception:
        continue
    return False
  except Exception:
    return False

def launch(args, logname):
  f = open(os.path.join(LOGDIR, logname), "a", encoding="utf-8", buffering=1)
  return subprocess.Popen(args, cwd=str(ROOT), stdout=f,
                          stderr=subprocess.STDOUT,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

def kill_translator_tree():
  """Kill backend + overlay (any interpreter), leave watcher alive. Returns count."""
  import psutil
  me = os.getpid()
  mine = {"backend", "app.py", "ui-overlay"}
  dead = 0
  procs = []
  for p in psutil.process_iter(["pid", "cmdline"]):
    try:
      if p.info["pid"] == me:
        continue
      cmd = " ".join(p.info.get("cmdline") or []).lower()
      if ("backend" in cmd and "app.py" in cmd) or "ui-overlay" in cmd:
        procs.append(p)
    except Exception:
      continue
  for p in procs:
    try:
      p.terminate()
      dead += 1
    except Exception:
      pass
  if procs:
    time.sleep(3)
    for p in procs:
      try:
        if p.is_running():
          p.kill()
      except Exception:
        pass
  return dead

backend_proc = None
overlay_proc = None
was_running = False
missed = 0
log("watcher started")
while True:
  try:
    running = dota_running()
    if running and not was_running:
      log("dota2.exe detected")
    if not running and was_running:
      log("dota2.exe closed")
    was_running = running
    if running:
      missed = 0
      if backend_proc and backend_proc.poll() is not None:
        log(f"backend exited code {backend_proc.poll()}, will relaunch")
        backend_proc = None
      if overlay_proc and overlay_proc.poll() is not None:
        log("overlay closed, will reopen")
        overlay_proc = None
      if not backend_proc and not ws_up():
        backend_proc = launch(BACKEND, "backend.log")
        log("backend launched (LIVE)")
      if WITH_OVERLAY and not overlay_proc and not proc_running("ui-overlay"):
        overlay_proc = launch(OVERLAY, "overlay.log")
        log("overlay launched")
    else:
      # dota gone: grace period, then shut translator down (goal: close with game)
      missed += 1
      if missed == 2:
        n = kill_translator_tree()
        backend_proc = None
        overlay_proc = None
        log(f"translator stopped ({n} procs) - dota closed")
    time.sleep(5)
    beat("dota" if running else "idle")
  except Exception as e:
    import traceback
    log(f"watcher error: {e}")
    log(traceback.format_exc().strip().replace("\n", " | ")[:400])
    beat("error")
    time.sleep(5)
