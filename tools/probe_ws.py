import asyncio, websockets, json, sys
async def main():
  try:
    async with websockets.connect("ws://127.0.0.1:5112") as ws:
      for _ in range(3):
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        m = json.loads(raw)
        print(f"GOT [{m.get('src')}] {m.get('en','')[:80]} lag={m.get('lag')}", flush=True)
      print("WS-LIVE", flush=True)
  except Exception as e:
    print(f"WS-FAIL: {type(e).__name__} {e}", flush=True)
    sys.exit(1)
asyncio.run(main())
