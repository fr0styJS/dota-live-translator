# Dota Live Translator

Local, real-time voice translation for Dota 2 voice chat and tournament casters.
Subtitles appear in an overlay over the game, or on a second-monitor page.

**Everything runs on your machine.** No audio, text or telemetry leaves the PC -
the only network traffic is the one-off model download from Hugging Face.

```
Dota 2 audio (WASAPI process loopback, this game only)
  -> Silero VAD (CPU, drops silence)
  -> faster-whisper large-v3-turbo (CUDA, int8_float16)
  -> NLLB-200-distilled-600M (CUDA)          [EN passes through untranslated]
  -> glossary lock (game terms never translated)
  -> websocket -> overlay + second-monitor page
```

Measured on an RTX 4070: ~2-4 s lag for a finished utterance, ~3-4 GB VRAM.

## Requirements

| | |
|---|---|
| OS | Windows 11 (build 20348+; WASAPI process loopback) |
| GPU | NVIDIA, ~4 GB free VRAM (CUDA 12.6 torch build, driver ~560+) |
| Python | 3.12 |
| Disk | ~3 GB models + ~5 GB venv |
| Game | Dota 2, voice chat enabled, a language in `config.yaml` |

CPU-only is possible but slow: set `asr.device` and `mt.device` to `cpu` in
`config.yaml`.

## Install

```powershell
git clone <repo> dota-translate
cd dota-translate
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` creates `.venv`, installs `requirements.txt` (CUDA torch), checks
CUDA, and warms up (downloads) the models. Useful flags:

```powershell
... -SkipModels      # install deps only, download models on first live run
... -Autostart       # add logon shortcut + minute watchdog (see below)
... -MockTest        # run the no-GPU, no-Dota smoke test afterwards
... -Force           # recreate the venv
```

## Run

```powershell
.venv\Scripts\python.exe backend\app.py           # live: waits for Dota 2
.venv\Scripts\python.exe backend\app.py --mock    # scripted demo, no models
.venv\Scripts\python.exe ui-overlay\overlay.py    # in-game subtitle overlay
.venv\Scripts\python.exe ui-desktop\app.py        # status window / launcher
```

The overlay is a normal window: **drag its edges** to show more or fewer lines
(rows follow the height, one line per utterance), and the size is remembered in
`logs\overlay.state.json`. A pinned header always states how many translation lines are currently rendered.
`ui.overlay_lines` in `config.yaml` only sets the height on first run.

- Second-monitor page: <http://127.0.0.1:5111>
- WebSocket feed: `ws://127.0.0.1:5112` (JSON: `src`, `src_text`, `en`, `lag`)
- `--port N` overrides the HTTP port (WS = N+1).

The backend is idle (0% GPU) until `dota2.exe` is running, and stops
translating the moment it closes.

## Autostart (optional)

`setup.ps1 -Autostart`, or `tools\install_autostart.ps1`, installs:

1. a Startup shortcut that runs the watcher hidden at logon;
2. a scheduled task `DotaTranslatorWatchdog` that restarts it within a minute if
   it dies.

Then just open Dota: backend + overlay start within ~5 s (plus model load), and
are reaped ~10 s after the game closes. Remove both with
`tools\install_autostart.ps1 -Remove`.

The watcher (`tools/watch_dota.py`) is headless and holds a single-instance
mutex, so duplicate launches exit instead of competing. It logs to
`logs/watch.log`; `logs/watch.heartbeat` is rewritten every 5 s as a liveness
check.

## Which audio is captured

Default is **only the game**: `backend/procloop.py` uses WASAPI *process*
loopback (`ActivateAudioInterfaceAsync` + `VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK`),
so Dota's audio and nothing else - Discord, music and browsers are excluded even
while they are playing. Verified by capturing a browser stream and the game at
the same moment: the game stream carried audio, every idle browser process
measured noise floor.

Two alternatives exist in `backend/capture.py`:

| Setup | Hears |
|---|---|
| no virtual cable (default) | only `dota2.exe` + its children (process loopback) |
| VB-Cable installed, Dota output set to `CABLE Input` | only what Dota sends to the cable (takes precedence) |
| process loopback unavailable | system loopback: everything on the default speaker (logged as a fallback) |

`python tools\audio_probe.py 3` prints the peak level of every process of an app,
which is the quickest way to find out whether an app is really rendering audio.

Implementation notes worth knowing before you touch `procloop.py`:

- the activation completion handler **must** implement `IAgileObject`, or
  `ActivateAudioInterfaceAsync` fails with `E_ILLEGAL_METHOD_CALL` (0x8000000E);
- `GetMixFormat`/`IsFormatSupported` are `E_NOTIMPL` on this audio client, so the
  format is hardcoded 44.1 kHz/16-bit/stereo + `AUTOCONVERTPCM`;
- activation must run on an MTA thread;
- an app with no render stream yields zero-filled buffers, so judge a stream by
  peak amplitude, not by whether buffers arrive.

## Configuration (`config.yaml`)

| Key | Meaning |
|---|---|
| `asr.model`, `asr.compute_type`, `asr.device` | whisper model + precision + device |
| `asr.languages` | languages accepted from ASR; anything else is dropped |
| `mt.model`, `mt.device` | translation model + device |
| `mt.target` | target language (default `eng_Latn`) |
| `dota.process` | process that gates capture (`dota2.exe`) |
| `server.port` | HTTP port; WS is port+1 |
| `glossary_lock` | game terms that must never be translated literally |

`backend/glossary.py` also protects a built-in Dota vocabulary (ss, rosh, gank,
ward, smoke, ...) by substituting placeholders before translation.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ERROR: config asks for cuda but torch sees no GPU` | wrong torch build or no NVIDIA GPU; reinstall requirements, or set both `device` values to `cpu` |
| nothing is transcribed, log says `suspended` | `dota2.exe` not running (that is the gate) |
| log shows `system loopback` instead of `process loopback` | activation failed (Windows too old, or the app renders in exclusive mode); the game's audio is the fallback's job - try a VB-Cable route |
| `port 5111 in use` | another backend is running: close it, or use `--port` |
| no subtitle window | overlay is a separate process: `ui-overlay\overlay.py`; it pops up bottom-centre of the primary screen |
| repeated console windows flashing | see `tools/procwatch.ps1` to identify the spawner; this was caused by shelling out to console apps from a windowless process |
| two python processes per launch | your Python install's venv template is the `py.exe` launcher instead of the interpreter - re-run `setup.ps1`, which restores stock binaries in `.venv\Scripts` |

Logs live in `logs/` (`backend.log`, `watch.log`, `watch.heartbeat`,
`watchdog.log`, `watch.fault.log`).

## Development

```powershell
.venv\Scripts\python.exe tools\test_mock.py     # HTTP + WS smoke test (no GPU)
.venv\Scripts\python.exe tools\test_ports.py    # double-start guard
.venv\Scripts\python.exe tools\audio_probe.py 3 # per-process audio levels
```

See `NOTICE.md` for third-party licences - notably **NLLB-200 is CC-BY-NC-4.0
(non-commercial)** - and the unofficial/Valve trademark disclaimer.

MIT licensed (`LICENSE`).

## Credits

Built by **Fr0styDev**. Written with substantial AI assistance from the
**DeepSeek V4.1 Flash 1017** agent in OpenCode - the WASAPI process-loopback
capture, the watcher/watchdog tooling and most of this documentation came from
it. Disclosed for transparency (and because some jurisdictions require human
authorship for copyright); licensing is unaffected.
