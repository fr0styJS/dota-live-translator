"""Live pipeline: loopback -> Silero VAD (CPU) -> faster-whisper (CUDA) -> NLLB (CUDA)."""
import time, numpy as np, glossary as G, yaml, pathlib
CFG = yaml.safe_load(open(pathlib.Path(__file__).parent.parent / "config.yaml", encoding="utf-8-sig"))

NLLB_LANG = {"ru": "rus_Cyrl", "en": "eng_Latn", "es": "spa_Latn",
             "uk": "ukr_Cyrl", "tl": "tgl_Latn", "pt": "por_Latn",
             "id": "ind_Latn"}

async def run_live(broadcast_async):
  import sounddevice as sd
  from faster_whisper import WhisperModel
  from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
  import torch
  from silero_vad import load_silero_vad, get_speech_timestamps

  print("loading VAD (CPU)...", flush=True)
  vad = load_silero_vad()

  dev = (CFG["asr"].get("device") or "cuda").lower()
  mt_dev = (CFG["mt"].get("device") or dev).lower()
  if "cuda" in (dev, mt_dev) and not torch.cuda.is_available():
    print("ERROR: config asks for cuda but torch sees no GPU.", flush=True)
    print("       Install an NVIDIA driver + CUDA torch, or set asr.device and "
          "mt.device to 'cpu' in config.yaml (much slower).", flush=True)
    raise SystemExit(3)
  ctype = CFG["asr"].get("compute_type", "int8_float16")
  if dev == "cpu" and "float16" in ctype:
    ctype = "int8"  # float16 matmul is not available on CPU

  print(f"loading ASR {CFG['asr']['model']} {ctype} {dev}...", flush=True)
  asr = WhisperModel(CFG["asr"]["model"], device=dev, compute_type=ctype)
  print(f"loading MT {CFG['mt']['model']} {mt_dev}...", flush=True)
  mt_id = CFG["mt"]["model"]
  tok = AutoTokenizer.from_pretrained(mt_id)
  mt = AutoModelForSeq2SeqLM.from_pretrained(mt_id).to(mt_dev).eval()

  sr = CFG["sample_rate"]
  import capture as Cap
  st = Cap.wait_status()
  print(f"target={Cap.TARGET_EXE} running={st['dota_running']} cable={st['cable_index']} {st['cable_info']}")
  loop = st["cable_index"]
  if loop is None:
    print("No CABLE Output found: will use WASAPI process loopback, i.e. only the "
          "target app's audio. Install VB-Cable if you prefer a cable route.", flush=True)

  buf = []
  def mt_translate(text: str, src: str) -> str:
    if src == "en":
      return text  # passthrough, e.g. Missing Tidehunter
    prot, slots = G.protect(text)
    tok.src_lang = NLLB_LANG.get(src, "rus_Cyrl")
    enc = tok(prot, return_tensors="pt").to(mt_dev)
    with torch.no_grad():
      gen = mt.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids("eng_Latn"))
    out = tok.batch_decode(gen, skip_special_tokens=True)[0]
    return G.restore(out, slots)

  def callback(indata, frames, t, status):
    if indata.shape[1] >= 2:
      buf.append(indata.mean(axis=1).astype("float32"))
    else:
      buf.append(indata[:, 0].copy())

  import sounddevice as sd
  capture_kind = "none"
  if loop is not None:
    stream = sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                            device=loop, callback=callback, blocksize=512*16)
    stream.start()
    capture_kind = f"CABLE device [{loop}]"
  else:
    # No CABLE: WASAPI process loopback, so ONLY the target process tree is heard
    # (Dota voice chat), not Discord/music/browser. Verified against a Firefox
    # stream playing at the same time: target peak 5163, other process peak 1.
    stream = None
    try:
      from procloop import start_process_capture
      sup = start_process_capture(Cap.TARGET_EXE, buf.append, log=print)
      # Wait only for a real failure signal. "No buffers yet" is normal: the target
      # may not be running, and the supervisor attaches as soon as its pid appears.
      deadline = time.time() + 8.0
      while time.time() < deadline and not buf:
        if sup.last_error is not None:
          break
        if sup.capturing:
          break  # attached, simply quiet so far
        time.sleep(0.2)
      if sup.last_error is not None:
        sup.stop()
        raise sup.last_error
      capture_kind = f"WASAPI process loopback ({Cap.TARGET_EXE} only)"
    except Exception as e:
      print(f"process loopback unavailable ({e!r}) - falling back to system loopback",
            flush=True)
      # Last resort: system loopback via soundcard. Everything the default speaker
      # plays is captured here, so this is NOT Dota-only.
      # sounddevice 0.5.6 has no loopback flag, so soundcard owns this path.
      # Records 48k stereo -> mono 16k to match VAD/ASR.
      import threading, soundcard as sc
      def pump():
        # COM must be initialized per-thread for MediaFoundation loopback,
        # else Error 0x800401f0 (CO_E_NOTINITIALIZED) kills the recorder.
        try:
          import ctypes
          ctypes.windll.ole32.CoInitialize(None)
        except Exception:
          pass
        while True:
          try:
            spk = sc.default_speaker()
            lb = sc.get_microphone(spk.name, include_loopback=True)
            print(f"loopback device: {spk.name}", flush=True)
            with lb.recorder(samplerate=48000, channels=2, blocksize=4800) as rec:
              while True:
                data = rec.record(numframes=24000)  # 0.5s
                mono = data.mean(axis=1)
                n = len(mono) // 3 * 3
                if n:
                  buf.append(mono[:n].reshape(-1, 3).mean(axis=1).astype("float32"))
          except Exception as e:
            print(f"loopback error, retrying in 2s: {e}", flush=True)
            time.sleep(2)
      threading.Thread(target=pump, daemon=True).start()
      capture_kind = "system loopback (everything on the default speaker)"
  print(f"capture: {capture_kind}", flush=True)

  # --- typed chat, straight from Dota's Game State Integration ---------------
  # Same NLLB model as voice; no ASR involved, so these lines are instant.
  chat_listener = None
  _gsi = CFG.get("gsi") or {}
  _chatcfg = _gsi.get("chat") or {}
  if _chatcfg.get("enabled", True):
    try:
      import asyncio as _aio
      from gsichat import GsiChat, detect_lang
      _allowed = tuple((CFG.get("asr") or {}).get("languages") or ("en",))
      _loop = _aio.get_running_loop()

      def _chat_translate(text):
        lang = detect_lang(text, _allowed)
        return lang, (text if lang == "en" else mt_translate(text, lang))

      def _chat_line(msg):
        _loop.call_soon_threadsafe(
          lambda: _aio.ensure_future(broadcast_async(msg)))

      chat_listener = GsiChat(int(_gsi.get("port") or 5300), _chat_translate,
                              _chat_line, channels=_chatcfg.get("channels"),
                              dump_raw=bool(_gsi.get("dump_raw")),
                              events_enabled=bool((_gsi.get("events") or {}).get("enabled", True)),
                              hero_kills=bool((_gsi.get("events") or {}).get("hero_kills", False))).start()
    except Exception as _e:
      print(f"chat translation unavailable: {_e!r}", flush=True)

  print(f"live. gated on {Cap.TARGET_EXE}: listening only while it runs...", flush=True)
  # Utterance chunking: accumulate while speech, finalize on pause.
  # Old 1.2s sliding windows caused 3-word fragments + duplicate GPU work.
  SPEECH_MIN, SILENCE_END, MAX_UTTER = 1.0, 0.9, 6.0
  DOTA_PROMPT = ("Tidehunter Tide Roshan mid top bot gank stack pull ward smoke "
                 "missing ss carry support offlane farm push dive")
  utter = np.zeros(0, dtype=np.float32)
  silence = 0.0
  t_start = 0.0
  last_en, last_prompt = "", ""
  idle_n = 0
  n_piece, n_hit, n_utter = 0, 0, 0
  tick = 0
  def process(audio, prompt):
    t1 = time.time()
    segs, info = asr.transcribe(audio, language=None, vad_filter=False,
                                condition_on_previous_text=True,
                                initial_prompt=prompt)
    t2 = time.time()
    out = []
    skipped = 0
    for s in segs:
      # whisper hallucinates names/phrases on music/silence Ã¢â‚¬â€ drop low-confidence junk
      if getattr(s, "no_speech_prob", 0) > 0.6 or getattr(s, "avg_logprob", 0) < -1.0:
        skipped += 1
        continue
      txt = s.text.strip()
      low = txt.lower()
      # known fixed-string hallucinations ("Subtitles by DimaTorzok" etc.)
      if not txt or "torzok" in low or low in (
          "thank you for watching", "thanks for watching", "please subscribe",
          "bye", "...", "Ã‘ÂÃÂ¿ÃÂ°Ã‘ÂÃÂ¸ÃÂ±ÃÂ¾ ÃÂ·ÃÂ° ÃÂ¿Ã‘â‚¬ÃÂ¾Ã‘ÂÃÂ¼ÃÂ¾Ã‘â€šÃ‘â‚¬", "Ã‘ÂÃ‘Æ’ÃÂ±Ã‘â€šÃÂ¸Ã‘â€šÃ‘â‚¬Ã‘â€¹ Ã‘ÂÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ» dimatorzok"):
        skipped += 1
        continue
      # prompt echo: whisper sometimes repeats our vocab prompt on weak audio.
      # Genuine loud callouts pass via the no_speech gate below.
      nsp = getattr(s, "no_speech_prob", 0)
      if nsp > 0.3:
        words = low.split()
        pw = DOTA_PROMPT.lower().split()
        echo = False
        if len(words) >= 2:
          for i in range(len(pw) - len(words) + 1):
            if pw[i:i + len(words)] == words:
              echo = True
              break
        if not echo and len(words) >= 2 and len(set(words)) == 1 and words[0] in pw:
          echo = True  # e.g. "Tidehunter Tidehunter" on noise
        if echo:
          skipped += 1
          continue
      lang = (info.language or "en").lower()[:2]
      if lang not in CFG["asr"]["languages"]:
        continue
      en = txt if lang == "en" else mt_translate(txt, lang)
      out.append((lang, txt, en))
    return out, t1, time.time()
  while True:
    await __import__("asyncio").sleep(0.5)
    if not Cap.is_dota_running():
      idle_n += 1
      if idle_n == 2:
        print(f"{Cap.TARGET_EXE} not running Ã¢â‚¬â€ suspended, 0% GPU. Start it to resume.")
      buf.clear()
      utter = np.zeros(0, dtype=np.float32)
      silence = 0.0
      await __import__("asyncio").sleep(1.0)
      continue
    idle_n = 0
    if not buf:
      # no fresh audio: count silence against open utterance
      if len(utter):
        silence += 0.5
      else:
        continue
    else:
      chunk = np.concatenate(buf); buf.clear()
      # split into 0.5s pieces for VAD gating
      step = int(sr * 0.5)
      for off in range(0, len(chunk), step):
        piece = chunk[off:off + step]
        import torch
        ts = get_speech_timestamps(torch.from_numpy(piece), vad,
                                   sampling_rate=sr, min_speech_duration_ms=250)
        if ts:
          n_hit += 1
          if not len(utter):
            t_start = time.time() - len(chunk) / sr + off / sr
          utter = np.concatenate([utter, piece])
          silence = 0.0
        elif len(utter):
          utter = np.concatenate([utter, piece])
          silence += len(piece) / sr
        n_piece += 1
    ulen = len(utter) / sr
    tick += 1
    if tick % 20 == 0:
      print(f"stats: pieces={n_piece} vad_hits={n_hit} utterances={n_utter} open_utter={ulen:.1f}s", flush=True)
    if len(utter) and (ulen >= MAX_UTTER or (ulen >= SPEECH_MIN and silence >= SILENCE_END)):
      audio, utter = utter.copy(), np.zeros(0, dtype=np.float32)
      silence = 0.0
      n_utter += 1
      prompt = ((last_prompt + " " + DOTA_PROMPT)[-200:]) if last_prompt else DOTA_PROMPT
      (items, t_asr, t_end) = await __import__("asyncio").to_thread(process, audio, prompt)
      for lang, txt, en in items:
        if not txt or en == last_en or (last_en and en in last_en):
          continue  # drop overlap duplicates
        last_en = en
        last_prompt = txt[-200:]
        lag = t_end - (t_start or t_end)
        print(f"[{lang.upper()}] {txt} -> {en} (lag {lag:.1f}s)", flush=True)
        await broadcast_async({"ts": time.time(), "src": lang.upper(),
                               "src_text": txt, "en": en,
                               "passthrough": lang == "en", "lag": round(lag, 1)})
