"""Suite de pruebas de Transcriber.

Importar `paths` tiene un efecto de borde deliberado: crea los directorios de datos
y fija HF_HOME. Este `__init__` corre antes que cualquier modulo de prueba, asi que
es el lugar donde redirigimos esas rutas a un directorio temporal y evitamos
ensuciar la carpeta real del usuario al correr los tests.
"""
import os
import atexit
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="transcriber-tests-")

os.environ["HOME"] = _SANDBOX
os.environ["USERPROFILE"] = _SANDBOX
os.environ["LOCALAPPDATA"] = os.path.join(_SANDBOX, "AppData", "Local")
# Que las pruebas no toquen ni consulten el cache real de modelos.
os.environ["HF_HOME"] = os.path.join(_SANDBOX, "hf")
os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(_SANDBOX, "hf")

atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)


def sandbox():
    """Directorio temporal que hace de HOME durante las pruebas."""
    return _SANDBOX
