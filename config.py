"""Configuracion de la app: rutas de salida, idiomas, formatos y FFmpeg.

Lo que NO vive aca a proposito:
  - La eleccion de modelo / device / precision -> hardware.py (depende del equipo
    y se resuelve de forma perezosa, no al importar).
  - La identidad y version de la app -> version.py.
"""
import shutil

import paths

# ── Datos del usuario (Documentos/Transcriber, ver paths.data_dir) ──
OUTPUT_DIR = paths.data_dir()

# ── FFmpeg: bundled (al lado del .exe) > sistema (PATH) ──
FFMPEG_BIN = paths.ffmpeg_path() or shutil.which("ffmpeg")

# ── Idiomas ──
# Espanol primero: es el default visual y el mas usado.
# Auto-detectar esta disponible pero no es default (confunde es/pt en audios cortos).
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
# Unica fuente de verdad: el filtro del dialogo y la validacion de drag & drop
# se derivan de esta tupla, para que no puedan divergir.
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".wma", ".aac", ".opus", ".webm")
AUDIO_FORMATS = (
    "Archivos de audio ("
    + " ".join(f"*{e}" for e in AUDIO_EXTS)
    + ");;Todos (*)"
)

# ── Etiqueta del modo automatico en el selector de modelo ──
MODEL_AUTO = "Automatico"

# ── Claves de QSettings (centralizadas para que no se escriban a mano) ──
SETTING_LANGUAGE = "language"
SETTING_SOURCE = "source"
SETTING_MODEL = "model"
SETTING_GEOMETRY = "geometry"
SETTING_TRAY_MESSAGE_SHOWN = "tray_message_shown"
SETTING_CPU_WARNING_SHOWN = "cpu_warning_shown"
SETTING_LAST_UPDATE_CHECK = "last_update_check"
SETTING_SKIPPED_VERSION = "skipped_version"

# Cada cuanto se consulta si hay version nueva. Mas seguido molesta sin aportar:
# los releases no salen varias veces por dia.
UPDATE_CHECK_INTERVAL_HOURS = 24
