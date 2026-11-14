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
import pathlib
import re
import threading
import time
from collections import deque

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROSTER_PATH = ROOT / "logs" / "roster.json"
SLOTS_PATH = ROOT / "logs" / "slots.json"
DUMP_PATH = ROOT / "logs" / "gsi-raw.json"

CYRILLIC = re.compile(r"[\u0400-\u04FF]")

# Game feed events worth one line in the overlay. Item purchases and pause
# chatter are deliberately absent: hundreds per match, all noise here.
TOP_INFO = {
  "roshan_killed": "Roshan killed",
  "aegis_picked_up": "Aegis picked up",
  "bounty_rune_pickup": "Bounty rune",
}
GENERIC_INFO = {
  "CHAT_MESSAGE_TOWER_KILL": "Tower destroyed",
  "CHAT_MESSAGE_GLYPH_USED": "Glyph used",
  "CHAT_MESSAGE_SCAN_USED": "Scan used",
  "CHAT_MESSAGE_SENTRY_WARD_KILLED": "Sentry ward killed",
}
GENERIC_KILLS = {
  "CHAT_MESSAGE_HERO_KILL": "hero kill",
  "CHAT_MESSAGE_STREAK_KILL": "killing spree",
}
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

  def __init__(self, port: int, translate, on_line, channels=None, log=print,
               dump_raw: bool = False, events_enabled: bool = True,
               hero_kills: bool = False):
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
    self.roster = {}        # hero -> team id, from visible minimap units
    self._roster_logged = None
    self.matchid = None
    self.dump_raw = bool(dump_raw)
    self.events_enabled = bool(events_enabled)
    self.hero_kills = bool(hero_kills)
    self._last_dump = 0.0
    self._slots_mtime = None
    self._slots = {}        # "0".."9" -> display name, written by tools/roster.py

  # --- http side -----------------------------------------------------------
  def _handle(self, data: dict) -> None:
    if self.dump_raw:
      now = time.time()
      if now - self._last_dump >= 5.0:
        self._last_dump = now
        try:
          DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
          DUMP_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except Exception:
          pass
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

    # Roster: every hero the minimap has shown, with its team. Enough to name the
    # ten heroes in the game - not enough to say which slot holds which (the feed
    # never links a hero to a player slot for a playing client).
    changed = False
    for v in (data.get("minimap") or {}).values():
      if not isinstance(v, dict):
        continue
      un = str(v.get("unitname") or "")
      if not un.startswith("npc_dota_hero"):
        continue
      hero = un.replace("npc_dota_hero_", "")
      team = v.get("team")
      if team is not None and self.roster.get(hero) != int(team):
        self.roster[hero] = int(team)
        changed = True
    mid = (data.get("map") or {}).get("matchid")
    if mid:
      self.matchid = str(mid)
    if changed and self.roster != self._roster_logged:
      self._roster_logged = dict(self.roster)
      self._write_roster()
      radiant = sorted(h for h, t in self.roster.items() if t == 2)
      dire = sorted(h for h, t in self.roster.items() if t == 3)
      self.log(f"roster seen ({len(self.roster)}/10): "
               f"RADIANT={radiant} DIRE={dire}")
    for ev in (data.get("events") or []):
      if ev.get("event_type") != "chat_message":
        if self.events_enabled:
          self._info_event(ev)
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
      named = self._named_slot(pid)
      if named:
        who = named                        # assigned in tools/roster.py
      elif pid is not None and me_slot is not None and pid == me_slot and my_hero:
        who = my_hero                      # your own line: your hero is known
      elif pid is not None:
        who = f"{label}·P{pid}"            # teammates/enemies: slot only
      else:
        who = label
      self._emit(who, pid, text, ev.get("game_time"))


  # --- roster / slot naming --------------------------------------------------
  def _write_roster(self) -> None:
    """Publish what we have seen so tools/roster.py can offer the right picks."""
    try:
      data = {
        "matchid": self.matchid,
        "radiant": sorted(h for h, t in self.roster.items() if t == 2),
        "dire": sorted(h for h, t in self.roster.items() if t == 3),
      }
      ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
      ROSTER_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception:
      pass

  def _named_slot(self, pid):
    """Display name for a chat slot, from logs/slots.json (per match)."""
    if pid is None:
      return None
    try:
      mtime = SLOTS_PATH.stat().st_mtime
    except OSError:
      self._slots, self._slots_mtime = {}, None
      return None
    if mtime != self._slots_mtime:
      self._slots_mtime = mtime
      try:
        raw = json.loads(SLOTS_PATH.read_text(encoding="utf-8"))
        if not self.matchid or str(raw.get("matchid") or "") in ("", self.matchid):
          self._slots = {str(k): v for k, v in (raw.get("names") or {}).items() if v}
        else:
          self._slots = {}          # map belongs to another match
      except Exception:
        self._slots = {}
    return self._slots.get(str(pid))

  def _info_event(self, ev) -> None:
    """One overlay line for an objective/kill event, deduped across ticks."""
    etype = ev.get("event_type")
    label = TOP_INFO.get(etype)
    raw_data = None
    if label is None and etype == "generic_event":
      raw_data = ev.get("data")
      try:
        inner = json.loads(raw_data or "{}")
      except Exception:
        return
      itype = inner.get("type")
      if itype in GENERIC_INFO:
        label = GENERIC_INFO[itype]
        who = self._named_slot(inner.get("playerid1"))
        if who and itype == "CHAT_MESSAGE_TOWER_KILL":
          label = f"Tower destroyed by {who}"
      elif itype in GENERIC_KILLS and self.hero_kills:
        k = self._named_slot(inner.get("playerid1")) or "?"
        v = self._named_slot(inner.get("playerid2")) or "?"
        label = (f"{k} killed {v}" if itype == "CHAT_MESSAGE_HERO_KILL"
                 else f"{k} on a {GENERIC_KILLS[itype]}")
      if label is None:
        return
    if label is None:
      return
    key = ("info", etype, ev.get("game_time"), raw_data or "")
    if key in self._seen_set:
      return
    self._seen.append(key)
    self._seen_set = set(self._seen)
    self.on_line({
      "ts": time.time(), "src": "INFO", "src_text": label, "en": label,
      "passthrough": True, "source": "INFO", "who": "INFO",
      "game_time": ev.get("game_time"), "kind": "info",
    })

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
