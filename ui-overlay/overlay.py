"""Transparent overlay MVP: topmost tkinter showing the last N lines from WS.

N comes from config.yaml -> ui.overlay_lines (default 10). The window height is
derived from the font's line spacing, so changing N does not need layout edits.
"""
import asyncio, json, threading, sys as _sys, pathlib

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
  _CFG = yaml.safe_load(open(ROOT / "config.yaml")) or {}
except Exception:
  _CFG = {}

MAX_LINES = max(1, int((_CFG.get("ui") or {}).get("overlay_lines") or 10))
FONT = ("Segoe UI", 12)
W = 640
WS_URL = "ws://127.0.0.1:5112"
lines = []

root = tk.Tk()
root.title("Dota Translator")
root.attributes("-topmost", True)
root.attributes("-alpha", 0.88)
root.configure(bg="black")

# height from real font metrics: N lines + vertical padding
import tkinter.font as tkfont
_line_h = tkfont.Font(family=FONT[0], size=FONT[1]).metrics("linespace")
PAD_Y = 8
H = _line_h * MAX_LINES + PAD_Y * 2 + 4

sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry(f"{W}x{H}+{(sw - W) // 2}+{sh - H - 90}")

label = tk.Label(root, text="waiting for Dota voice...",
                 fg="white", bg="black", font=FONT,
                 justify="left", anchor="w")
label.pack(fill="both", expand=True, padx=10, pady=PAD_Y)


def update(text):
  label.config(text=text)


def _entry(m) -> str:
  import datetime
  ts = datetime.datetime.now().strftime("%H:%M:%S")
  lag = f" ({m['lag']}s)" if m.get("lag") != None else ""
  text = f"{ts} [{m['src']}] {m['en']}{lag}"
  # keep one entry per line: clip instead of wrapping, so N lines stay N lines
  if len(text) > 96:
    text = text[:95] + "…"
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
          del lines[:-MAX_LINES]
          update("\n".join(lines))
    except Exception:
      await asyncio.sleep(2)


threading.Thread(target=lambda: asyncio.run(listen()), daemon=True).start()
root.mainloop()
