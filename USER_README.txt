============================================================
 TRANSCRIBER - Transcribir audio a texto, sin internet
============================================================

Transcribe con Whisper en tu propia PC. El audio nunca sale
de tu equipo.


USO RAPIDO
----------
1. Abri Transcriber.
2. La primera vez se descarga el modelo (entre 75 MB y 3 GB
   segun tu equipo). Es una sola vez; despues funciona sin
   internet.
3. Para grabar lo que estas escuchando:
   - Click en GRABAR.
   - Al terminar, click en DETENER.
   - Podes ponerle un nombre a la grabacion (opcional).
4. Para transcribir archivos que ya tenes:
   - Click en SUBIR ARCHIVO (podes elegir varios a la vez), o
   - Arrastralos sobre la ventana.

El texto aparece en pantalla mientras se transcribe. Se
guarda solo, y podes editarlo y volver a guardar.


DONDE QUEDAN TUS ARCHIVOS
-------------------------
Transcripciones y audios:
   Documentos\Transcriber\<fecha>\transcripcion-N\
       audio.mp3            copia del audio
       transcripcion.txt    el texto, con marcas de tiempo
       transcripcion.srt    subtitulos (si los exportas)

El boton "Abrir" te lleva directo a la carpeta de la
transcripcion que estas viendo, y "Historial" lista todas.

Modelos, ajustes y registro de errores:
   %LOCALAPPDATA%\Transcriber\

Desinstalar la app NO borra nada de esto.


ELEGIR EL MODELO
----------------
El desplegable "Modelo" define la calidad:

   Automatico        elige el mejor que tu equipo aguanta (recomendado)
   tiny              ~75 MB    el mas rapido, calidad basica
   base              ~145 MB   rapido, calidad aceptable
   small             ~480 MB   equilibrado
   medium            ~1.5 GB   bueno, necesita placa NVIDIA
   large-v3-turbo    ~1.6 GB   casi la calidad de large-v3 y mucho
                               mas rapido; ideal para audios largos
   large-v3          ~3 GB     la mejor calidad, necesita placa NVIDIA

Si elegis uno que no entra en la memoria de tu equipo, la app
baja sola al siguiente que si entra: no se rompe ni se cuelga.
Cambiar de modelo recarga el motor y puede descargar archivos
nuevos la primera vez.


VOCABULARIO Y ESTILO
--------------------
Click derecho en el icono de la bandeja > "Vocabulario y
estilo...".

Ahi hay un texto que el modelo usa como ejemplo: imita su
puntuacion, sus acentos y su forma de escribir. Sirve sobre
todo para nombres propios, siglas y jerga.

Por ejemplo, si tus audios hablan de una empresa o de terminos
tecnicos que la app escribe mal, agregalos ahi:

   Transcripcion en español, con puntuacion, acentos y
   mayusculas correctas. Terminos: Kubernetes, PostgreSQL,
   Dr. Martinez, ACME S.R.L.

Con eso deja de escribirlos mal. Si lo dejas vacio, no se usa
ninguno.


VELOCIDAD
---------
Con una placa NVIDIA la transcripcion es varias veces mas
rapida. Sin ella funciona igual, pero mas lento, y la app
elige un modelo mas liviano para compensar.

El recuadro de arriba a la izquierda te dice que esta usando:
"GPU: ..." o "CPU (lento)".


ATAJOS
------
Ctrl+Shift+R    Iniciar o detener la grabacion. Funciona
                aunque la app este minimizada en la bandeja.
                Si otro programa ya usa esa combinacion, el
                atajo responde solo con la ventana enfocada.

Click derecho sobre el texto: exportar subtitulos (.srt).

Cerrar con la X manda la app a la bandeja del sistema (al
lado del reloj). Para cerrarla de verdad: click derecho en el
icono de la bandeja > Salir.


PROBLEMAS FRECUENTES
--------------------
"Windows protegio su PC" al instalar
   La app no esta firmada digitalmente. Click en "Mas
   informacion" y despues en "Ejecutar de todas formas".

"FFmpeg no encontrado"
   Falta la carpeta bin\ junto al ejecutable. Reinstala.

Va muy lento
   Estas en CPU. Elegi un modelo mas chico (small o base), o
   usa una PC con placa NVIDIA.

"GPU NVIDIA detectada, pero sin CUDA"
   Actualiza los drivers desde nvidia.com/drivers y volve a
   abrir la app.

No graba nada / "Sin audio detectado"
   Para grabar lo que escuchas, Windows necesita un
   dispositivo de salida activo (parlantes o auriculares).
   Para dictar tu voz, cambia "Fuente" a Microfono.

Algo falla y no se por que
   El detalle queda en:
   %LOCALAPPDATA%\Transcriber\transcriber.log

   Y para un diagnostico completo, desde una consola:
   Transcriber.exe --selftest


LICENCIAS
---------
Transcriber se distribuye bajo GPL-3.0 (ver LICENSE).
   - FFmpeg: LGPL (ver bin\FFMPEG-LICENSE.txt)
   - Modelo Whisper: MIT (OpenAI)
   - PyQt6: GPL-3.0 o licencia comercial de Riverbank
   - faster-whisper y CTranslate2: MIT
