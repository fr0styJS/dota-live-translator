"""Smoke test: start the backend in mock mode, check HTTP + WS.

Usage: python tools\\test_mock.py [http_port]
Default uses config.yaml's port. A second backend on the same ports is refused,
so pass an unused port when the real service is running.
"""
import subprocess, time, sys, json, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
APP = ROOT / "backend" / "app.py"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else None
WS = (PORT + 1) if PORT else 5112
HTTP = PORT or 5111

args = [str(PY), str(APP), "--mock"]
if PORT:
  args += ["--port", str(PORT)]

proc = subprocess.Popen(args, cwd=str(ROOT),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
  for _ in range(20):
    time.sleep(1)
    try:
      with urllib.request.urlopen(f"http://127.0.0.1:{HTTP}/", timeout=2) as r:
        if r.status == 200:
          print(f"HTTP-OK :{HTTP}", flush=True)
          break
    except Exception:
      pass
  else:
    print("HTTP-FAIL"); sys.exit(1)
  import asyncio, websockets
  async def check():
    async with websockets.connect(f"ws://127.0.0.1:{WS}") as ws:
      for i in range(2):
        raw = await asyncio.wait_for(ws.recv(), timeout=8)
        m = json.loads(raw)
        assert "src" in m and "en" in m, m
        print(f"WS-OK {m['src']}: {m['en'][:60]}", flush=True)
  asyncio.run(check())
  print("MOCK-TEST-PASS", flush=True)
finally:
  proc.terminate()
  try: proc.wait(timeout=5)
  except Exception: proc.kill()
