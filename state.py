"""Lifecycle y estado: migraciones de layout, dedupe de modelos, creacion de sesiones.

Este modulo no tiene side effects al importar (a diferencia de paths.py que setea HF_HOME).
Las funciones aca se llaman explicitamente desde main.py durante el arranque.
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
_TRANSCRIPCION_RE = re.compile(r"^transcripcion-(\d+)$")


# ── Pre-migracion: log/settings ANTES de abrir el FileHandler ──
def pre_migrate_log_settings():
    """Mueve log/settings de layouts viejos al system_dir actual.

    Layouts viejos posibles:
      <data>/transcriber.log              (raiz, layout original)
      <data>/settings.ini                 (raiz)
      <data>/_sistema/transcriber.log     (layout intermedio)
      <data>/_sistema/settings.ini        (layout intermedio)

    Corre ANTES de abrir el FileHandler (Windows no permite mover archivos en uso).
    Silencioso porque el logger aun no esta inicializado.
    """
    sysd = paths.system_dir()
    data = paths.data_dir()
    intermediate_sysd = os.path.join(data, "_sistema")

    candidates = []
    for fname in ("transcriber.log", "settings.ini"):
        candidates.append((os.path.join(data, fname), os.path.join(sysd, fname)))
        candidates.append((os.path.join(intermediate_sysd, fname), os.path.join(sysd, fname)))

    for old, new in candidates:
        if not os.path.isfile(old):
            continue
        if same_path(old, new):
            continue
        try:
            if os.path.exists(new):
                os.remove(old)
            else:
                shutil.move(old, new)
        except Exception:
            pass


# ── Sesion del dia ──
def make_session_folder():
    """Crea (o reusa) <data>/<YYYY-MM-DD>/transcripcion-<N>/ y la devuelve.

    N se calcula contando carpetas 'transcripcion-*' del dia + 1.
    """
    data = paths.data_dir()
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    day_dir = os.path.join(data, date_str)
    os.makedirs(day_dir, exist_ok=True)

    n = 1
    for entry in os.listdir(day_dir):
        m = _TRANSCRIPCION_RE.match(entry)
        if m and os.path.isdir(os.path.join(day_dir, entry)):
            n = max(n, int(m.group(1)) + 1)

    session = os.path.join(day_dir, f"transcripcion-{n}")
    os.makedirs(session, exist_ok=True)
    return session


# ── Migracion de layouts viejos ──
def _merge_dir(src_root, dst_root, kind="entrada"):
    """Mueve subentries de src_root a dst_root sin pisar; borra src_root si queda vacio."""
    if not os.path.isdir(src_root) or same_path(src_root, dst_root):
        return
    os.makedirs(dst_root, exist_ok=True)
    for entry in os.listdir(src_root):
        src = os.path.join(src_root, entry)
        dst = os.path.join(dst_root, entry)
        if os.path.exists(dst):
            continue
        try:
            shutil.move(src, dst)
            log.info("Migrada %s: %s -> %s", kind, src, dst)
        except Exception as ex:
            log.warning("No se pudo migrar %s %s: %s", kind, entry, ex)
    try:
        if not os.listdir(src_root):
            os.rmdir(src_root)
    except OSError:
        pass


def migrate_old_layout():
    """Migra layouts viejos al actual.

    A) <data>/archivo_*/, <data>/grabacion_*/         -> <data>/<date>/transcripcion-N/
    B) <data>/models/                                 -> <system>/models/  (layout original)
    C) <data>/_sistema/models/                        -> <system>/models/  (layout intermedio)
    D) <data>/_sistema/                               -> eliminar si queda vacio

    Idempotente y seguro: solo mueve si el destino no existe.
    """
    data = paths.data_dir()
    new_models = paths.models_dir()
    intermediate_sysd = os.path.join(data, "_sistema")

    # B) <data>/models/
    _merge_dir(os.path.join(data, "models"), new_models, kind="modelo")

    # C) <data>/_sistema/models/
    _merge_dir(os.path.join(intermediate_sysd, "models"), new_models, kind="modelo")

    # D) Eliminar _sistema/ si quedo vacio
    if os.path.isdir(intermediate_sysd):
        try:
            if not os.listdir(intermediate_sysd):
                os.rmdir(intermediate_sysd)
                log.info("Eliminado %s (vacio)", intermediate_sysd)
        except OSError:
            pass

    # A) Sesiones viejas
    for entry in list(os.listdir(data)):
        m = _OLD_SESSION_RE.match(entry)
        if not m:
            continue
        full = os.path.join(data, entry)
        if not os.path.isdir(full):
            continue
        date_str = f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
        day_dir = os.path.join(data, date_str)
        os.makedirs(day_dir, exist_ok=True)
        n = 1
        for d in os.listdir(day_dir):
            mm = _TRANSCRIPCION_RE.match(d)
            if mm:
                n = max(n, int(mm.group(1)) + 1)
        target = os.path.join(day_dir, f"transcripcion-{n}")
        try:
            shutil.move(full, target)
            log.info("Migrada sesion: %s -> %s", full, target)
        except Exception as ex:
            log.warning("No se pudo migrar sesion %s: %s", entry, ex)


# ── Dedupe de modelos Whisper ──
def dedupe_models_at_startup(model_name):
    """Mantiene una sola copia del modelo activo en paths.models_dir().

    - Borra duplicados del modelo activo en caches HF estandar (~/.cache/huggingface/hub).
    - Si el modelo activo solo existe en un cache externo, lo MUEVE a la carpeta portable.
    - Borra otros modelos Whisper que esten en la carpeta portable (no el activo).
    No toca otros modelos en caches externos (podrian usarlos otras apps).
    """
    target_name = f"models--Systran--faster-whisper-{model_name}"
    portable_root = paths.models_dir()
    portable_target = os.path.join(portable_root, target_name)

    appdata = os.environ.get("LOCALAPPDATA") or ""
    raw_caches = [
        os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"),
        os.path.join(appdata, "huggingface", "hub"),
        # Dev-mode cache de Transcriber (cuando se corre desde fuente)
        os.path.join(appdata, "Transcriber", "models"),
    ]
    seen = set()
    external_caches = []
    for c in raw_caches:
        if not c or not os.path.isdir(c):
            continue
        if same_path(c, portable_root):
            continue
        key = os.path.normcase(os.path.normpath(c))
        if key in seen:
            continue
        seen.add(key)
        external_caches.append(c)

    portable_has_target = os.path.isdir(portable_target)

    for cache in external_caches:
        ext_path = os.path.join(cache, target_name)
        if not os.path.isdir(ext_path):
            continue
        if portable_has_target:
            log.info("Dedupe: borrando duplicado externo %s", ext_path)
            shutil.rmtree(ext_path, ignore_errors=True)
        else:
            log.info("Dedupe: moviendo %s -> %s", ext_path, portable_target)
            try:
                shutil.move(ext_path, portable_target)
                portable_has_target = True
            except Exception as ex:
                log.warning("No se pudo mover modelo: %s", ex)

    # Limpiar otros modelos whisper en la carpeta portable (mantener solo el activo)
    if os.path.isdir(portable_root):
        for entry in os.listdir(portable_root):
            full = os.path.join(portable_root, entry)
            if not os.path.isdir(full):
                continue
            if not entry.startswith("models--") or "whisper" not in entry.lower():
                continue
            if entry == target_name:
                continue
            log.info("Dedupe: borrando modelo extra del portable %s", full)
            shutil.rmtree(full, ignore_errors=True)
