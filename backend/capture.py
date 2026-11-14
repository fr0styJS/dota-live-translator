"""Dota-only audio routing. Lightweight: process watch + CABLE device.
Setup once: Windows Sound > Volume mixer > Dota 2 > Output = CABLE Input.
Then CABLE Output carries Dota-only audio, nothing else triggers inference.
"""
import pathlib
import time

try:
  import yaml
  _CFG = yaml.safe_load(open(pathlib.Path(__file__).parent.parent / "config.yaml", encoding="utf-8-sig"))
except Exception:
  _CFG = {}

DOTA_EXE = "dota2.exe"
# Live target: inference is gated on this process running (config.yaml dota.process).
# Anything else was test mode and would keep the pipeline awake with Dota shut.
TARGET_EXE = ((_CFG.get("dota") or {}).get("process") or DOTA_EXE).strip()
CABLE_KEYS = ("cable output", "vb-audio", "cable input")

def is_target_running(exe: str | None = None) -> bool:
  want = (exe or TARGET_EXE).lower()
  try:
    import psutil
    for p in psutil.process_iter(["name"]):
      try:
        if (p.info.get("name") or "").lower() == want:
          return True
      except Exception:
        continue
    return False
  except Exception:
    import subprocess
    try:
      out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {want}"],
                                    text=True, stderr=subprocess.DEVNULL)
      return want in out.lower()
    except Exception:
      return False

def is_dota_running() -> bool:
  # compat alias (old call sites in live.py): gates on TARGET_EXE, i.e. dota2.exe
  return is_target_running()

def find_cable_device():
  """Return (index, name) for VB-Cable output, or (None, hint)."""
  try:
    import sounddevice as sd
    devs = sd.query_devices()
    for i, d in enumerate(devs):
      n = d["name"].lower()
      if "cable output" in n and d.get("max_input_channels", 0) > 0:
        return i, d["name"]
    # fallback: any cable-named input
    for i, d in enumerate(devs):
      n = d["name"].lower()
      if "cable" in n and d.get("max_input_channels", 0) > 0:
        return i, d["name"]
    names = [d["name"] for d in devs]
    return None, f"no CABLE found. devices={names}"
  except Exception as e:
    return None, f"audio query failed: {e}"

def wait_status(poll_s: float = 1.0):
  """One-shot status for UI/tray: target running, cable present."""
  running = is_target_running()
  idx, info = find_cable_device()
  return {"dota_running": running, "target": TARGET_EXE,
          "cable_index": idx, "cable_info": info,
          "ready": bool(running and idx is not None), "ts": time.time()}
