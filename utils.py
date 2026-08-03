"""Utilidades compartidas. Sin dependencias fuera de la biblioteca estandar."""
import os
import re
import sys
import logging
import subprocess

log = logging.getLogger(__name__)

# Evita que subprocess abra ventanas de consola cuando la app corre sin consola.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Caracteres que Windows no admite en nombres de archivo o carpeta.
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def resource_path(rel):
    """Resuelve un recurso relativo, contemplando PyInstaller.

    En modo congelado busca primero en sys._MEIPASS (los datos embebidos) y despues
    junto al ejecutable. En desarrollo, relativo a este archivo.
    """
    bases = []
    if hasattr(sys, "_MEIPASS"):
        bases.append(sys._MEIPASS)
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(os.path.abspath(sys.executable)))
    bases.append(os.path.dirname(os.path.abspath(__file__)))

    for base in bases:
        candidate = os.path.join(base, rel)
        if os.path.exists(candidate):
            return candidate
    # No esta en ningun lado: devolvemos la ruta canonica y decide quien llama.
    return os.path.join(bases[0], rel)


def same_path(a, b):
    """Compara rutas normalizadas y sin distinguir mayusculas (correcto en Windows)."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def open_in_explorer(path):
    """Abre una carpeta o archivo con la aplicacion asociada del sistema.

    Se abre la carpeta directamente y no `explorer /select`, que falla cuando el
    nombre tiene espacios o parentesis (p.ej. 'transcripcion-3 (prueba)') y termina
    abriendo la carpeta raiz.
    """
    try:
        os.startfile(path)
    except (OSError, AttributeError) as ex:
        log.warning("No se pudo abrir %s: %s", path, ex)


def sanitize_folder_name(name, max_len=60):
    """Convierte texto libre en un nombre de carpeta valido en Windows.

    Devuelve None si no queda nada utilizable.
    """
    if not name:
        return None
    cleaned = _INVALID_FILENAME_CHARS.sub("", name)
    # Windows no admite nombres terminados en punto ni en espacio.
    cleaned = cleaned.strip().rstrip(". ")
    return cleaned[:max_len].strip() or None
