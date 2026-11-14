"""Transparent overlay: topmost tkinter showing the latest translation lines.

Rows are not fixed: the overlay shows as many lines as the window can hold, so
drag it bigger for a busy fight and smaller for a clean screen. The window size
is remembered between restarts, and hovering shows how many lines are visible.

config.yaml -> ui.overlay_lines only sets the *initial* height on first run.
"""
import asyncio, json, threading, sys as _sys, pathlib
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"


def _in_project_venv() -> bool:
  try:
    return pathlib.Path(_sys.executable).resolve().is_relative_to((ROOT / ".venv").resolve())
  except Exception:
    return False


if not _in_project_venv():
  # opened with a system interpreter (double-click): reopen under the venv
  try:
    import subprocess as _sp
    _sp.Popen([str(VENV_PYW)] + _sys.argv, cwd=str(ROOT),
              creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
  except Exception:
    pass
  raise SystemExit(3)

import tkinter as tk

try:
  import yaml
  _CFG = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8-sig")) or {}
except Exception:
  _CFG = {}

DEFAULT_LINES = max(1, int((_CFG.get("ui") or {}).get("overlay_lines") or 10))
FONT = ("Segoe UI", 12)
W = 640
PAD_Y = 8
WS_URL = "ws://127.0.0.1:5112"
STATE = ROOT / "logs" / "overlay.state.json"

lines = deque(maxlen=200)   # newest last; only the tail is rendered


def _load_state() -> dict:
  try:
    return json.loads(STATE.read_text(encoding="utf-8"))
  except Exception:
    return {}


def _save_state(geom: str, rows: int) -> None:
  try:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"geometry": geom, "rows": rows}), encoding="utf-8")
  except Exception:
    pass


root = tk.Tk()
root.title("Dota Translator")
root.attributes("-topmost", True)
root.attributes("-alpha", 0.88)
root.configure(bg="black")

import tkinter.font as tkfont
_line_h = tkfont.Font(family=FONT[0], size=FONT[1]).metrics("linespace")
root.minsize(320, _line_h * 2 + PAD_Y * 2 + 4)

_state = _load_state()
_geom = _state.get("geometry")
if not _geom:
  sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
  h = _line_h * DEFAULT_LINES + PAD_Y * 2 + 4
  _geom = f"{W}x{h}+{(sw - W) // 2}+{sh - h - 90}"
root.geometry(_geom)

label = tk.Label(root, text="waiting for Dota voice...",
                 fg="white", bg="black", font=FONT,
                 justify="left", anchor="w")
label.pack(fill="both", expand=True, padx=10, pady=PAD_Y)

# --- hover hint: how many lines are visible right now ----------------------
tip = None
tip_job = None
hide_job = None
_save_job = None


def _rows() -> int:
  """How many lines fit the current window height."""
  usable = root.winfo_height() - PAD_Y * 2 - 4
  return max(1, usable // max(1, _line_h))


def _render() -> None:
  rows = _rows()
  if lines:
    label.config(text="\n".join(list(lines)[-rows:]))
  else:
    label.config(text="waiting for Dota voice...")


def _show_tip():
  global tip
  if tip is not None or not root.winfo_viewable():
    return
  rows = _rows()
  tip = tk.Toplevel(root)
  tip.overrideredirect(True)
  tip.attributes("-topmost", True)
  tip.configure(bg="#1b1f27")
  tk.Label(tip, text=f"{rows} lines  Â·  drag an edge to resize  Â·  {len(lines)} buffered",
           bg="#1b1f27", fg="#aab3c0", font=("Segoe UI", 9),
           padx=8, pady=3).pack()
  tip.geometry(f"+{root.winfo_rootx() + 8}+{root.winfo_rooty() + 6}")


def _hide_tip():
  global tip, tip_job, hide_job
  if tip_job is not None:
    root.after_cancel(tip_job)
    tip_job = None
  if hide_job is not None:
    root.after_cancel(hide_job)
    hide_job = None
  if tip is not None:
    tip.destroy()
    tip = None


def _on_enter(_evt=None):
  global tip_job, hide_job
  if hide_job is not None:
    root.after_cancel(hide_job)
    hide_job = None
  if tip is None and tip_job is None:
    tip_job = root.after(400, _show_tip)


def _on_leave(_evt=None):
  global tip_job, hide_job
  if tip_job is not None:
    root.after_cancel(tip_job)
    tip_job = None
  if hide_job is not None:
    root.after_cancel(hide_job)
  hide_job = root.after(250, _hide_tip)  # grace period: no flicker between child widgets


def _on_configure(evt):
  if evt.widget is not root:
    return
  global _save_job
  _hide_tip()
  _render()
  if _save_job is not None:
    root.after_cancel(_save_job)
  _save_job = root.after(500, lambda: _save_state(root.geometry(), _rows()))


for _w in (root, label):
  _w.bind("<Enter>", _on_enter)
  _w.bind("<Leave>", _on_leave)
root.bind("<Configure>", _on_configure)


def _entry(m) -> str:
  import datetime
  ts = datetime.datetime.now().strftime("%H:%M:%S")
  lag = f" ({m['lag']}s)" if m.get("lag") != None else ""
  text = f"{ts} [{m['src']}] {m['en']}{lag}"
  # one entry per line: clip instead of wrapping, so N lines stay N lines
  if len(text) > 150:
    text = text[:149] + "â€¦"
  return text


async def listen():
  import websockets
  while True:
    try:
      async with websockets.connect(WS_URL) as ws:
        async for raw in ws:
          try: m = json.loads(raw)
          except Exception: continue
          lines.append(_entry(m))
          root.after(0, _render)   # tk must be touched from the main thread
    except Exception:
      await asyncio.sleep(2)


threading.Thread(target=lambda: asyncio.run(listen()), daemon=True).start()
_render()
root.mainloop()
