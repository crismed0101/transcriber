import os
import shutil
import logging

import paths

log = logging.getLogger(__name__)

# ── Datos del usuario (carpeta segun modo portable o estandar) ──
OUTPUT_DIR = paths.data_dir()

# ── Whisper ──
# Modelo siempre el mas potente; sobreescribible via env var para testing.
WHISPER_MODEL = os.environ.get("TRANSCRIBER_MODEL", "large-v3")


def _detect_device():
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    log.warning("CUDA no disponible, usando CPU (sera mas lento)")
    return "cpu", "int8"


WHISPER_DEVICE, WHISPER_COMPUTE_TYPE = _detect_device()

# ── FFmpeg: bundled (modo portable) > sistema ──
FFMPEG_BIN = paths.ffmpeg_path() or shutil.which("ffmpeg")

# ── Idiomas ──
LANGUAGES = {
    "Auto-detectar": None,
    "Español": "es",
    "English": "en",
    "Português": "pt",
    "Français": "fr",
    "Deutsch": "de",
    "Italiano": "it",
}

# ── Formatos de audio soportados ──
AUDIO_FORMATS = "Archivos de audio (*.mp3 *.wav *.m4a *.ogg *.flac *.wma *.aac *.opus *.webm);;Todos (*)"
