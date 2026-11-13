import threading, soundcard as sc
out = []
def pump():
  import ctypes
  ctypes.windll.ole32.CoInitialize(None)
  spk = sc.default_speaker()
  lb = sc.get_microphone(spk.name, include_loopback=True)
  with lb.recorder(samplerate=48000, channels=2, blocksize=4800) as rec:
    for _ in range(2):
      data = rec.record(numframes=24000)
      mono = data.mean(axis=1)
      n = len(mono) // 3 * 3
      out.append(mono[:n].reshape(-1, 3).mean(axis=1).astype("float32"))
t = threading.Thread(target=pump)
t.start(); t.join(timeout=30)
print("chunks:", len(out), "len0:", len(out[0]) if out else 0, "max:", float(abs(out[0]).max()) if out else 0)
assert len(out) == 2 and len(out[0]) == 8000, "pump thread record failed"
print("PUMP-THREAD-OK")
