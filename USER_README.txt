============================================================
 TRANSCRIBER - Transcribir audio a texto (offline) con Whisper
============================================================

USO RAPIDO
----------
1. Doble click en Transcriber.exe.
2. La primera vez la app baja el modelo Whisper (entre 75 MB
   y 3 GB segun el modelo elegido). Tene paciencia.
3. Para grabar el audio del sistema (lo que estas escuchando):
   - Click en GRABAR.
   - Cuando termines, click en DETENER.
   - Esperar la transcripcion. Click en Guardar para .txt.
4. Para transcribir un archivo de audio existente:
   - Click en SUBIR ARCHIVO, o
   - Arrastra el archivo sobre la ventana.

MODELO WHISPER
--------------
La app detecta tu hardware y elige un modelo automaticamente
en modo "Auto". Si querer mas precision o mas velocidad,
elegi manualmente:
   tiny       - ~75 MB,  el mas rapido, calidad basica
   base       - ~140 MB, rapido, calidad ok
   small      - ~480 MB, balance
   medium     - ~1.5 GB, mejor calidad, requiere GPU 3GB+
   large-v3   - ~3 GB,   maxima calidad, GPU 5GB+ recomendado

Cambiar de modelo recarga el motor (~5-15s).

ATAJOS
------
- Ctrl+Shift+R: Iniciar/detener grabacion (funciona aunque
  la ventana este minimizada en la bandeja).
- Cerrar (X): minimiza a la bandeja del sistema. Click derecho
  en el icono > Salir para cerrar la app.

PORTABLE
--------
La carpeta es portable: copiala a un USB o a otra PC y funciona.
Todo (modelos descargados, transcripciones, settings) se guarda
en subcarpetas:
   data/    - tus transcripciones (.wav, .mp3, .txt) y log
   models/  - modelos Whisper bajados
   bin/     - ffmpeg incluido

REQUISITOS
----------
- Windows 10 / 11 (x64).
- 4 GB de RAM minimo (8 GB+ recomendado).
- GPU NVIDIA con CUDA es OPCIONAL pero hace la transcripcion
  10-20x mas rapida.

TROUBLESHOOTING
---------------
- "FFmpeg no encontrado": la carpeta bin/ debe estar al lado
  del .exe. Si la perdiste, descargala de gyan.dev/ffmpeg.
- App se cierra al transcribir: tu hardware no alcanza para el
  modelo elegido. Bajalo a 'small' o 'base' en el desplegable.
- Sin audio: para grabar lo que escuchas, Windows necesita un
  dispositivo de salida activo (parlantes/auriculares).
- Logs detallados en data/transcriber.log

LICENCIAS
---------
- Codigo de la app: tu licencia preferida.
- FFmpeg: LGPL (ver bin/FFMPEG-LICENSE.txt).
- Modelo Whisper: MIT (OpenAI).
- PyQt6: GPLv3 / Riverbank Commercial.
