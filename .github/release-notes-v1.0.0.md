# Transcriber v1.0.0

Primera release pública. App de escritorio Windows para transcribir audio a texto usando Whisper, **100% local y offline** después de la primera descarga del modelo.

## Descarga e instalación

1. Bajá `Transcriber-v1.0.0-windows-x64.zip` (abajo en **Assets**).
2. Click derecho > **Extract All** sobre el zip.
3. Doble click en `Transcriber.exe` dentro de la carpeta extraída.

Listo. La app es **portable**: copiala a un USB y funciona en cualquier Windows 10/11.

> **Primera ejecución**: descarga el modelo Whisper `large-v3` (~3 GB) desde HuggingFace. Una sola vez. Verás una barra de progreso. Subsecuentes lanzamientos arrancan en ~3 segundos.

## Features

- **Grabación del audio del sistema** (loopback WASAPI: lo que escuchas por parlantes).
- **Grabación del micrófono** (toggle en la UI).
- **Subir archivos** de audio (MP3, WAV, M4A, OGG, FLAC, etc.).
- **Drag-and-drop** multi-archivo (procesa en cola).
- **Transcripción offline** con Whisper `large-v3` (max calidad).
- **GPU NVIDIA con CUDA** (si está disponible — 10-20x más rápido).
- **Auto-detección de idioma** o selector manual (es / en / pt / fr / de / it).
- **Auto-export** de `audio.mp3` + `transcripcion.txt` + `transcripcion.srt` (con timestamps).
- **Texto editable** + botón Guardar para correcciones manuales.
- **Cancelar** transcripciones largas en curso.
- **Historial** de transcripciones pasadas con preview y reload.
- **System tray**: cerrar la ventana minimiza, click derecho > Salir.
- **Hotkey global** Ctrl+Shift+R para iniciar/detener grabación.

## Requisitos

- **Windows 10 / 11 (x64)**
- **8 GB RAM** mínimo recomendado
- **GPU NVIDIA con CUDA** opcional (transcripción 10-20x más rápida)
- **Conexión a internet** sólo para la primera descarga del modelo

## Estructura portable

```
Transcriber/
├── Transcriber.exe        ← doble click
├── _internal/             ← deps (PyQt6, faster-whisper, cuDNN, cuBLAS)
├── bin/                   ← ffmpeg.exe + ffprobe.exe (LGPL)
├── portable.txt           ← marker del modo portable
└── LEEME.txt              ← guía de uso

Al ejecutar se crean:
├── transcripciones/<YYYY-MM-DD>/transcripcion-N/
│   ├── audio.mp3
│   ├── transcripcion.txt
│   └── transcripcion.srt
└── _sistema/
    ├── transcriber.log
    ├── settings.ini
    └── models/            ← modelo Whisper descargado
```

Si borrás `portable.txt`, la app pasa a modo estándar Windows: transcripciones en `Documents\Transcriber\`, modelos/logs en `%LOCALAPPDATA%\Transcriber\`.

## Limitaciones conocidas

- **Solo Windows**: la captura loopback usa `pyaudiowpatch` que es Windows-only.
- **SmartScreen warning** la primera vez: el .exe no está firmado digitalmente. Click en "Más información" > "Ejecutar de todos modos".
- **Sin auto-update**: para actualizar, descargar la siguiente release.

## Licencias de componentes

- App: código fuente bajo el repo.
- FFmpeg: LGPL (incluido en `bin/FFMPEG-LICENSE.txt`).
- Whisper: MIT (OpenAI).
- PyQt6: GPLv3.

## Reportar bugs

Issues en https://github.com/crismed0101/transcriber/issues
