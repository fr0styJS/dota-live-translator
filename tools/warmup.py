"""Download the models and prove they load, on the device config.yaml asks for.

Run after setup, or with `python tools\\warmup.py` to pre-fetch ~2.5 GB.
Honours asr.device / mt.device so a CPU-only machine gets a clean message
instead of a traceback.
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8-sig"))

dev = (CFG["asr"].get("device") or "cuda").lower()
mt_dev = (CFG["mt"].get("device") or dev).lower()
ctype = CFG["asr"].get("compute_type", "int8_float16")
if dev == "cpu" and "float16" in ctype:
  ctype = "int8"  # no float16 matmul on CPU

import torch  # noqa: E402
if "cuda" in (dev, mt_dev) and not torch.cuda.is_available():
  print(f"config wants cuda but torch has no GPU (torch {torch.__version__}, "
        f"cuda build {torch.version.cuda}).", flush=True)
  print("Install the CUDA wheel (setup.ps1 does this) or set asr.device and "
        "mt.device to 'cpu' in config.yaml.", flush=True)
  sys.exit(2)

print(f"loading ASR {CFG['asr']['model']} {ctype} {dev}...", flush=True)
from faster_whisper import WhisperModel  # noqa: E402
asr = WhisperModel(CFG["asr"]["model"], device=dev, compute_type=ctype)
print("ASR OK", flush=True)

print(f"loading MT {CFG['mt']['model']} {mt_dev}...", flush=True)
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM  # noqa: E402
mid = CFG["mt"]["model"]
tok = AutoTokenizer.from_pretrained(mid)
mt = AutoModelForSeq2SeqLM.from_pretrained(mid).to(mt_dev).eval()
print("MT OK", flush=True)

with torch.no_grad():
  enc = tok("Missing Tidehunter mid", return_tensors="pt").to(mt_dev)
  gen = mt.generate(**enc,
                    forced_bos_token_id=tok.convert_tokens_to_ids("eng_Latn"),
                    max_new_tokens=30)
  print("MT-TEST:", tok.batch_decode(gen, skip_special_tokens=True)[0], flush=True)
print("WARMUP-DONE", flush=True)
