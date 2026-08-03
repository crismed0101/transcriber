"""Unica fuente de verdad de la identidad y la version de Transcriber.

Este modulo NO importa nada: lo consumen tanto la app como las herramientas de
build, y algunas corren fuera del entorno de la app.

Consumidores:
    main.py            -> identidad de la ventana, AppUserModelID, dialogo "Acerca de"
    Transcriber.spec   -> recurso VS_VERSION_INFO del .exe
    build.py           -> /DAppVersion= para ISCC
    Transcriber.iss    -> lo recibe de build.py

Para liberar una version: cambiar __version__ ACA Y SOLO ACA.
"""

__version__ = "1.1.0"

APP_NAME = "Transcriber"
APP_PUBLISHER = "CrisMed"
APP_URL = "https://github.com/crismed0101/transcriber"

# Repositorio de donde se descargan los instaladores y donde el actualizador
# consulta si hay version nueva. Tiene que ser PUBLICO: si fuera privado, la app
# necesitaria llevar un token de GitHub adentro, y un token dentro de un binario
# que se reparte no es secreto.
RELEASES_REPO = "crismed0101/transcriber"
RELEASES_URL = f"https://github.com/{RELEASES_REPO}/releases"
INSTALLER_LATEST_URL = f"{RELEASES_URL}/latest/download/{APP_NAME}-Setup.exe"
APP_DESCRIPTION = "Transcripcion de audio a texto con Whisper (offline, local)"
APP_COPYRIGHT = "Copyright (C) 2026 CrisMed. Licencia GPL-3.0."

# Identidad de la app para la barra de tareas de Windows. Sin esto, Windows
# agrupa la ventana bajo el icono generico de Python.
APP_USER_MODEL_ID = f"{APP_PUBLISHER}.{APP_NAME}.1"

# Organizacion para QSettings. Se mantiene separado de APP_PUBLISHER por si algun
# dia divergen (el publisher es texto legal, la org es una clave de registro).
APP_ORG = APP_PUBLISHER

# El recurso VS_FIXEDFILEINFO de Windows exige exactamente 4 enteros.
VERSION_TUPLE = tuple(int(p) for p in __version__.split(".")) + (0,)
assert len(VERSION_TUPLE) == 4, "__version__ debe tener el formato MAJOR.MINOR.PATCH"
