"""Transparent overlay: topmost tkinter showing the latest translation lines.

Rows are not fixed: the overlay shows as many lines as the window can hold, so
drag it bigger for a busy fight and smaller for a clean screen. A pinned header
always states how many translation lines are being rendered, and the window size
is remembered between restarts.

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
import tkinter.font as tkfont

try:
  import yaml
  _CFG = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8-sig")) or {}
except Exception:
  _CFG = {}

DEFAULT_LINES = max(1, int((_CFG.get("ui") or {}).get("overlay_lines") or 10))
FONT = ("Segoe UI", 12)
HEAD_FONT = ("Segoe UI", 9)
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

_line_h = tkfont.Font(family=FONT[0], size=FONT[1]).metrics("linespace")
_head_h = tkfont.Font(family=HEAD_FONT[0], size=HEAD_FONT[1]).metrics("linespace") + 6
root.minsize(360, _head_h + _line_h * 2 + PAD_Y + 4)

_state = _load_state()
_geom = _state.get("geometry")
if not _geom:
  sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
  h = _line_h * DEFAULT_LINES + _head_h + PAD_Y + 4
  _geom = f"{W}x{h}+{(sw - W) // 2}+{sh - h - 90}"
root.geometry(_geom)

# pinned status line: always says how many translation lines are on screen
header = tk.Label(root, text="", fg="#8b93a1", bg="black", font=HEAD_FONT,
                  anchor="w", justify="left")
header.pack(fill="x", padx=10, pady=(4, 0))

label = tk.Label(root, text="waiting for Dota voice...",
                 fg="white", bg="black", font=FONT,
                 justify="left", anchor="w")
label.pack(fill="both", expand=True, padx=10, pady=(0, PAD_Y))

_save_job = None
_last_rows = None


def _rows() -> int:
  """How many translation lines fit under the header."""
  usable = root.winfo_height() - _head_h - PAD_Y - 4
  return max(1, usable // max(1, _line_h))


def _render() -> None:
  global _last_rows
  rows = _rows()
  header.config(text=f"This overlay renders {rows} translation "
                     f"line{'s' if rows != 1 else ''}  ·  drag an edge to resize")
  if lines:
    label.config(text="\n".join(list(lines)[-rows:]))
  else:
    label.config(text="waiting for Dota voice...")
  _last_rows = rows


def _on_configure(evt):
  if evt.widget is not root:
    return
  global _save_job
  _render()
  if _save_job is not None:
    root.after_cancel(_save_job)
  _save_job = root.after(500, lambda: _save_state(root.geometry(), _rows()))


root.bind("<Configure>", _on_configure)


def _entry(m) -> str:
  import datetime
  ts = datetime.datetime.now().strftime("%H:%M:%S")
  lang = m.get("src") or "EN"
  if m.get("kind") == "info":
    text = f"{ts} [INFO] {m.get('en')}"
  elif m.get("kind") == "chat":
    who = m.get("who") or m.get("source") or "CHAT"
    if m.get("passthrough"):
      body = m.get("src_text") or m.get("en") or ""
    else:
      body = f"{m.get('src_text')} → {m.get('en')}"
    text = f"{ts} [{who}] [{lang}] {body}"
  else:
    lag = f" ({m['lag']}s)" if m.get("lag") != None else ""
    text = f"{ts} [VOICE] [{lang}] {m['en']}{lag}"
  # one entry per line: clip instead of wrapping, so N lines stay N lines
  if len(text) > 150:
    text = text[:149] + "…"
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
