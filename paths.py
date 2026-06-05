"""Manejo de paths: SIEMPRE modo estandar Windows, en cualquier PC.

La app sigue las Known Folders de Microsoft, sin importar desde donde se ejecute
(C:\\DevMed, USB, etc.). Es lo que el usuario espera: lo que el genera va a
Documents, los datos internos de la app van al cache local del sistema.
    data_dir   = ~/Documents/Transcriber/      (transcripciones + audios del usuario)
    system_dir = %LOCALAPPDATA%/Transcriber/   (modelos, logs, settings)

El antiguo modo portable (marker portable.txt junto al .exe) quedo DESACTIVADO;
ver is_portable(). Si aparece un portable.txt de un build viejo, se ignora.

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
    """Modo portable DESACTIVADO por decision de producto.

    Antes se activaba si existia <app>/portable.txt junto al .exe, lo que hacia
    que la app guardara todo junto al ejecutable. Eso confundia al usuario porque
    cada copia (C:\\DevMed, USB, etc.) escribia en su propia carpeta en vez de en
    Documents. Ahora la app SIEMPRE usa rutas estandar Windows en cualquier PC:
        transcripciones/audios -> ~/Documents/Transcriber/
        modelos/logs/settings  -> %LOCALAPPDATA%/Transcriber/
    El archivo portable.txt, si existe, se ignora.
    """
    return False


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
# (TRANSFORMERS_CACHE quedo deprecado en huggingface_hub; HF_HOME ya cubre todo.)
_models = models_dir()
os.environ.setdefault("HF_HOME", _models)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", _models)
