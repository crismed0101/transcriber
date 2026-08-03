"""Ciclo de vida en disco: migraciones de layout, limpieza de modelos y sesiones.

Este modulo no tiene efectos al importarse (a diferencia de paths.py, que fija
HF_HOME). Las funciones se llaman explicitamente desde el arranque.
"""
import os
import re
import shutil
import datetime
import logging

import paths
from utils import same_path

log = logging.getLogger(__name__)

_OLD_SESSION_RE = re.compile(r"^(archivo|grabacion)_(\d{4})(\d{2})(\d{2})_\d{6}$")
# Acepta 'transcripcion-N' y 'transcripcion-N (nombre custom)'; grupo 1 = numero.
_TRANSCRIPCION_RE = re.compile(r"^transcripcion-(\d+)( \(.+\))?$")

# Nombres que deja la app dentro de una sesion y que valen la pena conservar.
SESSION_KEEP_FILES = frozenset({"audio.mp3", "transcripcion.txt", "transcripcion.srt"})

# Margen sobre el MAX_PATH de Windows (260) para que entren los nombres de archivo
# que la app agrega dentro de la sesion (audio.mp3, transcripcion.srt, ...).
MAX_SESSION_DIR_LEN = 240


# ── Pre-migracion: log y settings ANTES de abrir el FileHandler ──
def pre_migrate_log_settings():
    """Mueve log/settings de layouts viejos al system_dir actual.

    Corre antes de abrir el FileHandler porque Windows no permite mover un archivo
    en uso. Silencioso a proposito: el logger todavia no existe.
    """
    sysd = paths.system_dir()
    roots = [paths.data_dir()]
    legacy_docs = paths.legacy_documents_dir()
    if legacy_docs:
        roots.append(os.path.join(legacy_docs, paths.APP_DIRNAME))

    candidates = []
    for root in roots:
        for fname in ("transcriber.log", "settings.ini"):
            candidates.append((os.path.join(root, fname), os.path.join(sysd, fname)))
            candidates.append((os.path.join(root, "_sistema", fname),
                               os.path.join(sysd, fname)))

    for old, new in candidates:
        if not os.path.isfile(old) or same_path(old, new):
            continue
        try:
            if os.path.exists(new):
                os.remove(old)
            else:
                shutil.move(old, new)
        except OSError:
            pass


# ── Sesiones ──
def next_session_number(day_dir):
    """Proximo N libre para 'transcripcion-N' dentro de una carpeta de fecha."""
    n = 1
    try:
        entries = os.listdir(day_dir)
    except OSError:
        return n
    for entry in entries:
        m = _TRANSCRIPCION_RE.match(entry)
        if m and os.path.isdir(os.path.join(day_dir, entry)):
            n = max(n, int(m.group(1)) + 1)
    return n


def make_session_folder():
    """Crea y devuelve <data>/<YYYY-MM-DD>/transcripcion-<N>/.

    Raises:
        OSError: si no se puede crear (disco lleno, carpeta de solo lectura,
            OneDrive sin conexion) o si la ruta supera el limite de Windows. El
            caller debe manejarlo: es un slot de Qt y una excepcion sin capturar
            aborta el proceso.
    """
    day_dir = os.path.join(paths.data_dir(), datetime.date.today().strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    session = os.path.join(day_dir, f"transcripcion-{next_session_number(day_dir)}")

    if len(session) > MAX_SESSION_DIR_LEN:
        raise OSError(
            f"La ruta de la transcripcion es demasiado larga ({len(session)} "
            f"caracteres, maximo {MAX_SESSION_DIR_LEN}):\n{session}\n\n"
            "Mové tu carpeta Documentos a una ruta mas corta."
        )

    os.makedirs(session, exist_ok=True)
    return session


def session_has_content(session_dir):
    """True si la sesion tiene algun archivo que valga la pena conservar."""
    try:
        return bool(set(os.listdir(session_dir)) & SESSION_KEEP_FILES)
    except OSError:
        return False


# ── Migracion de layouts viejos ──
def _merge_dir(src_root, dst_root, kind="entrada"):
    """Mueve el contenido de src_root a dst_root sin pisar; borra src si queda vacio."""
    if not os.path.isdir(src_root) or same_path(src_root, dst_root):
        return
    os.makedirs(dst_root, exist_ok=True)
    try:
        entries = os.listdir(src_root)
    except OSError:
        return
    for entry in entries:
        src = os.path.join(src_root, entry)
        dst = os.path.join(dst_root, entry)
        if os.path.exists(dst):
            continue
        try:
            shutil.move(src, dst)
            log.info("Migrada %s: %s -> %s", kind, src, dst)
        except OSError as ex:
            log.warning("No se pudo migrar %s %s: %s", kind, entry, ex)
    try:
        if not os.listdir(src_root):
            os.rmdir(src_root)
    except OSError:
        pass


def migrate_old_layout():
    """Lleva instalaciones viejas al layout actual. Idempotente y no destructiva.

    Migraciones cubiertas:
      A) <Documents-sin-redirigir>/Transcriber/  -> <Documentos-real>/Transcriber/
         (la app armaba la ruta a mano y con OneDrive escribia en la carpeta
          huerfana; ver paths.documents_dir)
      B) <data>/models/ y <data>/_sistema/models/ -> <system>/models/
      C) <data>/archivo_*/ y <data>/grabacion_*/  -> <data>/<fecha>/transcripcion-N/
    """
    data = paths.data_dir()

    # A) Documents no redirigido -> Documentos real
    legacy_docs = paths.legacy_documents_dir()
    if legacy_docs:
        _merge_dir(os.path.join(legacy_docs, paths.APP_DIRNAME), data, kind="carpeta")

    # B) Modelos que quedaron entre los datos del usuario
    new_models = paths.models_dir()
    intermediate = os.path.join(data, "_sistema")
    _merge_dir(os.path.join(data, "models"), new_models, kind="modelo")
    _merge_dir(os.path.join(intermediate, "models"), new_models, kind="modelo")
    try:
        if os.path.isdir(intermediate) and not os.listdir(intermediate):
            os.rmdir(intermediate)
    except OSError:
        pass

    # C) Sesiones con el nombre viejo
    try:
        entries = list(os.listdir(data))
    except OSError:
        return
    for entry in entries:
        m = _OLD_SESSION_RE.match(entry)
        if not m:
            continue
        full = os.path.join(data, entry)
        if not os.path.isdir(full):
            continue
        day_dir = os.path.join(data, f"{m.group(2)}-{m.group(3)}-{m.group(4)}")
        try:
            os.makedirs(day_dir, exist_ok=True)
            target = os.path.join(day_dir, f"transcripcion-{next_session_number(day_dir)}")
            shutil.move(full, target)
            log.info("Migrada sesion: %s -> %s", full, target)
        except OSError as ex:
            log.warning("No se pudo migrar la sesion %s: %s", entry, ex)


# ── Limpieza del cache de modelos ──
def cleanup_model_cache(active_model):
    """Deja un solo modelo Whisper en el cache PROPIO de la app.

    Solo toca `paths.models_dir()`. Deliberadamente NO toca los caches compartidos
    de HuggingFace (~/.cache/huggingface, %LOCALAPPDATA%\\huggingface): son de todo
    el sistema y borrar ahi le rompe el cache a cualquier otro proyecto del usuario
    que use el mismo modelo.
    """
    root = paths.models_dir()
    keep = os.path.basename(paths.model_cache_dir(active_model))
    try:
        entries = os.listdir(root)
    except OSError:
        return
    for entry in entries:
        full = os.path.join(root, entry)
        if entry == keep or not os.path.isdir(full):
            continue
        if not entry.startswith("models--") or "whisper" not in entry.lower():
            continue
        log.info("Borrando modelo que ya no se usa: %s", full)
        shutil.rmtree(full, ignore_errors=True)
