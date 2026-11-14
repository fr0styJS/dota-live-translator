"""Dota terms that must never be literally translated."""

import re

# English calls: protected with placeholders, because MT models ruin them.
# Only used for Latin-script text - see protect().
LOCK = {
  "ss", "miss", "missing", "rosh", "roshan", "gank", "b", "back",
  "push", "stack", "pull", "ward", "smoke", "dive", "farm",
  "mid", "top", "bot", "carry", "support", "offlane",
  "tide", "tidehunter", "th",
}

# Cyrillic game slang -> the English call it means.
#
# Measured with NLLB (ru->en), raw vs pre-substituted:
#   "пуш сейчас или фармим?"        raw "Now or tomorrow?"         sub "push now or farm?"
#   "идём на мид, они без ульты"    raw "they're not wearing a suit" sub "they're not ult"
#   "го смок, ганк топ"             raw "♪ Go smoke, go top ♪"      sub "Go smoke, gank top"
# So for Cyrillic text we substitute the English call directly and translate - no
# placeholder tokens, which NLLB mangles when they sit inside Russian sentences.
RU_SLANG = {
  "пуш": "push", "пушим": "push", "пушить": "push", "пушат": "push",
  "пушните": "push", "пуша": "push",
  "фарм": "farm", "фармим": "farm", "фармить": "farm", "фармлю": "farm",
  "фарми": "farm", "фармил": "farm",
  "мид": "mid", "миду": "mid", "мида": "mid", "миде": "mid",
  "топ": "top", "топу": "top", "топа": "top", "топе": "top",
  "бот": "bot", "боту": "bot", "бота": "bot", "боте": "bot",
  "ульт": "ult", "ульта": "ult", "ульты": "ult", "ульту": "ult",
  "ультим": "ult", "ультой": "ult",
  "смок": "smoke", "смоук": "smoke", "смоукнулись": "smoke", "смокнулись": "smoke",
  "ганг": "gank", "гангим": "gank", "гангнуть": "gank", "гангаем": "gank",
  "ганк": "gank", "ганка": "gank", "ганком": "gank", "ганкнуть": "gank",
  "вард": "ward", "варды": "wards", "вардим": "ward", "вардни": "ward",
  "рош": "rosh", "роша": "rosh", "рошан": "roshan", "рошана": "roshan",
  "тп": "tp", "тпшся": "tp", "тпшусь": "tp", "тпнулся": "tp",
  "хук": "hook", "хука": "hook", "хуком": "hook",
  "б": "back", "бэк": "back", "го": "go", "гоу": "go",
  "мис": "miss", "мисс": "miss", "мисует": "miss", "мисуй": "miss",
  "стан": "stun", "станит": "stun",
  "хайд": "hide", "хайдимся": "hide",
  "кат": "cut", "резать": "cut",
  "деф": "defend", "дефаем": "defend", "защита": "defend",
  "инвейд": "invade", "инвейдим": "invade",
}

CYRILLIC = re.compile(r"[\u0400-\u04FF]")


def protect(text: str) -> tuple[str, dict]:
  """Prepare text for MT.

  Latin text: locked calls become placeholders (restore() puts them back).
  Cyrillic text: slang becomes its English call directly - proven better than
  placeholders, which NLLB shreds inside Russian sentences - so nothing to restore.
  """
  if CYRILLIC.search(text):
    out = text
    for w in sorted(RU_SLANG, key=len, reverse=True):
      out = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])", RU_SLANG[w], out,
                   flags=re.IGNORECASE)
    return out, {}

  slots: dict = {}
  out = text
  counter = [0]
  for w in sorted(LOCK, key=len, reverse=True):
    pat = re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)

    def _repl(m):
      token = f"__DOTA{counter[0]}__"
      slots[token] = m.group(0)  # preserve original case
      counter[0] += 1
      return token

    out = pat.sub(_repl, out)
  return out, slots


def restore(text: str, slots: dict) -> str:
  for k, v in slots.items():
    text = text.replace(k, v)
  return text
