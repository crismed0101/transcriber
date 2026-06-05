"""Deteccion de hardware para sugerir el mejor modelo Whisper."""
import sys
import ctypes
import subprocess
import logging

from utils import NO_WINDOW

log = logging.getLogger(__name__)


def total_ram_gb():
    """RAM total del sistema en GB. 0 si no se puede determinar."""
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
            log.warning("No se pudo obtener RAM via Win32", exc_info=True)
    return 0


def total_vram_gb():
    """VRAM de la GPU primaria en GB. 0 si no hay GPU NVIDIA o nvidia-smi no esta."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=NO_WINDOW,
        )
        if result.returncode == 0:
            mb = int(result.stdout.strip().split("\n")[0])
            return mb / 1024
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return 0


def has_cuda():
    """ctranslate2 puede usar CUDA?"""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def recommend_model(vram_gb=None, ram_gb=None, cuda=None):
    """Sugiere el mejor modelo Whisper segun el hardware.

    Reglas:
      GPU >=5GB VRAM   -> large-v3
      GPU 3-5GB        -> medium
      GPU 2-3GB        -> small
      GPU <2GB         -> base
      CPU + 16GB+ RAM  -> small
      CPU + 8-16GB     -> base
      CPU <8GB         -> tiny
    """
    cuda = has_cuda() if cuda is None else cuda
    if cuda:
        vram_gb = total_vram_gb() if vram_gb is None else vram_gb
        if vram_gb <= 0:
            # CUDA disponible pero no pudimos medir la VRAM (nvidia-smi ausente/timeout).
            # Confiamos en el GPU y usamos el modelo grande (no degradar a ciegas).
            return "large-v3"
        if vram_gb >= 5:
            return "large-v3"
        if vram_gb >= 3:
            return "medium"
        if vram_gb >= 2:
            return "small"
        return "base"
    ram_gb = total_ram_gb() if ram_gb is None else ram_gb
    if ram_gb >= 16:
        return "small"
    if ram_gb >= 8:
        return "base"
    return "tiny"


def hardware_summary():
    cuda = has_cuda()
    vram = total_vram_gb() if cuda else 0
    ram = total_ram_gb()
    return {
        "cuda": cuda,
        "vram_gb": round(vram, 1),
        "ram_gb": round(ram, 1),
        "recommended": recommend_model(vram, ram, cuda),
    }
