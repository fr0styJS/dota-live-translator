"""Minimal Dota 2 Game State Integration receiver.

Purpose: show exactly what the game pushes, and whether anything in it contains
chat text. GSI is *push* (the game POSTs JSON to a URI you configure), not poll.

Usage:
  python tools\\gsi_probe.py --write-cfg     # install gamestate_integration_dotalive.cfg
  python tools\\gsi_probe.py [port]          # listen (default 5300) and log payloads

Payloads land in logs\\gsi.log, one JSON object per line. Restart Dota 2 after
--write-cfg: GSI configs are read at game launch.
"""
import argparse
import http.server
import json
import pathlib
import re
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "gsi.log"
CFG_NAME = "gamestate_integration_dotalive.cfg"

# every component the client can be asked for (chat is not among them)
COMPONENTS = ["auth", "provider", "map", "player", "hero", "abilities", "items",
              "events", "buildings", "league", "draft", "wearables", "minimap",
              "roshan", "couriers", "neutralitems"]


def find_game_cfg_dir() -> pathlib.Path | None:
  """Steam library path from the registry, then the well-known relative path."""
  import winreg
  roots = []
  try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
      roots.append(pathlib.Path(winreg.QueryValueEx(k, "SteamPath")[0]))
  except Exception:
    pass
  roots.append(pathlib.Path(r"E:\SteamLibrary"))
  roots.append(pathlib.Path(r"C:\Program Files (x86)\Steam"))
  for r in roots:
    for lib in [r] + [p for p in ([r / "steamapps"] if r.name != "steamapps" else [r])]:
      d = lib / "common" / "dota 2 beta" / "game" / "dota" / "cfg"
      if d.is_dir():
        return d
  return None


def write_cfg(port: int) -> int:
  d = find_game_cfg_dir()
  if not d:
    print("could not locate the Dota 2 cfg folder; pass nothing and edit manually", flush=True)
    return 1
  target = d / "gamestate_integration"
  target.mkdir(exist_ok=True)
  body = ['"Dota Live Translator probe"', "{",
          f'    "uri"          "http://127.0.0.1:{port}/"',
          '    "timeout"      "5.0"', '    "buffer"       "0.1"',
          '    "throttle"     "0.1"', '    "heartbeat"    "10.0"', '    "data"', "    {"]
  body += [f'        "{c}"{" " * (15 - len(c))}"1"' for c in COMPONENTS]
  body += ["    }", "}", ""]
  (target / CFG_NAME).write_text("\n".join(body), encoding="ascii")
  print(f"wrote {target / CFG_NAME}", flush=True)
  print("restart Dota 2 for it to be read; remove that file to undo.", flush=True)
  return 0


def chat_hits(obj, path="") -> list[str]:
  out = []
  if isinstance(obj, dict):
    for k, v in obj.items():
      p = f"{path}.{k}" if path else str(k)
      if re.search(r"chat|message|text_said", str(k), re.I):
        out.append(f"{p} = {v!r}")
      out += chat_hits(v, p)
  elif isinstance(obj, list):
    for i, v in enumerate(obj):
      out += chat_hits(v, f"{path}[{i}]")
  return out


class Handler(http.server.BaseHTTPRequestHandler):
  def do_POST(self):
    n = int(self.headers.get("Content-Length") or 0)
    raw = self.rfile.read(n)
    try:
      data = json.loads(raw or b"{}")
    except Exception:
      data = {"_unparsed": raw[:200].decode("utf-8", "replace")}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
      f.write(json.dumps(data) + "\n")
    m = data.get("map") or {}
    p = (data.get("player") or {}).get("name") or ""
    hits = chat_hits(data)
    stamp = time.strftime("%H:%M:%S")
    print(f"{stamp} GSI state={m.get('game_state')} clock={m.get('clock_time')} "
          f"hero={(data.get('hero') or {}).get('name') or '-'} player={p} "
          f"chat_keys={len(hits)}", flush=True)
    for h in hits[:10]:
      print(f"      {h}", flush=True)
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"ok")

  def log_message(self, *_a):
    pass


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("port", nargs="?", type=int, default=5300)
  ap.add_argument("--write-cfg", action="store_true", help="install the GSI config file")
  a = ap.parse_args()
  if a.write_cfg:
    return write_cfg(a.port)
  print(f"listening on http://127.0.0.1:{a.port}/  (log: {LOG})", flush=True)
  print("waiting for the game to POST... start Dota 2 and enter a game.", flush=True)
  http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
  return 0


if __name__ == "__main__":
  sys.exit(main())
