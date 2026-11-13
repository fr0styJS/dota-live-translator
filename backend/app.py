"""Dota Live Translator backend. Mock for UI test, live for GPU pipeline."""
import argparse, asyncio, json, time, http.server, threading, functools
import yaml, pathlib
import sys as _sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"


def _in_project_venv() -> bool:
    try:
        return pathlib.Path(_sys.executable).resolve().is_relative_to((ROOT / ".venv").resolve())
    except Exception:
        return False


if not _in_project_venv():
    # double-clicked with a system interpreter: reopen under the project venv
    try:
        import subprocess as _sp
        _sp.Popen([str(VENV_PYW)] + _sys.argv, cwd=str(ROOT),
                  creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    raise SystemExit(3)

CFG = yaml.safe_load(open(ROOT / "config.yaml"))
HTTP_PORT = CFG["server"]["port"]
WS_PORT = HTTP_PORT + 1
clients = set()

def broadcast(msg: dict):
  data = json.dumps(msg)
  for ws in list(clients):
    try:
      asyncio.run_coroutine_threadsafe(ws.send(data), loop)
    except Exception:
      pass

# --- mock feed: your examples + a few more ---
MOCK = [
  ("ru", "Hello this is an example", "Hello this is an example"),
  ("en", "Missing Tidehunter", "Missing Tidehunter"),
  ("ru", "Тайд пропал с мида, осторожно", "Tide missing from mid, careful"),
  ("es", "voy a gankear top", "going to gank top"),
]

async def mock_loop():
  i = 0
  while True:
    src, txt, en = MOCK[i % len(MOCK)]
    msg = {"ts": time.time(), "src": src.upper(), "src_text": txt,
           "en": en if src != "en" else txt, "passthrough": src == "en"}
    for ws in list(clients):
      try: await ws.send(json.dumps(msg))
      except Exception: pass
    i += 1
    await asyncio.sleep(4)

async def ws_handler(ws):
  clients.add(ws)
  try:
    await ws.wait_closed()
  finally:
    clients.discard(ws)

def ports_free() -> str | None:
  import socket
  for p in (HTTP_PORT, WS_PORT):
    s = socket.socket()
    try:
      s.bind(("127.0.0.1", p))
    except OSError:
      return f"port {p} in use — backend already running? Close the other window or kill python backend/app.py, then retry."
    finally:
      s.close()
  return None

def serve_http():
  h = functools.partial(http.server.SimpleHTTPRequestHandler,
                        directory=str(pathlib.Path(__file__).parent.parent / "ui-second"))
  httpd = http.server.ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), h)
  print(f"2nd-monitor page: http://127.0.0.1:{HTTP_PORT}")
  httpd.serve_forever()

async def main(mock: bool):
  global loop
  loop = asyncio.get_running_loop()
  threading.Thread(target=serve_http, daemon=True).start()
  import websockets
  print(f"WS on ws://127.0.0.1:{WS_PORT}")
  async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT):
    if mock:
      await mock_loop()
    else:
      from live import run_live  # heavy deps only in live mode
      await run_live(broadcast_async=ws_broadcast)

async def ws_broadcast(msg: dict):
  for ws in list(clients):
    try: await ws.send(json.dumps(msg))
    except Exception: pass

if __name__ == "__main__":
  ap = argparse.ArgumentParser(description="Dota Live Translator backend")
  ap.add_argument("--mock", action="store_true", help="feed scripted demo lines, no models")
  ap.add_argument("--port", type=int, default=None,
                  help="HTTP port (WS = port+1). Default from config.yaml")
  a = ap.parse_args()
  if a.port:
    HTTP_PORT = a.port
    WS_PORT = a.port + 1
  busy = ports_free()
  if busy:
    print(busy)
    raise SystemExit(2)
  asyncio.run(main(a.mock))
