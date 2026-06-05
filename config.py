import os
import shutil
import logging

import paths
import hardware

log = logging.getLogger(__name__)

# ── Datos del usuario (siempre Documents/Transcriber, ver paths.data_dir) ──
OUTPUT_DIR = paths.data_dir()


# ── Whisper: device (GPU si hay CUDA, sino CPU) ──
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


# ── Whisper: modelo auto-seleccionado segun el hardware de ESTA PC ──
# La app elige el mejor modelo que entra en la GPU/CPU detectada (ver hardware.recommend_model):
#   GPU grande -> large-v3 ; GPU mediana/chica -> medium/small/base ; sin GPU -> small/base/tiny.
# Asi funciona bien en cualquier PC sin quedarse sin memoria. Se puede forzar uno fijo
# con la variable de entorno TRANSCRIBER_MODEL (util para testing/debug).
# Reusa el device ya detectado para no consultar CUDA dos veces al arranque.
def _select_model():
    override = os.environ.get("TRANSCRIBER_MODEL")
    if override:
        log.info("Modelo forzado via TRANSCRIBER_MODEL=%s", override)
        return override
    try:
        m = hardware.recommend_model(cuda=(WHISPER_DEVICE == "cuda"))
        log.info("Modelo auto-seleccionado segun hardware: %s", m)
        return m
    except Exception:
        log.warning("No se pudo auto-seleccionar modelo; uso large-v3 por defecto", exc_info=True)
        return "large-v3"


WHISPER_MODEL = _select_model()

# ── FFmpeg: bundled (al lado del .exe) > sistema (PATH) ──
FFMPEG_BIN = paths.ffmpeg_path() or shutil.which("ffmpeg")

# ── Idiomas ──
# Español primero -> es el default visual + el mas usado.
# Auto-detectar disponible pero NO default (se confunde es/pt en audios cortos).
LANGUAGES = {
    "Español": "es",
    "Auto-detectar": None,
    "English": "en",
    "Português": "pt",
    "Français": "fr",
    "Deutsch": "de",
    "Italiano": "it",
}

# ── Formatos de audio soportados ──
AUDIO_FORMATS = "Archivos de audio (*.mp3 *.wav *.m4a *.ogg *.flac *.wma *.aac *.opus *.webm);;Todos (*)"
