"""Coordinacion de las actualizaciones de la aplicacion.

Todo el ciclo -comprobar, ofrecer, descargar, verificar e instalar- vive aca y no
mezclado con la ventana principal. La ventana solo lo crea, escucha dos senales y le
pregunta si esta ocupado.

La logica sin interfaz (comparar versiones, descargar, verificar el SHA256) esta en
`updater`; este modulo es el puente entre eso y lo que ve el usuario.
"""
import logging
import datetime

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

import config
import updater
import version
import widgets
from workers import UpdateCheckThread, UpdateDownloadThread

log = logging.getLogger(__name__)

#: Cuanto esperar antes de volver a ofrecer si el usuario esta grabando o transcribiendo.
REINTENTO_SI_OCUPADO_MS = 120_000

#: Las notas de version pueden ser largas; en el dialogo se recortan.
MAX_NOTAS = 600


class UpdateController(QObject):
    """Busca versiones nuevas y las instala si el usuario acepta.

    Args:
        window: ventana padre de los dialogos.
        settings: QSettings donde se recuerdan la ultima comprobacion y la version
            omitida.
        progress: ProgressReporter para mostrar la descarga.
        is_busy: callable que devuelve True si la app esta grabando o transcribiendo.
    """

    #: Texto para la barra de estado. (mensaje, es_error)
    status = pyqtSignal(str, bool)
    #: Cambio en si hay una descarga en curso; la ventana refresca sus controles.
    busy_changed = pyqtSignal()
    #: El instalador quedo listo y verificado: la app debe cerrarse.
    install_requested = pyqtSignal()

    def __init__(self, window, settings, progress, is_busy):
        super().__init__(window)
        self._window = window
        self._settings = settings
        self._progress = progress
        self._is_busy = is_busy
        self._check_thread = None
        self._download_thread = None
        self._manual = False

    # ── Estado ──
    @property
    def is_downloading(self):
        return self._download_thread is not None

    def threads(self):
        """Hilos vivos, para que la ventana los cierre ordenadamente al salir."""
        return tuple(t for t in (self._check_thread, self._download_thread) if t)

    def cancel(self):
        """Aborta la descarga en curso, si la hay."""
        if self._download_thread is not None and self._download_thread.isRunning():
            self._download_thread.cancel()
            return True
        return False

    # ── Comprobacion ──
    def check_if_due(self):
        """Comprobacion automatica, como mucho una vez por dia."""
        last = self._settings.value(config.SETTING_LAST_UPDATE_CHECK, "", type=str)
        if last:
            try:
                transcurrido = datetime.datetime.now() - datetime.datetime.fromisoformat(last)
                if transcurrido.total_seconds() < config.UPDATE_CHECK_INTERVAL_HOURS * 3600:
                    return
            except ValueError:
                pass  # valor corrupto: se vuelve a comprobar
        self._start_check(manual=False)

    def check_now(self):
        """Comprobacion manual, desde el menu de la bandeja."""
        self._start_check(manual=True)

    def _start_check(self, manual):
        if self._check_thread is not None or self._download_thread is not None:
            return
        self._manual = manual
        if manual:
            self.status.emit("Buscando actualizaciones...", False)
        self._check_thread = UpdateCheckThread()
        self._check_thread.found.connect(self._on_found)
        self._check_thread.finished.connect(self._on_check_done)
        self._check_thread.start()

    def _on_check_done(self):
        self._check_thread = None

    def _on_found(self, info):
        self._settings.setValue(
            config.SETTING_LAST_UPDATE_CHECK,
            datetime.datetime.now().isoformat(timespec="seconds"),
        )
        if info is None:
            if self._manual:
                self.status.emit("Listo", False)
                QMessageBox.information(
                    self._window, "Sin novedades",
                    f"Ya tenes la ultima version ({version.__version__}).",
                )
            return

        omitida = self._settings.value(config.SETTING_SKIPPED_VERSION, "", type=str)
        if not self._manual and info.version == omitida:
            log.info("La version %s fue omitida por el usuario", info.version)
            return
        self._prompt(info)

    # ── Ofrecimiento ──
    def _prompt(self, info):
        """Ofrece actualizar. Nunca interrumpe una grabacion ni una transcripcion."""
        if self._is_busy():
            QTimer.singleShot(REINTENTO_SI_OCUPADO_MS, lambda: self._prompt(info))
            return
        self.status.emit("Listo", False)

        notas = info.notes
        if len(notas) > MAX_NOTAS:
            notas = notas[:MAX_NOTAS].rsplit("\n", 1)[0] + "\n..."

        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Hay una version nueva")
        box.setText(
            f"<b>{version.APP_NAME} {info.version}</b> ya esta disponible.<br>"
            f"Tenes instalada la {version.__version__}."
        )
        if notas:
            box.setInformativeText(notas)
        if info.size:
            box.setDetailedText(
                f"Se descargaran {info.size / widgets.MB:.0f} MB desde:\n{info.installer_url}"
            )
        actualizar = box.addButton("Actualizar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        omitir = box.addButton("Omitir esta version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(actualizar)
        box.exec()

        elegido = box.clickedButton()
        if elegido is actualizar:
            self._start_download(info)
        elif elegido is omitir:
            self._settings.setValue(config.SETTING_SKIPPED_VERSION, info.version)
            log.info("El usuario omitio la version %s", info.version)

    # ── Descarga ──
    def _start_download(self, info):
        self.status.emit("Descargando actualizacion...", False)
        self._progress.megabytes(0, info.size / widgets.MB, cancelable=True)

        self._download_thread = UpdateDownloadThread(info)
        self._download_thread.progress.connect(self._on_progress)
        self._download_thread.done.connect(self._on_downloaded)
        self._download_thread.finished.connect(self._on_download_done)
        self._download_thread.start()
        self.busy_changed.emit()

    def _on_progress(self, descargado, total):
        self._progress.megabytes(descargado / widgets.MB, total / widgets.MB,
                                 cancelable=True)

    def _on_download_done(self):
        self._download_thread = None
        self.busy_changed.emit()

    def _on_downloaded(self, path, error):
        self._progress.hide()

        if error == "cancelado":
            self.status.emit("Actualizacion cancelada", False)
            return
        if error:
            self.status.emit("No se pudo actualizar", True)
            QMessageBox.warning(
                self._window, "No se pudo actualizar",
                f"{error}\n\nPodes descargarla a mano desde:\n{version.RELEASES_URL}",
            )
            return

        QMessageBox.information(
            self._window, "Listo para instalar",
            f"{version.APP_NAME} se va a cerrar para instalar la version nueva.\n\n"
            "Cuando el instalador termine, la app se abre de nuevo.",
        )
        updater.launch_installer(path)
        self.install_requested.emit()
