"""Dota terms that must never be literally translated."""
LOCK = {
  "ss", "miss", "missing", "rosh", "roshan", "gank", "b", "back",
  "push", "stack", "pull", "ward", "smoke", "dive", "farm",
  "mid", "top", "bot", "carry", "support", "offlane",
  "tide", "tidehunter", "th",
}

def protect(text: str) -> tuple[str, dict]:
  """Replace locked terms with placeholders before MT, restore after."""
  import re
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
