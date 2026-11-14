r"""Fill the slot -> hero map from Valve's Web API (post-match, and sometimes live).

Sources, best first:
  --live              GetTopLiveGame: only featured/high-MMR games are listed
  --match-id N        GetMatchDetails: any published match, once it has ended
  (default)           your most recent match via GetMatchHistory (needs the account)

Result is written to logs\slots.json, which the backend applies immediately (it is
ignored when the matchid does not match, so leaving it around is safe).

Requirements: the account must have "Expose Public Match Data" enabled in Dota 2
(Settings -> Social). With it off, Valve answers status 15 / HTTP 500 and no match
data exists for anyone to read.

A Steam Web API key is required for the Valve endpoints (free at
https://steamcommunity.com/dev/apikey). Provide it in this order:
  1. env STEAM_API_KEY
  2. %USERPROFILE%\.dota-translator\steam_api_key.txt   (outside the repo)
  3. logs\steam_api_key.txt                            (gitignored)
Never put a key in the repo or in a chat message.
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
SLOTS = LOGS / "slots.json"
HEROES_CACHE = LOGS / "heroes.json"
KEY_FILES = [pathlib.Path(os.path.expanduser("~")) / ".dota-translator" / "steam_api_key.txt",
             LOGS / "steam_api_key.txt"]
STEAM_API = "https://api.steampowered.com"
OPENDOTA_HEROES = "https://api.opendota.com/api/heroes"
UA = {"User-Agent": "dota-live-translator/1.0"}
STATUS_PRIVATE = 15


def read_key() -> str | None:
  env = os.environ.get("STEAM_API_KEY")
  if env and env.strip():
    return env.strip()
  for p in KEY_FILES:
    try:
      v = p.read_text(encoding="utf-8").strip()
      if v:
        return v
    except OSError:
      continue
  return None


def fetch_json(url: str, timeout=25) -> dict:
  req = urllib.request.Request(url, headers=UA)
  try:
    with urllib.request.urlopen(req, timeout=timeout) as r:
      return json.loads(r.read().decode("utf-8", "replace"))
  except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")[:120]
    hint = ""
    if e.code == 500:
      hint = ("  (a 500 from GetMatchDetails usually means the match is not published:\n"
              "   Expose Public Match Data off, or the match has not been recorded)")
    elif e.code in (401, 403):
      hint = "  (key rejected - check it was copied whole)"
    raise RuntimeError(f"HTTP {e.code} from {url.split('?')[0]}{hint}") from None


def heroes(key: str | None = None) -> dict[int, str]:
  """hero_id -> name. Cached; Valve's list with a key, OpenDota without one."""
  try:
    raw = json.loads(HEROES_CACHE.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}
  except Exception:
    pass
  mapping: dict[int, str] = {}
  if key:
    try:
      q = urllib.parse.urlencode({"key": key, "language": "english"})
      data = fetch_json(f"{STEAM_API}/IEconDOTA2_570/GetHeroes/v1/?{q}")
      for h in (data.get("result") or {}).get("heroes") or []:
        mapping[int(h["id"])] = h.get("localized_name") or h.get("name") or str(h["id"])
    except Exception:
      mapping = {}
  if not mapping:
    for h in fetch_json(OPENDOTA_HEROES):
      mapping[int(h["id"])] = h.get("localized_name") or h.get("name") or str(h["id"])
  LOGS.mkdir(parents=True, exist_ok=True)
  HEROES_CACHE.write_text(json.dumps(mapping, indent=1), encoding="utf-8")
  return mapping


def hero_name(hero_id: int, names: dict[int, str]) -> str:
  return str(names.get(int(hero_id) or 0, f"hero {hero_id}")).upper()


def slot_of(player_slot: int) -> int:
  """Web API uses 0-4 for Radiant and 128-132 for Dire; chat uses 0-9."""
  ps = int(player_slot)
  return ps - 128 + 5 if ps >= 128 else ps


def save(match_id: str, names_by_slot: dict[str, str]) -> None:
  LOGS.mkdir(parents=True, exist_ok=True)
  SLOTS.write_text(json.dumps({"matchid": str(match_id), "names": names_by_slot}, indent=1),
                   encoding="utf-8")
  print(f"wrote {SLOTS} for match {match_id}")
  for slot in sorted(names_by_slot, key=int):
    print(f"  P{slot}: {names_by_slot[slot]}")


def account_id_from_capture() -> str | None:
  """The player's account id appears in the GSI payload the backend dumps."""
  try:
    raw = json.loads((LOGS / "gsi-raw.json").read_text(encoding="utf-8"))
    acct = ((raw.get("player") or {}).get("accountid"))
    return str(acct) if acct else None
  except Exception:
    return None


def from_match_details(key: str, match_id: str) -> int:
  q = urllib.parse.urlencode({"key": key, "match_id": match_id})
  try:
    d = (fetch_json(f"{STEAM_API}/IDOTA2Match_570/GetMatchDetails/v1/?{q}") or {}).get("result") or {}
  except RuntimeError as e:
    print(str(e))
    return 1
  players = d.get("players") or []
  if not players:
    print("no players in that match: not published, or the account's data is private")
    return 1
  names = heroes(key)
  mapping = {str(slot_of(p.get("player_slot", 0))): hero_name(p.get("hero_id", 0), names)
             for p in players}
  save(match_id, mapping)
  return 0


def latest_match(key: str, account: str | None) -> int:
  if not account:
    account = account_id_from_capture()
  if not account:
    print("need --account-id (or a GSI capture with the player's accountid)")
    return 2
  q = urllib.parse.urlencode({"key": key, "account_id": account, "matches_requested": 1})
  try:
    res = (fetch_json(f"{STEAM_API}/IDOTA2Match_570/GetMatchHistory/v1/?{q}") or {}).get("result") or {}
  except RuntimeError as e:
    print(str(e))
    return 1
  if res.get("status") == STATUS_PRIVATE:
    print(f'account {account}: match history is private -> enable "Expose Public Match Data"'
          " (Dota 2 -> Settings -> Social), then play one match")
    return 1
  matches = res.get("matches") or []
  if not matches:
    print(f"account {account}: no matches published yet")
    return 1
  return from_match_details(key, str(matches[0]["match_id"]))


def from_top_live(key: str, want_match: str | None) -> int:
  """Only featured/high-MMR games appear here - worth a try, often empty."""
  q = urllib.parse.urlencode({"key": key, "partner": 0})
  try:
    d = (fetch_json(f"{STEAM_API}/IDOTA2Match_570/GetTopLiveGame/v1/?{q}") or {}).get("result") or {}
  except RuntimeError as e:
    print(str(e))
    return 1
  games = d.get("game_list") or []
  print(f"live games listed: {len(games)}")
  names = heroes(key)
  for g in games:
    mid = str(g.get("match_id") or g.get("lobby_id") or "?")
    if want_match and want_match != mid:
      continue
    players = g.get("players") or []
    if not players:
      continue
    mapping = {str(slot_of(p.get("player_slot", 0))): hero_name(p.get("hero_id", 0), names)
               for p in players}
    print(f"match {mid}: {len(players)} players")
    save(mid, mapping)
    return 0
  print("your match is not in the top-live list (high-MMR/featured games only)")
  return 1


def main() -> int:
  ap = argparse.ArgumentParser(description="slot -> hero map from the Steam Web API")
  ap.add_argument("--live", action="store_true", help="try GetTopLiveGame")
  ap.add_argument("--match-id", help="fetch that finished match")
  ap.add_argument("--account-id", help="steam32 account id for --latest")
  ap.add_argument("--latest", action="store_true", help="your most recent match")
  a = ap.parse_args()

  key = read_key()
  if not key:
    print("no Steam Web API key found. Put it in one of:")
    for p in KEY_FILES:
      print(f"  {p}")
    print("  or set STEAM_API_KEY. Free key: https://steamcommunity.com/dev/apikey")
    return 2
  if a.live:
    return from_top_live(key, a.match_id)
  if a.match_id:
    return from_match_details(key, a.match_id)
  return latest_match(key, a.account_id)


if __name__ == "__main__":
  sys.exit(main())
