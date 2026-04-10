import os
import shutil
import logging

log = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Transcriber")

# ── Whisper ──
WHISPER_MODEL = "large-v3"

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

# ── FFmpeg ──
FFMPEG_BIN = shutil.which("ffmpeg")

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

os.makedirs(OUTPUT_DIR, exist_ok=True)
