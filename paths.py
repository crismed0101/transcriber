"""Manejo de paths con dual-mode: portable o estandar Windows.

Modo portable (PortableApps convention):
  Activado si existe <app>/portable.txt junto al ejecutable.
  Todos los datos viven al lado del .exe (USB-friendly, todo viaja junto).
    data_dir   = <app>/transcripciones/
    system_dir = <app>/_sistema/

Modo estandar (Windows convention):
  Default cuando no esta el marker. Sigue las Known Folders de Microsoft:
    data_dir   = ~/Documents/Transcriber/      (transcripciones del usuario)
    system_dir = %LOCALAPPDATA%/Transcriber/   (logs, settings, modelos)

Importar este modulo SETEA HF_HOME / HUGGINGFACE_HUB_CACHE para que faster_whisper
descargue los modelos al directorio correcto. Debe importarse ANTES que faster_whisper.
"""
import os
import sys

PORTABLE_MARKER = "portable.txt"


def is_frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    """Carpeta donde esta el .exe en frozen mode, o el codigo fuente en dev."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def is_portable():
    """Modo portable activo si existe <app>/portable.txt."""
    return os.path.isfile(os.path.join(app_dir(), PORTABLE_MARKER))


def data_dir():
    """Donde van las transcripciones del usuario."""
    if is_portable():
        d = os.path.join(app_dir(), "transcripciones")
    else:
        d = os.path.join(os.path.expanduser("~"), "Documents", "Transcriber")
    os.makedirs(d, exist_ok=True)
    return d


def system_dir():
    """Donde van log, settings y modelos."""
    if is_portable():
        d = os.path.join(app_dir(), "_sistema")
    else:
        appdata = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        d = os.path.join(appdata, "Transcriber")
    os.makedirs(d, exist_ok=True)
    return d


def models_dir():
    """Cache de modelos Whisper -> <system_dir>/models/."""
    d = os.path.join(system_dir(), "models")
    os.makedirs(d, exist_ok=True)
    return d


def bin_dir():
    """Carpeta con binarios bundled (ffmpeg)."""
    return os.path.join(app_dir(), "bin")


def ffmpeg_path():
    """Ruta a ffmpeg.exe bundled, o None si no esta."""
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    p = os.path.join(bin_dir(), name)
    return p if os.path.exists(p) else None


def settings_ini_path():
    return os.path.join(system_dir(), "settings.ini")


def log_path():
    return os.path.join(system_dir(), "transcriber.log")


# ── Side effect: setear cache HF antes que faster_whisper se importe ──
_models = models_dir()
os.environ.setdefault("HF_HOME", _models)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", _models)
os.environ.setdefault("TRANSFORMERS_CACHE", _models)
