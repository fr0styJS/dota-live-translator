"""Offline test: glossary + examples, no GPU needed."""
import sys, io, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))
import glossary as G
cases = [
  ("ru", "Hello this is an example"),
  ("en", "Missing Tidehunter"),
  ("ru", "тайд missing мид ss"),
]
for lang, txt in cases:
  prot, slots = G.protect(txt)
  back = G.restore(prot, slots)
  skip_mt = lang == "en"
  print(f"[{lang.upper()}] {txt} -> protect={prot} roundtrip_ok={back==txt} skip_mt={skip_mt}")
print("OK - run mock backend next: .venv\\Scripts\\python.exe backend\\app.py --mock")
