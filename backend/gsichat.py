"""Read typed chat out of Dota 2's Game State Integration feed.

GSI pushes the whole recent event list on every tick, so a single chat line
arrives in many consecutive payloads - dedupe by (game_time, player, channel,
text). Verified on a live match 2026-11-14:

  {"event_type": "chat_message", "game_time": 1113, "player_id": 4,
   "channel_type": 12, "message": "tower"}

channel_type 12 = team chat, 11 = all chat (configurable via config.yaml ->
gsi.chat.channels). Messages from other players arrive too, but GSI only gives
their slot number, not a name.
"""
import http.server
import json
import re
import threading
import time
from collections import deque

CYRILLIC = re.compile(r"[\u0400-\u04FF]")
UK_CHARS = set("іїєґІЇЄҐ")

# English Dota shorthand: never worth language-detecting, always passthrough.
JARGON = {
  "omw", "omg", "gg", "wp", "k", "kk", "ok", "okay", "b", "bak", "brb", "afk",
  "ss", "miss", "misi", "ward", "wards", "tower", "rosh", "roshan", "gank",
  "push", "pull", "stack", "smoke", "mid", "top", "bot", "carry", "support",
  "offlane", "farm", "dive", "rune", "aghs", "bkb", "tp", "mana", "hp", "stun",
  "hex", "silence", "ult", "no", "yes", "why", "ggwp", "ez", "nice", "ty",
  "or", "and", "the", "pls", "please", "help", "wait", "go", "come", "now",
  "x", "d", "xd", "lol", "lmao", "ezzz", "hhh",
}
# Cypher-Cyrillic calls that are jargon, not prose.
RU_JARGON = {"б", "го", "мид", "топ", "бот", "пуш", "смоук", "ганг", "вард",
             "хук", "ульт", "тп", "хп", "мп"}
# Malay and Indonesian are close enough that detectors mix them; both translate
# fine with NLLB's ind_Latn.
LANG_ALIASES = {"ms": "id"}

# Chat is full of misspellings and furious typing ("twt", "X D", "cek ward").
# Translating that is noise, so only reasonably formed sentences are considered.
MIN_WORDS = 3
MIN_CHARS = 14
MIN_CONFIDENCE = 0.45
MIN_MARGIN = 0.08       # top language must beat the runner-up by this much

_lingua = None


def _detector():
  """lingua is markedly better than langdetect on 3-6 word messages."""
  global _lingua
  if _lingua is None:
    from lingua import Language, LanguageDetectorBuilder
    langs = [Language.RUSSIAN, Language.ENGLISH, Language.SPANISH,
             Language.UKRAINIAN, Language.TAGALOG, Language.PORTUGUESE,
             Language.INDONESIAN]
    _lingua = (LanguageDetectorBuilder.from_languages(*langs)
               .with_preloaded_language_models().build())
  return _lingua


_LINGUA_CODES = {"RUSSIAN": "ru", "ENGLISH": "en", "SPANISH": "es",
                 "UKRAINIAN": "uk", "TAGALOG": "tl", "PORTUGUESE": "pt",
                 "INDONESIAN": "id"}


def detect_lang(text: str, allowed=("ru", "en", "es", "uk", "tl", "pt", "id")) -> str:
  """Best-effort language for a chat line; 'en' means leave it exactly as typed.

  Deliberately conservative:
    * Cyrillic is decided by script (reliable even for one word),
    * short messages, abbreviations and all-jargon phrases are never translated -
      "cek ward", "twt", "X D", "gago ka" are calls or typos, not prose,
    * otherwise lingua must be confident and clear of the runner-up, because
      Spanish/Portuguese and Tagalog/Indonesian overlap badly on short text.
  """
  t = (text or "").strip()
  if not t:
    return "en"
  bare = re.sub(r"[^a-z0-9А-Яа-яЁёІіЇїЄєҐґ ]+", " ", t.lower()).strip()
  if not bare:
    return "en"

  if CYRILLIC.search(bare):
    if bare in RU_JARGON:
      return "en"
    return "uk" if any(ch in UK_CHARS for ch in bare) else "ru"

  words = bare.split()
  if len(words) < MIN_WORDS or len(bare) < MIN_CHARS:
    return "en"
  if all(w in JARGON for w in words):
    return "en"

  try:
    det = _detector()
    vals = sorted((( _LINGUA_CODES.get(v.language.name, "en"), v.value)
                   for v in det.compute_language_confidence_values(bare)),
                  key=lambda x: x[1], reverse=True)
    if not vals:
      return "en"
    lang, conf = vals[0]
    if lang == "en" or conf < MIN_CONFIDENCE:
      return "en"
    if len(vals) > 1 and (conf - vals[1][1]) < MIN_MARGIN:
      return "en"          # too close to call: show the original instead
    lang = LANG_ALIASES.get(lang, lang)
    return lang if lang in allowed else "en"
  except Exception:
    return "en"


class GsiChat:
  """Minimal HTTP listener for GSI that emits each new chat line once."""

  def __init__(self, port: int, translate, on_line, channels=None, log=print):
    """translate(text) -> (lang, english); on_line(dict) publishes a line."""
    self.port = int(port)
    self.translate = translate
    self.on_line = on_line
    self.channels = {int(k): str(v) for k, v in (channels or {12: "TEAM", 11: "ALL"}).items()}
    self.log = log
    self._seen = deque(maxlen=800)
    self._seen_set = set()
    self._server = None
    self._thread = None
    self.lines = 0

  # --- http side -----------------------------------------------------------
  def _handle(self, data: dict) -> None:
    # Who am I? A player's GSI feed only knows your own slot and hero; the names
    # of everyone else's heroes are not exposed (minimap units carry no slot).
    # player.player_slot is NOT usable here (it reported 6 for a radiant team_slot
    # 0); chat player_id is the global slot 0-9 = team_slot + 5 for Dire.
    pl = data.get("player") or {}
    try:
      offset = 5 if str(pl.get("team_name") or "").lower() == "dire" else 0
      me_slot = None if pl.get("team_slot") is None else int(pl["team_slot"]) + offset
    except (TypeError, ValueError):
      me_slot = None
    my_hero = ((data.get("hero") or {}).get("name") or "").replace("npc_dota_hero_", "")
    my_hero = my_hero.replace("_", " ").upper()
    for ev in (data.get("events") or []):
      if ev.get("event_type") != "chat_message":
        continue
      text = (ev.get("message") or "").strip()
      if not text:
        continue
      try:
        ch = int(ev.get("channel_type"))
      except (TypeError, ValueError):
        continue
      label = self.channels.get(ch)
      if label is None:
        continue  # channel we were not asked to translate
      key = (ev.get("game_time"), ev.get("player_id"), ch, text)
      if key in self._seen_set:
        continue
      self._seen.append(key)
      self._seen_set = set(self._seen)
      pid = ev.get("player_id")
      if pid is not None and me_slot is not None and pid == me_slot and my_hero:
        who = my_hero                      # your own line: your hero is known
      elif pid is not None:
        who = f"{label}·P{pid}"            # teammates/enemies: slot only
      else:
        who = label
      self._emit(who, pid, text, ev.get("game_time"))

  def _emit(self, who: str, player_id, text: str, game_time) -> None:
    try:
      lang, en = self.translate(text)
    except Exception as exc:
      self.log(f"chat translate failed: {exc!r}")
      return
    self.lines += 1
    self.on_line({
      "ts": time.time(),
      "src": (lang or "en").upper(),
      "src_text": text,
      "en": en if en else text,
      "passthrough": (lang == "en"),
      "source": who,
      "who": who,
      "player_id": player_id,
      "game_time": game_time,
      "kind": "chat",
    })

  def _serve(self) -> None:
    outer = self

    class Handler(http.server.BaseHTTPRequestHandler):
      def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
          outer._handle(json.loads(raw or b"{}"))
        except Exception as exc:
          outer.log(f"gsi chat parse error: {exc!r}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

      def log_message(self, *_a):
        pass

    try:
      self._server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
    except OSError as exc:
      self.log(f"chat listener could not bind :{self.port} ({exc}) - chat translation off")
      return
    self.log(f"chat listener: http://127.0.0.1:{self.port}/ "
             f"(labels {self.channels})")
    self._server.serve_forever()

  def start(self):
    self._thread = threading.Thread(target=self._serve, daemon=True, name="gsi-chat")
    self._thread.start()
    return self

  def stop(self) -> None:
    if self._server is not None:
      try:
        self._server.shutdown()
      except Exception:
        pass
