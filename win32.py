"""Integracion con Windows: instancia unica y atajo de teclado global.

Las dos cosas que la app necesita del sistema operativo y que Qt no resuelve solo.
Aisladas aca para que main.py no cargue con detalles de la plataforma.
"""
import sys
import ctypes
import getpass
import logging

from PyQt6.QtCore import QAbstractNativeEventFilter
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

import version

if sys.platform == "win32":
    # `import ctypes` no arrastra wintypes; hace falta para leer el MSG del filtro
    # de eventos nativo que atiende el atajo global.
    import ctypes.wintypes

log = logging.getLogger(__name__)

# ── Instancia unica ──
# La clave lleva el usuario para que dos sesiones de Escritorio Remoto en la misma
# maquina no se bloqueen entre si.
try:
    _USER_TAG = getpass.getuser() or "default"
except Exception:
    _USER_TAG = "default"

INSTANCE_KEY = f"{version.APP_USER_MODEL_ID}.SingleInstance.v1.{_USER_TAG}"
SOCKET_TIMEOUT_MS = 800

# ── Atajo global (Win32) ──
# Con hwnd=NULL el atajo queda asociado al hilo y el WM_HOTKEY llega al filtro de
# eventos nativo de la aplicacion.
HOTKEY_ID = 1
HOTKEY_TEXT = "Ctrl+Shift+R"
_MOD_SHIFT = 0x0004
_MOD_CONTROL = 0x0002
_MOD_NOREPEAT = 0x4000
_VK_R = 0x52
_WM_HOTKEY = 0x0312


def try_acquire_single_instance():
    """False si ya hay otra instancia (a la que se le pide que se muestre)."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(SOCKET_TIMEOUT_MS):
        try:
            sock.write(b"SHOW")
            sock.flush()
            sock.waitForBytesWritten(500)
        finally:
            sock.disconnectFromServer()
        return False
    return True


class SingleInstanceServer:
    """Escucha a instancias posteriores y trae la ventana al frente.

    Args:
        window: objeto con un metodo `show_from_tray()`.
        on_lost: se llama si otra instancia gano la carrera y hay que salir.
    """

    def __init__(self, window, on_lost=None):
        self.window = window
        self.server = QLocalServer()
        # Limpiar un socket huerfano de un cierre anterior anormal.
        QLocalServer.removeServer(INSTANCE_KEY)
        if not self.server.listen(INSTANCE_KEY):
            log.warning("listen() fallo: %s; reintento la deteccion",
                        self.server.errorString())
            if not try_acquire_single_instance() and on_lost:
                log.info("Otra instancia gano la carrera; salgo")
                on_lost()
            return
        self.server.newConnection.connect(self._on_new)

    def _on_new(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        try:
            if sock.waitForReadyRead(500) and bytes(sock.readAll().data()) == b"SHOW":
                log.info("Otra instancia pidio mostrar la ventana")
                self.window.show_from_tray()
        finally:
            sock.disconnectFromServer()

    def close(self):
        self.server.close()
        QLocalServer.removeServer(INSTANCE_KEY)


class GlobalHotkey(QAbstractNativeEventFilter):
    """Atajo de teclado a nivel sistema mediante RegisterHotKey (Win32).

    QShortcut solo funciona con la ventana enfocada, asi que no servia para el caso
    que le da sentido al atajo: empezar a grabar con la app minimizada en la bandeja.
    """

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.registered = False

    def install(self, app):
        """Registra el atajo. False si no se pudo (otra app ya lo tiene)."""
        if sys.platform != "win32":
            return False
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, _MOD_CONTROL | _MOD_SHIFT | _MOD_NOREPEAT, _VK_R
            )
        except Exception:
            log.warning("RegisterHotKey no disponible", exc_info=True)
            return False
        if not ok:
            log.warning("No se pudo registrar el atajo global %s", HOTKEY_TEXT)
            return False
        app.installNativeEventFilter(self)
        self.registered = True
        log.info("Atajo global %s registrado", HOTKEY_TEXT)
        return True

    def remove(self, app):
        if not self.registered:
            return
        try:
            app.removeNativeEventFilter(self)
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:
            log.warning("No se pudo liberar el atajo global", exc_info=True)
        self.registered = False

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._callback()
                return True, 0
        return False, 0
