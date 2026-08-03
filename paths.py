"""Rutas de la app, resueltas contra las Known Folders reales de Windows.

Layout, en cualquier PC y sin importar desde donde se ejecute el .exe:
    data_dir   = <Documentos>/Transcriber/      transcripciones + audios del usuario
    system_dir = %LOCALAPPDATA%/Transcriber/    modelos, logs, settings

Por que Known Folders y no "%USERPROFILE%\\Documents":
    Con OneDrive Backup activado (el default en Windows 11 con cuenta Microsoft),
    la carpeta Documentos se redirige a %USERPROFILE%\\OneDrive\\Documents. Armar la
    ruta a mano deja los archivos en la carpeta huerfana: la app los encuentra
    porque usa rutas absolutas, pero el usuario abre Documentos en el Explorador y
    no ve nada. SHGetKnownFolderPath devuelve la ruta que el shell resuelve de
    verdad, redirigida o no.

IMPORTANTE: importar este modulo SETEA HF_HOME / HUGGINGFACE_HUB_CACHE para que
faster_whisper descargue los modelos al directorio correcto. Debe importarse ANTES
que faster_whisper.
"""
import os
import sys
import ctypes
import logging

log = logging.getLogger(__name__)

APP_DIRNAME = "Transcriber"

# FOLDERID_Documents — https://learn.microsoft.com/windows/win32/shell/knownfolderid
_FOLDERID_DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"


def is_frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    """Carpeta donde esta el .exe en frozen mode, o el codigo fuente en dev."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _known_folder(folder_guid):
    """Resuelve una Known Folder de Windows. None si no se puede.

    Usa SHGetKnownFolderPath, que respeta las redirecciones de carpeta (OneDrive,
    politicas de dominio, perfiles moviles).
    """
    if sys.platform != "win32":
        return None
    try:
        guid = _GUID()
        # CLSIDFromString parsea el formato "{...}" y llena la estructura GUID.
        if ctypes.windll.ole32.CLSIDFromString(folder_guid, ctypes.byref(guid)) != 0:
            return None
        out = ctypes.c_wchar_p()
        # dwFlags=0, hToken=NULL (usuario actual)
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(out)
        )
        if hr != 0 or not out.value:
            return None
        try:
            return out.value
        finally:
            # El caller es dueno del buffer y debe liberarlo con CoTaskMemFree.
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        log.warning("SHGetKnownFolderPath fallo para %s", folder_guid, exc_info=True)
        return None


def documents_dir():
    """Carpeta Documentos del usuario, redirigida o no."""
    return _known_folder(_FOLDERID_DOCUMENTS) or os.path.join(
        os.path.expanduser("~"), "Documents"
    )


def legacy_documents_dir():
    """La ruta que la app usaba antes: '~/Documents' armada a mano.

    Solo sirve para migrar datos de instalaciones previas (ver state.migrate).
    Devuelve None si coincide con la ruta actual, o sea si no hay nada que migrar.
    """
    legacy = os.path.join(os.path.expanduser("~"), "Documents")
    current = documents_dir()
    if os.path.normcase(os.path.normpath(legacy)) == os.path.normcase(
        os.path.normpath(current)
    ):
        return None
    return legacy


def data_dir():
    """Donde van las transcripciones del usuario."""
    d = os.path.join(documents_dir(), APP_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def system_dir():
    """Donde van log, settings y modelos."""
    appdata = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    d = os.path.join(appdata, APP_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def models_dir():
    """Cache de modelos Whisper -> <system_dir>/models/."""
    d = os.path.join(system_dir(), "models")
    os.makedirs(d, exist_ok=True)
    return d


def model_cache_dir(model_name):
    """Carpeta donde huggingface_hub deja un modelo Whisper concreto.

    Unica definicion del layout del cache HF: la usan el monitor de descarga, la
    limpieza de modelos viejos y el chequeo de "ya esta bajado".
    """
    return os.path.join(models_dir(), f"models--Systran--faster-whisper-{model_name}")


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


# ── Side effect: fijar el cache de HuggingFace antes de que se importe faster_whisper ──
# Sin esto los modelos caerian en ~/.cache/huggingface, fuera del control de la app.
_models = models_dir()
os.environ.setdefault("HF_HOME", _models)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", _models)
