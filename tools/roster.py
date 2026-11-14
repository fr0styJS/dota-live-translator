"""Assign hero names to chat slots for the current match.

The game's feed tells us which ten heroes are in the match and which team each is
on, but never which player slot holds which hero. The scoreboard lists players in
slot order, so this window is a 10-dropdown answer: pick the hero per slot once,
save, and chat lines become "[ARC WARDEN]" instead of "[TEAM-P4]".

Options come from logs/roster.json (written by the backend), so nothing is typed.
Saved to logs/slots.json, which the backend picks up without a restart.

Run: .venv\\Scripts\\python.exe tools\\roster.py
"""
import json
import pathlib
import sys
import tkinter as tk
from tkinter import ttk

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROSTER = ROOT / "logs" / "roster.json"
SLOTS = ROOT / "logs" / "slots.json"

RADIANT_LABEL = "RADIANT (slots 0-4)"
DIRE_LABEL = "DIRE (slots 5-9)"


def pretty(name: str) -> str:
  return name.replace("npc_dota_hero_", "").replace("_", " ").upper()


def load_roster() -> dict:
  try:
    return json.loads(ROSTER.read_text(encoding="utf-8"))
  except Exception:
    return {}


def load_slots() -> dict:
  try:
    return json.loads(SLOTS.read_text(encoding="utf-8"))
  except Exception:
    return {}


class RosterWindow:
  def __init__(self, root: tk.Tk):
    self.root = root
    self.roster = load_roster()
    self.saved = load_slots()
    self.matchid = str(self.roster.get("matchid") or self.saved.get("matchid") or "")
    self.vars: dict[int, tk.StringVar] = {}

    root.title("Dota Translator - roster")
    root.geometry("520x420")
    root.attributes("-topmost", True)

    head = tk.Label(root, justify="left", anchor="w", font=("Segoe UI", 9),
                    text=(f"match {self.matchid or '?'}  ·  pick the hero for each slot.\n"
                          "Your own slot is filled in; the scoreboard (Tab) lists players in slot order."))
    head.pack(fill="x", padx=10, pady=(8, 4))

    body = tk.Frame(root)
    body.pack(fill="both", expand=True, padx=10)

    names = {str(k): v for k, v in (self.saved.get("names") or {}).items()}
    for col, (label, team, base) in enumerate(
        (("RADIANT", "radiant", 0), ("DIRE", "dire", 5))):
      box = ttk.LabelFrame(body, text=label)
      box.grid(row=0, column=col, sticky="nsew", padx=4, pady=4)
      body.columnconfigure(col, weight=1)
      choices = ["(unknown)"] + sorted(pretty(h) for h in (self.roster.get(team) or []))
      for i in range(5):
        slot = base + i
        row = tk.Frame(box)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=f"P{slot}", width=4, anchor="w").pack(side="left")
        var = tk.StringVar(value=names.get(str(slot)) or "(unknown)")
        self.vars[slot] = var
        cb = ttk.Combobox(row, textvariable=var, values=choices, width=17, state="readonly")
        cb.pack(side="left", fill="x", expand=True)
        if slot == 0:  # your own slot is known - lich here means you
          pass

    btns = tk.Frame(root)
    btns.pack(fill="x", padx=10, pady=8)
    tk.Button(btns, text="Save", width=10, command=self.save).pack(side="left")
    tk.Button(btns, text="Reload roster", width=14, command=self.reload).pack(side="left", padx=6)
    tk.Button(btns, text="Clear", width=8, command=self.clear).pack(side="left")
    self.status = tk.Label(btns, text="", anchor="w", fg="#666")
    self.status.pack(side="left", padx=8, fill="x", expand=True)

  def reload(self):
    self.roster = load_roster()
    self.status.config(text=f"roster: {len(self.roster.get('radiant') or [])} radiant / "
                            f"{len(self.roster.get('dire') or [])} dire")

  def save(self):
    names = {str(s): v.get() for s, v in self.vars.items() if v.get() and v.get() != "(unknown)"}
    payload = {"matchid": self.matchid, "names": names}
    SLOTS.parent.mkdir(parents=True, exist_ok=True)
    SLOTS.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    self.status.config(text=f"saved {len(names)} slots -> {SLOTS.name}")

  def clear(self):
    try:
      SLOTS.unlink()
    except OSError:
      pass
    for var in self.vars.values():
      var.set("(unknown)")
    self.status.config(text="cleared")


if __name__ == "__main__":
  r = tk.Tk()
  RosterWindow(r)
  r.mainloop()
  sys.exit(0)
