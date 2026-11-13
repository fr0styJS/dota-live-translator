import sys
print("loading ASR...", flush=True)
from faster_whisper import WhisperModel
asr = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8_float16")
print("ASR OK", flush=True)
print("loading MT...", flush=True)
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
mid = "facebook/nllb-200-distilled-600M"
tok = AutoTokenizer.from_pretrained(mid)
mt = AutoModelForSeq2SeqLM.from_pretrained(mid).to("cuda").eval()
print("MT OK", flush=True)
import torch
with torch.no_grad():
  enc = tok("Привет это пример", return_tensors="pt").to("cuda")
  gen = mt.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids("eng_Latn"),
                    max_new_tokens=30)
  print("MT-TEST:", tok.batch_decode(gen, skip_special_tokens=True)[0], flush=True)
print("WARMUP-DONE", flush=True)
