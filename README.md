# Transcriber

App de escritorio Windows para transcribir audio a texto con Whisper (offline, local).

- Graba el audio del sistema (loopback WASAPI) o un microfono.
- Empaquetada como **portable** (copias la carpeta y funciona en cualquier Windows).
- Detecta tu hardware (GPU/CPU + RAM); el modelo Whisper esta fijo en `large-v3`.
- FFmpeg bundled, sin dependencias externas en la version distribuida.

## Para usuarios finales

Bajate la carpeta `Transcriber/` (zipeada). Doble click en `Transcriber.exe`.

Documentacion de uso: `USER_README.txt` (incluido en el zip).

## Para desarrolladores

### Componentes

| Archivo | Proposito |
|---|---|
| `main.py` | Entry point (UI con PyQt6, threads de procesamiento). |
| `paths.py` | Dual-mode portable/estandar (HF_HOME side effect). |
| `state.py` | Migraciones de layout, dedupe de modelos, sesiones. |
| `utils.py` | Helpers (NO_WINDOW, resource_path, same_path). |
| `config.py` | Modelo Whisper, idiomas, FFmpeg path, OUTPUT_DIR. |
| `hardware.py` | Deteccion VRAM/RAM/CUDA. |
| `audio_capture.py` | Grabacion loopback WASAPI + microfono (pyaudiowpatch). |
| `transcriber.py` | Wrapper de faster-whisper, build_srt. |
| `build.py` | Helper: descarga FFmpeg + corre PyInstaller. |
| `Transcriber.spec` | Spec PyInstaller (onedir, sin UPX). |
| `start.bat` | Script de arranque dev (crea venv, instala deps, lanza). |
| `requirements.txt` | Dependencias Python. |
| `USER_README.txt` | Guia para el usuario final (se copia al .exe distribuible). |

### Setup local (Windows)

```cmd
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pythonw main.py
```

Necesitas FFmpeg en el PATH (`winget install Gyan.FFmpeg`) si no haces el build portable.

O directamente con `start.bat` que automatiza esos pasos.

### Empaquetar (portable)

```cmd
venv\Scripts\python build.py
```

Salida: `dist/Transcriber/` con todo lo necesario (incluido `bin/ffmpeg.exe` + `portable.txt`). Zipeala y compartila.

### Configuracion

La configuracion va en `config.py`. La app guarda settings de usuario (idioma, fuente, geometria) en `settings.ini` dentro del directorio del modo activo:
- Portable: `<app>/_sistema/settings.ini`
- Estandar: `%LOCALAPPDATA%\Transcriber\settings.ini`

**No commitear secretos** — usar variables de entorno; los runtime files estan en `.gitignore`.

### Notas tecnicas

- **PyInstaller onedir** (no onefile): arranque rapido, una sola carpeta distribuible.
- **HF_HOME** se setea a la carpeta de modelos antes de importar `faster_whisper`, manteniendo el cache portable.
- **AppUserModelID** seteado via `ctypes` para que la barra de tareas Windows muestre la identidad propia (no se agrupa bajo Python).
- **Single-instance**: lock per-user via `QLocalServer` (evita doble launch).
- **System tray**: cerrar la ventana minimiza; salida real desde el menu del icono de bandeja.
- **Modo dual portable/estandar**: detectado por la presencia de `portable.txt` junto al `.exe`.
- **Layout de sesiones**: `<date>/transcripcion-N/audio.mp3 + transcripcion.txt + transcripcion.srt`.
- **Auto-dedupe** de modelos cross-cache (HF default + LOCALAPPDATA + portable).
- **Race condition** del modelo: `Transcriber.load_model()` usa un Lock.

### Reportar bugs / solicitar features

Ver `SECURITY.md` para reportes de vulnerabilidades. Para bugs y features usar el issue tracker del repo.

### Limitaciones conocidas

- Solo Windows (`pyaudiowpatch` para grabacion loopback es Windows-only).
- Sin firma de codigo: SmartScreen advierte la primera vez.
- Sin auto-update.
- Modelo se descarga de HuggingFace en la primera ejecucion (~3 GB para `large-v3`).
