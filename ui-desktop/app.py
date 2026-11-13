"""Tiny desktop status app. No extra deps (tkinter stdlib).
Shows target + CABLE state, one-click start LIVE/mock backend, open views.
Run: .venv\\Scripts\\python.exe ui-desktop\\app.py
"""
import sys, subprocess, webbrowser, pathlib, tkinter as tk

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
sys.path.insert(0, str(ROOT / "backend"))


def _in_project_venv() -> bool:
  try:
    return pathlib.Path(sys.executable).resolve().is_relative_to((ROOT / ".venv").resolve())
  except Exception:
    return False


# Self-heal: double-clicked with system Python? Reopen under the venv interpreter.
if not _in_project_venv():
  try:
    subprocess.Popen([str(VENV_PYW)] + sys.argv, cwd=str(ROOT),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
  except Exception:
    pass
  raise SystemExit(3)

# single instance: a second copy only steals ports and confuses the backend
import os
try:
  import psutil
  _me = os.getpid()
  for _p in psutil.process_iter(["pid", "cmdline"]):
    try:
      if _p.info["pid"] == _me:
        continue
      _cmd = " ".join(_p.info.get("cmdline") or [])
      if "ui-desktop" in _cmd and "app.py" in _cmd:
        print("Desktop app already running - exiting this copy.")
        raise SystemExit(0)
    except SystemExit:
      raise
    except Exception:
      continue
except SystemExit:
  raise
except Exception:
  pass
import capture as Cap

proc = None
backend_mode = None  # "mock" or "live"
root = tk.Tk()
root.title("Dota Translator")
root.geometry("560x260")
status = tk.StringVar(value="checking...")
tk.Label(root, textvariable=status, justify="left", font=("Segoe UI", 11)).pack(padx=12, pady=10, anchor="w")


def backend_up() -> bool:
  import socket
  s = socket.socket()
  s.settimeout(0.3)
  try:
    s.connect(("127.0.0.1", 5112))
    return True
  except OSError:
    return False
  finally:
    s.close()


def refresh():
  s = Cap.wait_status()
  tgt = s.get("target", "dota2.exe")
  run = "yes" if s["dota_running"] else f"no (start {tgt})"
  cable = s["cable_info"] if s["cable_index"] is None else f"{s['cable_info']} [{s['cable_index']}]"
  be = "down"
  if backend_up():
    be = f"up ({backend_mode})" if backend_mode and proc and proc.poll() is None else "up (external)"
  status.set(f"Target {tgt} running: {run}\n"
             f"Capture: {'CABLE' if s['cable_index'] is not None else 'WASAPI process loopback (target only)'}\n"
             f"CABLE: {cable}\nBackend WS :5112: {be}")
  root.after(2000, refresh)


def start_backend(mock: bool):
  global proc, backend_mode
  if proc and proc.poll() is None:
    return
  if backend_up():
    status.set(status.get() + "\nBackend already running - not starting a second one.")
    return
  args = [str(VENV_PY), str(ROOT / "backend" / "app.py")]
  if mock:
    args.append("--mock")
  proc = subprocess.Popen(args, cwd=str(ROOT))
  backend_mode = "mock" if mock else "LIVE"


def stop_backend():
  global proc
  if proc and proc.poll() is None:
    proc.terminate()
  try:
    import os, psutil
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
      try:
        if p.info["pid"] == me:
          continue
        cmd = " ".join(p.info.get("cmdline") or [])
        if "backend" in cmd and "app.py" in cmd:
          p.terminate()
      except Exception:
        continue
  except Exception:
    pass


def open_second():
  webbrowser.open("http://127.0.0.1:5111")


def start_overlay():
  subprocess.Popen([str(VENV_PY), str(ROOT / "ui-overlay" / "overlay.py")], cwd=str(ROOT))


row = tk.Frame(root); row.pack(pady=6)
for txt, fn in [("Start LIVE", lambda: start_backend(False)), ("Start mock", lambda: start_backend(True)),
                ("Stop backend", stop_backend), ("2nd monitor", open_second), ("Overlay", start_overlay)]:
  tk.Button(row, text=txt, command=fn).pack(side="left", padx=4)

refresh()
# auto fresh LIVE backend on open: stop strays, then start live
import time as _t
stop_backend()
_t.sleep(1)
start_backend(False)
refresh()
root.mainloop()
