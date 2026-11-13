import sys
import time
import pathlib

import numpy as np
import psutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))
import procloop  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
rows = []
for p in psutil.process_iter(["name"]):
    if (p.info.get("name") or "").lower() == "firefox.exe":
        rows.append(p.pid)

_real = procloop._find_pid
for pid in rows:
    chunks = []
    procloop._find_pid = lambda exe, _p=pid: _p
    sup = procloop.Supervisor("forced", lambda m: chunks.append(m), log=lambda m: None)
    sup.start()
    time.sleep(secs)
    sup.stop()
    procloop._find_pid = _real
    if not chunks:
        print(f"firefox pid={pid}: no buffers")
        continue
    peak = max(float(np.abs(m).max()) for m in chunks if len(m))
    rms = float(np.sqrt(np.mean(np.concatenate(chunks) ** 2)))
    if peak > 0.002:
        print(f"firefox pid={pid}: peak={peak:.4f} rms={rms:.4f} <- RENDERING AUDIO")
    else:
        print(f"firefox pid={pid}: peak={peak:.5f} (idle)")
