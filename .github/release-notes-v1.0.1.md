# Transcriber v1.0.1

Pulido grande de UX + fixes de cleanup post-uso real. Recomendado actualizar.

## Descarga

1. Bajá `Transcriber-v1.0.1-windows-x64.zip` (abajo en **Assets**).
2. Click derecho > **Extract All**.
3. Doble click en `Transcriber.exe`. Listo.

> Si ya tenías `Transcriber-v1.0.0`, podés simplemente reemplazar la carpeta por la nueva. Tus transcripciones (`transcripciones/`) y settings (`_sistema/`) sobreviven si los moves.

## Novedades

### Nuevo formato del archivo de texto

Antes: texto plano (un solo bloque). Ahora **timestamps por línea**:

```
[00:00] Hola, bienvenido al programa.
[00:03] Vamos a hablar del tema X.
[00:08] Y muy especificamente de Y.
```

Mucho más fácil de revisar y saltar a la parte relevante del audio. Si el audio supera 1 hora, cambia a `[HH:MM:SS]` automáticamente.

### Idioma por defecto: Español

Auto-detectar quedó como segunda opción (a veces confundía español con portugués en audios cortos). Se persiste tu elección.

### Más visible qué está pasando

- **Título de la ventana** dice el estado: `Transcriber - Grabando 0:23` / `Transcriber* - 2026-04-29/transcripcion-3` (`*` = sin guardar).
- **Tray tooltip** sigue el estado en vivo.
- **Status chip** color-coded: verde Listo / naranja Procesando / rojo Error.
- **Hardware badge** en el header: `GPU: RTX 5070` o `CPU - 16 GB RAM`.
- **ETA** durante transcripción: `Transcribiendo... 42% (~2m 15s)`.
- **Status durante grabación** muestra el dispositivo: `Grabando (Speakers Realtek)`.

### Funcionalidad nueva

- **Cancelar** transcripción en curso (botón al lado de la barra).
- **Texto editable** + botón Guardar para corregir manualmente.
- **Copiar selección** (si hay texto seleccionado, copia solo eso).
- **Subir múltiples archivos** a la vez (cola batch); drag-and-drop multi-archivo.
- **Toggle Fuente: Audio del sistema / Micrófono** para grabar dictado.
- **Historial enriquecido**: hora, duración, indicador `.srt`, click derecho para borrar.
- **SRT** ahora opcional, click derecho en el editor → "Exportar como subtítulos (.srt)".
- **Barra de descarga del modelo** durante la primera ejecución.
- **Avisa antes de descartar ediciones**: "Cambios sin guardar / Descartar / Cancelar".

### Robustez (production fixes)

- `_mono.wav` y `_raw.wav` siempre limpiados (incluso en cancel/error).
- `audio.mp3` parcial eliminado si cancelás antes de que arranque Whisper.
- Carpetas de sesión vacías post-error se eliminan solas.
- Auto-stop a 3.8 GB (límite WAV) con aviso, evitando corrupción.
- Manejo de disco lleno durante grabación.
- Single-instance per-user (no colisiona en Remote Desktop).
- Log con fallback a `%TEMP%` si la ruta principal es read-only.
- Validación de path length (Windows MAX_PATH).
- FFmpeg subprocesses killable on cancel/close (no zombies).

## Compatibilidad

- Misma cosa que v1.0.0: Windows 10/11 x64, GPU NVIDIA opcional, ~3 GB de modelo en la 1ra ejecución.

## Limitaciones conocidas

- Solo Windows.
- SmartScreen warning la primera vez (sin firma de código).
- Sin auto-update.

## Reportar bugs

Issues en https://github.com/crismed0101/transcriber/issues
