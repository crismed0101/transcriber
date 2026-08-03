# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para Transcriber.

Build:  python build.py
Salida: dist/Transcriber/Transcriber.exe  (modo onedir: arranca rapido)
        dist/Transcriber/bin/ffmpeg.exe   (lo copia build.py despues del build)
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct,
)

# SPECPATH lo inyecta PyInstaller; permite importar version.py sin depender del cwd.
sys.path.insert(0, SPECPATH)
import version  # noqa: E402

datas, binaries, hiddenimports = [], [], ["PyQt6.QtNetwork"]

# ── Dependencias que hay que empaquetar completas ──
#
#   av           faster_whisper/audio.py hace 'import av' a nivel de modulo. En
#                Windows los DLL de FFmpeg viven en av.libs/ y solo los levanta el
#                hook de hooks-contrib, que tiene ramas por version. Declararlo
#                explicito nos independiza de esa heuristica.
#
#   onnxruntime  faster_whisper/vad.py lo importa PEREZOSAMENTE dentro de
#                SileroVADModel.__init__, envuelto en try/except ImportError. Como
#                la app transcribe siempre con vad_filter=True, ese import se
#                ejecuta en cada transcripcion. Si no se empaqueta, el build sale
#                verde y la app muere en runtime con "Applying the VAD filter
#                requires the onnxruntime package". No confiar en el analisis
#                estatico para esto.
#
# Sin try/except a proposito: si falta un paquete, el build DEBE fallar. Antes se
# tragaba el error y producia un ejecutable roto que solo se detectaba al usarlo.
for pkg in ("faster_whisper", "ctranslate2", "pyaudiowpatch", "av", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Extension nativa que onnxruntime carga de forma dinamica.
hiddenimports.append("onnxruntime.capi.onnxruntime_pybind11_state")

# Metadata de distribucion: huggingface_hub y tokenizers consultan
# importlib.metadata.version() de sus dependencias al importarse.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av",
            "huggingface_hub", "tokenizers", "numpy", "tqdm"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        # Un paquete sin metadata instalable no es motivo para abortar el build.
        pass

# ── DLLs de CUDA ──
# destdir="ctranslate2" es CRITICO. CTranslate2 (ver su __init__.py) hace
# os.add_dll_directory() unicamente sobre SU propia carpeta y carga las *.dll que
# encuentre ahi. Si las DLL de CUDA quedaran en la ruta anidada por defecto
# (nvidia/<pkg>/bin/), CTranslate2 no las encuentra nunca y transcribir falla con
# "Library cublas64_12.dll is not found or cannot be loaded".
#
# Se empaquetan siempre: la app decide en runtime si usar GPU o CPU (ver
# hardware.engine_candidates), asi que un unico instalador sirve para cualquier PC.
for nv_pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
    try:
        binaries += collect_dynamic_libs(nv_pkg, destdir="ctranslate2")
    except Exception:
        # Entorno sin soporte CUDA: el build sigue y la app corre en CPU.
        pass

# ── Recursos del proyecto ──
datas.append((os.path.join(SPECPATH, "icon.ico"), "."))

# Nota: bin/ffmpeg.exe NO se incluye aca. build.py lo copia DESPUES del build a
# dist/Transcriber/bin/ para que quede junto al .exe y no dentro de _internal/,
# de modo que el usuario pueda verlo y reemplazarlo.


# ── Recurso de version del ejecutable ──
# Sin esto, el Explorador de Windows muestra "Editor: desconocido" y los antivirus
# heuristicos penalizan al binario. Se genera desde version.py para que no pueda
# quedar desincronizado.
_v = version.VERSION_TUPLE
_vs = ".".join(str(x) for x in _v)

VERSION_RESOURCE = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_v,
        prodvers=_v,
        mask=0x3F,          # VS_FFI_FILEFLAGSMASK
        flags=0x0,          # build de release
        OS=0x40004,         # VOS_NT_WINDOWS32
        fileType=0x1,       # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        # '040904B0' = en-US (0x0409) + codepage Unicode (1200). Se usa en-US
        # aunque los textos esten en espanol: es el bloque que el Explorador y las
        # heuristicas de antivirus esperan encontrar siempre.
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", version.APP_PUBLISHER),
            StringStruct("FileDescription", version.APP_DESCRIPTION),
            StringStruct("FileVersion", _vs),
            StringStruct("InternalName", version.APP_NAME),
            StringStruct("LegalCopyright", version.APP_COPYRIGHT),
            StringStruct("OriginalFilename", version.APP_NAME + ".exe"),
            StringStruct("ProductName", version.APP_NAME),
            StringStruct("ProductVersion", _vs),
            StringStruct("Comments", version.APP_URL),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)


a = Analysis(
    [os.path.join(SPECPATH, "main.py")],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # torch no se usa: faster-whisper corre sobre ctranslate2.
        "torch", "torchaudio", "torchvision", "tensorflow", "jax", "transformers",
        # La interfaz es PyQt6, no Tk.
        "tkinter",
        # Cientifico/desarrollo que entra por dependencias transitivas.
        "matplotlib", "scipy", "pandas", "IPython", "pytest", "setuptools._distutils",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=version.APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX corrompe las DLL de CUDA y de Qt, y ademas dispara falsos positivos de
    # antivirus en binarios de PyInstaller. No activar.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, "icon.ico"),
    version=VERSION_RESOURCE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=version.APP_NAME,
)
