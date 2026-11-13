"""Transparent overlay MVP: topmost tkinter showing the last 3 lines from WS."""
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

WS_URL = "ws://127.0.0.1:5112"
lines = []

root = tk.Tk()
root.title("Dota Translator")
root.attributes("-topmost", True)
root.attributes("-alpha", 0.88)
root.configure(bg="black")

# bottom-centre of the primary screen; move it anywhere, geometry is not fixed
W, H = 560, 110
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry(f"{W}x{H}+{(sw - W) // 2}+{sh - H - 90}")

label = tk.Label(root, text="waiting for Dota voice...",
                 fg="white", bg="black", font=("Segoe UI", 12),
                 justify="left", anchor="w")
label.pack(fill="both", expand=True, padx=10, pady=8)


def update(text):
  label.config(text=text)


async def listen():
  import websockets, datetime
  while True:
    try:
      async with websockets.connect(WS_URL) as ws:
        async for raw in ws:
          try: m = json.loads(raw)
          except Exception: continue
          ts = datetime.datetime.now().strftime("%H:%M:%S")
          lag = f" ({m['lag']}s)" if m.get("lag") != None else ""
          lines.append(f"{ts} [{m['src']}] {m['en']}{lag}")
          update("\n".join(lines[-3:]))
    except Exception:
      await asyncio.sleep(2)

threading.Thread(target=lambda: asyncio.run(listen()), daemon=True).start()
root.mainloop()
