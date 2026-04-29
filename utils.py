"""Utilidades compartidas (sin dependencias externas al proyecto)."""
import os
import sys
import subprocess


# Flag para que subprocess no abra ventanas de consola en Windows + pythonw.exe
NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def resource_path(rel):
    """Resuelve un recurso relativo, soportando PyInstaller (sys._MEIPASS).

    En frozen mode busca primero en _MEIPASS (datas embebidas), luego junto al .exe.
    En dev busca relativo a este archivo.
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
    # No existe en ningun lado: devolver el path canonico igual (caller decide)
    return os.path.join(bases[0], rel)


def same_path(a, b):
    """Comparacion case-insensitive y normalizada de paths (correcto en Windows)."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
