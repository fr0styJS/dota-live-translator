# Third-party notices

This project's own code is MIT (see `LICENSE`). It downloads and runs other
people's models and libraries at runtime; no model weights are redistributed
here. Relevant terms:

## Models (downloaded at first run, not bundled)

| Model | Licence | Notes |
|---|---|---|
| `large-v3-turbo` (faster-whisper / OpenAI Whisper) | MIT | speech-to-text |
| `facebook/nllb-200-distilled-600M` | **CC-BY-NC-4.0 (non-commercial)** | machine translation |
| Silero VAD | MIT | speech detection |

The NLLB-200 model family is licensed **CC-BY-NC-4.0**, which forbids commercial
use. This repository therefore must not be offered as, or bundled into, a
commercial product while it depends on that model. Swap `mt.model` in
`config.yaml` for a permissively licensed translation model (e.g. an
Apache-2.0/MIT opus-mt checkpoint) if commercial use matters.

## Libraries

| Library | Licence |
|---|---|
| faster-whisper, CTranslate2 | MIT |
| transformers, accelerate, tokenizers | Apache-2.0 |
| torch (CUDA build) | BSD-3-Clause (with CUDA runtime EULA for the bundled runtime) |
| sounddevice | MIT |
| soundcard | BSD-3-Clause |
| comtypes | MIT |
| numpy | BSD-3-Clause |
| websockets | BSD-3-Clause |
| PyYAML | MIT |
| psutil | BSD-3-Clause |

## Trademarks

*Dota*, *Dota 2* and *Valve* are trademarks of Valve Corporation. This is an
unofficial, community project. It is not affiliated with, endorsed by, or
sponsored by Valve. It reads the game's audio locally through the Windows audio
APIs; it does not read or modify game memory, files or network traffic, and it
does not inject code into the game.

Check your league's or tournament's rules before using any third-party audio
aid in competitive play.
