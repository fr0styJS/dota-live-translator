r"""Wait for a match to become readable, then write the slot -> hero map.

Valve publishes a match a few minutes after it ends (and OpenDota parses it some
time after that), so this polls both until the ten hero ids are available, then
writes logs\slots.json exactly like tools/match_roster.py.

  python tools\wait_match.py --match-id 9089738519 --minutes 40

Useful as a background step right after a game: the overlay switches from
TEAM-P4 to hero names as soon as the map lands (the backend applies slots.json
live, since the matchid matches).
"""
import argparse
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import match_roster as M  # noqa: E402


def main() -> int:
  ap = argparse.ArgumentParser(description="wait for a match, then map slot -> hero")
  ap.add_argument("--match-id", required=True)
  ap.add_argument("--minutes", type=float, default=40)
  ap.add_argument("--interval", type=float, default=90, help="seconds between attempts")
  a = ap.parse_args()

  key = M.read_key()
  if not key:
    print("no Steam Web API key found (see tools/match_roster.py --help)")
    return 2

  deadline = time.time() + a.minutes * 60
  attempt = 0
  while time.time() < deadline:
    attempt += 1
    stamp = time.strftime("%H:%M:%S")
    # nudge OpenDota's parser every few attempts, not every time
    if attempt % 4 == 1:
      print(f"{stamp} attempt {attempt}: asking OpenDota to parse {a.match_id}")
      if M.from_opendota(a.match_id, request_parse=True) == 0:
        return 0
    else:
      print(f"{stamp} attempt {attempt}")
      if M.from_match_details(key, a.match_id) == 0:
        return 0
    time.sleep(a.interval)

  print(f"gave up after {a.minutes:.0f} minutes; try again later with"
        f" tools\\match_roster.py --match-id {a.match_id}")
  return 1


if __name__ == "__main__":
  sys.exit(main())
