# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para Transcriber portable.

Build:  python build.py
Salida: dist/Transcriber/Transcriber.exe (modo onedir, arranque rapido, portable)
        dist/Transcriber/bin/ffmpeg.exe   (bundled)
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], ["PyQt6.QtNetwork"]

# Empaquetar dependencias completas (codigo, datos y libs nativas)
# tokenizers y huggingface_hub ya vienen via collect_all("faster_whisper") como deps transitivas
for pkg in ("faster_whisper", "ctranslate2", "pyaudiowpatch"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# DLLs de NVIDIA (cublas, cudnn, cuda_nvrtc) — solo los que existen en venv.
# CRITICO: destdir="ctranslate2" para que queden DENTRO de la carpeta de ctranslate2.
# CTranslate2 (ver su __init__.py) solo hace os.add_dll_directory() sobre SU propia
# carpeta y carga las *.dll que esten ahi. Si las DLLs de CUDA quedan en la ruta
# anidada por defecto (nvidia/<pkg>/bin/), CTranslate2 NUNCA las encuentra y al
# transcribir falla con "Library cublas64_12.dll is not found or cannot be loaded".
for nv_pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
    try:
        binaries += collect_dynamic_libs(nv_pkg, destdir="ctranslate2")
    except Exception:
        pass

# Recursos del proyecto
datas.append(("icon.ico", "."))

# Nota: bin/ffmpeg.exe NO se incluye aca; build.py lo copia DESPUES del build
# a dist/Transcriber/bin/ para que quede al lado del .exe (no dentro de _internal/),
# manteniendo la app realmente portable y la carpeta bin/ visible para el usuario.


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Reducir tamano: torch no se usa (faster-whisper usa ctranslate2)
        "torch", "torchaudio", "torchvision",
        "tensorflow", "jax",
        # Tk no se usa (UI con PyQt6)
        "tkinter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Transcriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX rompe DLLs de CUDA / Qt; mejor evitarlo
    console=False,                  # GUI app (sin consola)
    disable_windowed_traceback=False,
    icon="icon.ico",
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Transcriber",
)
