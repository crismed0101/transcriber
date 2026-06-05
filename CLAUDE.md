# CLAUDE.md

Guía operativa para que cualquier instancia de Claude Code entienda este repo en 60 segundos.

## Qué es

App de escritorio Windows que transcribe audio en tiempo real capturando el loopback del sistema (lo que sale por los altavoces) y opcionalmente el micrófono, con Whisper local en GPU. Output a `transcripciones/`. Todo local, sin cloud.

## Stack

- **UI:** PyQt6 ≥ 6.7
- **Audio:** `pyaudiowpatch` ≥ 0.2.12 — fork de PyAudio con loopback WASAPI (sin VB-Cable ni Stereo Mix).
- **ASR:** `faster-whisper` ≥ 1.1 (CTranslate2, 4-5× más rápido que openai-whisper).
- **GPU:** CUDA 12 vía `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` (wheels oficiales). NVIDIA requerida.
- **Numpy:** ≥ 2.0
- **Empaquetado:** PyInstaller (`build.py`) en modo **onedir** → carpeta `dist/Transcriber/` (`Transcriber.exe` + `_internal/` + `bin/` con FFmpeg). El `.exe` NO corre suelto, necesita su carpeta. Distribución vía instalador **Inno Setup** (`Transcriber.iss`; `python build.py --installer` → `installer/Transcriber-Setup.exe`, instala por-usuario sin admin).

## Layout

```
transcriber/
├── requirements.txt
├── build.py                ← empaqueta a Transcriber.exe
├── <fuentes>.py            ← UI + worker
├── bin/                    ← FFmpeg (gitignored, lo baja build.py)
├── models/                 ← Whisper weights cacheados (gitignored)
├── transcripciones/        ← output runtime (gitignored)
├── _sistema/, output/, data/  ← runtime (gitignored)
├── settings.ini            ← config (gitignored)
└── venv/
```

## Convenciones / decisiones

- **`pyaudiowpatch`, no `pyaudio`.** Mainline no tiene loopback WASAPI. No migrar al upstream.
- **`faster-whisper`, no `openai-whisper`.** Decisión deliberada por velocidad. Si se sugiere `whisper.cpp` o el paquete oficial, preguntar antes.
- **GPU NVIDIA asumida.** Si no hay CUDA, cae a CPU (`config._detect_device`) pero **avisa al usuario** con un cartel (`main._maybe_warn_cpu`) — no es silencioso. El modelo se auto-selecciona según el hardware (`hardware.recommend_model` vía `config._select_model`); override con env var `TRANSCRIBER_MODEL`.
- **Output a `transcripciones/`** (español). No renombrar a `transcripts/`.
- **FFmpeg bundleado**, no requerido en PATH.
- **Sin telemetría, sin red.** No agregar llamadas a APIs externas.

## Cómo desarrollar

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python <main>.py
python build.py    # → Transcriber.exe
```

Para validar loopback: reproducir audio y chequear que aparezcan devices `[Loopback]` en la lista. `pyaudiowpatch` los expone como input espejo de los output.

## Limitaciones

1. Solo Windows (WASAPI).
2. NVIDIA only.
3. Modelo se baja al primer run (requiere internet).
4. Latencia ≈ chunk + tamaño de modelo. `large-v3` es más preciso pero más lag en streaming.

## Antes de tocar algo

- **`requirements.txt`** — pins atados a versiones compatibles entre `faster-whisper` y las wheels CUDA. No bumpear a ciegas.
- **`build.py`** — si cambia URL de FFmpeg o bundling, validar el `.exe` en máquina limpia sin Python.
- **Estado del repo** — actualmente solo `requirements.txt` + `.gitignore`. El código fuente puede estar WIP o aún no committeado. Antes de asumir layout, hacer `ls` y leer lo que exista.
