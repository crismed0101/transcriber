"""Deteccion de hardware y eleccion del motor Whisper que esta PC puede sostener.

Este modulo concentra TODA la logica de adaptacion al equipo. El resto de la app
no consulta nvidia-smi ni razona sobre VRAM: pide `engine_candidates()` y usa lo
que le devuelve.

Las consultas son cacheadas: nvidia-smi tarda ~100-300 ms y antes se lo invocaba
tres veces distintas durante el arranque.
"""
import os
import re
import sys
import ctypes
import logging
import functools
import subprocess
import collections

from utils import NO_WINDOW

log = logging.getLogger(__name__)

GpuInfo = collections.namedtuple("GpuInfo", "present name vram_gb driver_version compute_cap")

_NO_GPU = GpuInfo(present=False, name="", vram_gb=0.0, driver_version="", compute_cap="")

# Escalera de modelos, del mas capaz al mas liviano.
#
#   min_vram_gb: VRAM necesaria para correr con holgura en GPU.
#   min_ram_gb : RAM necesaria para correr en CPU. `inf` significa "nunca en CPU":
#                medium y large-v3 son tan lentos sin GPU que la app quedaria horas
#                trabajando. Es una decision de producto, no un limite tecnico; el
#                usuario igual puede forzarlos desde el selector de modelo.
#   size_mb    : peso aproximado de la descarga, para la barra de progreso.
_NEVER = float("inf")

MODEL_LADDER = (
    # nombre           min_vram_gb  min_ram_gb  size_mb
    ("large-v3",               5.0,     _NEVER,     3000),
    # Mismo encoder que large-v3 con 4 capas de decodificador en vez de 32: unas 6
    # veces mas rapido y ~0.3 puntos mas de error. Entra donde large-v3 no entra, y
    # es mejor opcion que medium a igual memoria.
    ("large-v3-turbo",         3.5,     _NEVER,     1600),
    ("medium",                 3.0,     _NEVER,     1500),
    ("small",                  2.0,       16.0,      480),
    ("base",                   1.0,        8.0,      145),
    ("tiny",                   0.0,        0.0,       75),
)

MODEL_NAMES = tuple(m[0] for m in MODEL_LADDER)
MODEL_SIZES_MB = {m[0]: m[3] for m in MODEL_LADDER}

# Driver minimo para GPUs Blackwell (RTX 50xx). Con uno anterior, CUDA carga pero
# los kernels sm_120 no existen y la transcripcion muere con
# "no kernel image is available for execution on the device".
_BLACKWELL_MIN_DRIVER = 570
_BLACKWELL_COMPUTE_CAP = 12.0


@functools.lru_cache(maxsize=1)
def total_ram_gb():
    """RAM total del sistema en GB. 0.0 si no se puede determinar."""
    if sys.platform == "win32":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("sullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return ms.ullTotalPhys / (1024 ** 3)
        except Exception:
            log.warning("No se pudo obtener la RAM via Win32", exc_info=True)
        return 0.0

    # Dev en Linux/macOS: la app no corre ahi, pero los tests si.
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def _nvidia_smi(fields, timeout=5):
    """Corre nvidia-smi con las columnas pedidas. Devuelve la primera fila o None."""
    try:
        r = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(fields)}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=NO_WINDOW,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    first = r.stdout.strip().splitlines()[0]
    return [c.strip() for c in first.split(",")]


@functools.lru_cache(maxsize=1)
def gpu_info():
    """Datos de la GPU NVIDIA primaria en UNA sola consulta a nvidia-smi.

    Devuelve un GpuInfo; `present` es False si no hay GPU NVIDIA o nvidia-smi no
    esta disponible (que es lo mismo desde el punto de vista de la app: sin driver
    no hay CUDA).
    """
    # compute_cap solo existe en nvidia-smi recientes; si falla, reintentamos sin el
    # para no perder el resto de los datos en equipos con drivers viejos.
    row = _nvidia_smi(["name", "memory.total", "driver_version", "compute_cap"])
    compute_cap = ""
    if row is None:
        row = _nvidia_smi(["name", "memory.total", "driver_version"])
    elif len(row) >= 4:
        compute_cap = row[3]
    if row is None or len(row) < 3:
        return _NO_GPU

    try:
        vram_gb = int(row[1]) / 1024
    except ValueError:
        vram_gb = 0.0

    info = GpuInfo(
        present=True,
        name=row[0],
        vram_gb=vram_gb,
        driver_version=row[2],
        compute_cap=compute_cap,
    )
    log.info(
        "GPU: %s | VRAM %.1f GB | driver %s | compute %s",
        info.name, info.vram_gb, info.driver_version, info.compute_cap or "?",
    )
    return info


def short_gpu_name(name=None):
    """Nombre corto para la UI: 'NVIDIA GeForce RTX 5070' -> 'RTX 5070'."""
    name = gpu_info().name if name is None else name
    if not name:
        return ""
    # El orden importa: 'RTX A' antes que 'RTX' para no cortar una 'RTX A4000'.
    for token in ("RTX A", "RTX", "GTX", "Quadro", "Tesla"):
        idx = name.find(token)
        if idx >= 0:
            return name[idx:]
    return name


def driver_too_old():
    """True si la GPU necesita un driver mas nuevo del que hay instalado.

    Solo aplica a Blackwell (compute capability 12.x, RTX 50xx), que exige r570+.
    Con un driver anterior CUDA parece disponible pero ningun kernel corre.
    """
    info = gpu_info()
    if not info.present:
        return False
    try:
        cap = float(info.compute_cap)
    except (TypeError, ValueError):
        return False
    if cap < _BLACKWELL_COMPUTE_CAP:
        return False
    m = re.match(r"(\d+)", info.driver_version or "")
    if not m:
        return False
    return int(m.group(1)) < _BLACKWELL_MIN_DRIVER


@functools.lru_cache(maxsize=1)
def cuda_available():
    """True si CTranslate2 ve al menos un dispositivo CUDA utilizable.

    Ojo: esto solo consulta el driver. Que devuelva True no garantiza que existan
    kernels para esta arquitectura; por eso el motor igual prueba y degrada
    (ver engine_candidates y Transcriber.load_model).
    """
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() <= 0:
            return False
    except Exception:
        log.info("CTranslate2 no reporta dispositivos CUDA", exc_info=True)
        return False

    if driver_too_old():
        log.warning(
            "GPU Blackwell (compute %s) con driver %s: se necesita r%d+. Usando CPU.",
            gpu_info().compute_cap, gpu_info().driver_version, _BLACKWELL_MIN_DRIVER,
        )
        return False
    return True


def recommend_model(cuda=None, vram_gb=None, ram_gb=None):
    """Modelo mas capaz que esta PC puede sostener, segun MODEL_LADDER."""
    cuda = cuda_available() if cuda is None else cuda
    if cuda:
        vram_gb = gpu_info().vram_gb if vram_gb is None else vram_gb
        if vram_gb <= 0:
            # Hay CUDA pero no pudimos medir la VRAM (nvidia-smi ausente o mudo).
            # Confiamos en la GPU en vez de degradar a ciegas.
            return MODEL_LADDER[0][0]
        for name, min_vram, _, _ in MODEL_LADDER:
            if vram_gb >= min_vram:
                return name
    else:
        ram_gb = total_ram_gb() if ram_gb is None else ram_gb
        for name, _, min_ram, _ in MODEL_LADDER:
            if ram_gb >= min_ram:
                return name
    return MODEL_LADDER[-1][0]


def compute_type_for(device):
    """Precision a usar en cada dispositivo.

    En CUDA siempre float16. NO usar int8/int8_float16 en GPU: CTranslate2 4.6.2
    deshabilito INT8 en Blackwell (sm_120), asi que en una RTX 50xx cualquier
    variante int8 falla al cargar el modelo.
    """
    return "float16" if device == "cuda" else "int8"


def _chain_from(start_model, device):
    """Escalera de (modelo, device, compute) desde start_model hacia abajo."""
    compute = compute_type_for(device)
    names = list(MODEL_NAMES)
    if start_model in names:
        tail = names[names.index(start_model):]
    else:
        # Modelo fuera de la escalera (override manual via TRANSCRIBER_MODEL):
        # probarlo primero y, si no carga, recorrer la escalera conocida.
        tail = [start_model] + names
    return [(name, device, compute) for name in tail]


def engine_candidates(preferred_model=None):
    """Configuraciones a probar, de la mejor a la mas conservadora.

    El motor recorre esta lista hasta que una carga (ver Transcriber.load_model).
    Asi la app arranca en cualquier equipo: si CUDA no sirve cae a CPU, y si el
    modelo no entra en memoria cae al siguiente mas chico, sin que el usuario
    tenga que tocar nada.

    Args:
        preferred_model: modelo elegido a mano; None = automatico segun hardware.

    Returns:
        Lista de tuplas (model_name, device, compute_type), sin repetidos.
    """
    if cuda_available():
        candidates = _chain_from(preferred_model or recommend_model(cuda=True), "cuda")
        # Red de contencion en CPU. Arranca por lo que la CPU aguanta, NO por el
        # modelo elegido para GPU: si la GPU fallo, correr large-v3 en CPU seria
        # una espera de horas disfrazada de exito.
        candidates += _chain_from(recommend_model(cuda=False), "cpu")
    else:
        candidates = _chain_from(preferred_model or recommend_model(cuda=False), "cpu")

    seen, unique = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def summary():
    """Resumen para el log y la UI."""
    info = gpu_info()
    cuda = cuda_available()
    return {
        "cuda": cuda,
        "gpu_name": info.name,
        "gpu_short": short_gpu_name(),
        "vram_gb": round(info.vram_gb, 1),
        "driver": info.driver_version,
        "compute_cap": info.compute_cap,
        "driver_too_old": driver_too_old(),
        "ram_gb": round(total_ram_gb(), 1),
        "recommended": recommend_model(cuda=cuda),
    }
