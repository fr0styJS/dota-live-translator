"""Port-guard test: a second backend on the same ports must exit with code 2."""
import subprocess, time, sys, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
APP = ROOT / "backend" / "app.py"

p1 = subprocess.Popen([str(PY), str(APP), "--mock"],
                      cwd=str(ROOT),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
  for _ in range(20):
    time.sleep(1)
    try:
      with urllib.request.urlopen("http://127.0.0.1:5111/", timeout=2) as r:
        if r.status == 200:
          print("FIRST-OK", flush=True)
          break
    except Exception:
      pass
  else:
    print("FIRST-FAIL"); sys.exit(1)
  p2 = subprocess.run([str(PY), str(APP), "--mock"],
                      capture_output=True, text=True, timeout=20)
  print("SECOND-CODE:", p2.returncode, flush=True)
  print("SECOND-OUT:", (p2.stdout + p2.stderr).strip()[-200:], flush=True)
  assert p2.returncode == 2 and "already running" in (p2.stdout + p2.stderr), "guard missing"
  print("GUARD-OK", flush=True)
finally:
  p1.terminate()
  try: p1.wait(timeout=5)
  except Exception: p1.kill()
