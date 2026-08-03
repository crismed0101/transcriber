"""Hilos de trabajo: todo lo que no debe correr en el hilo de la interfaz.

Cargar el modelo, transcribir, consultar y descargar actualizaciones son operaciones
de segundos a minutos. Si corrieran en el hilo de la interfaz, Windows mostraria la
ventana como "no responde".

Todos siguen el mismo contrato: emiten senales para informar el avance y aceptan una
cancelacion cooperativa mediante `cancel()`.
"""
import os
import logging
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

import updater
from config import FFMPEG_BIN
from transcriber import EngineCancelled
from utils import NO_WINDOW

log = logging.getLogger(__name__)


def unlink(path):
    """Borra un archivo si existe, sin quejarse."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


class ModelLoadThread(QThread):
    """Carga el motor Whisper sin bloquear la interfaz.

    Es una subclase de verdad, no un QThread con `run` reasignado: asi la
    cancelacion y las senales quedan en el mismo objeto y no hay que adivinar a
    quien pertenece el estado.
    """
    attempt = pyqtSignal(str, str)   # (modelo, device) antes de cada intento
    done = pyqtSignal(str)           # "" = ok | "cancelado" | mensaje de error

    def __init__(self, whisper):
        super().__init__()
        self.whisper = whisper
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.whisper.load_model(
                should_cancel=lambda: self._cancelled,
                on_attempt=lambda name, device: self.attempt.emit(name, device),
            )
            self.done.emit("")
        except EngineCancelled:
            self.done.emit("cancelado")
        except Exception as ex:
            log.error("Error cargando el motor Whisper", exc_info=True)
            self.done.emit(str(ex))


class UpdateCheckThread(QThread):
    """Consulta si hay version nueva, sin bloquear la interfaz."""
    found = pyqtSignal(object)   # UpdateInfo, o None si no hay novedades

    def run(self):
        # check_for_update no lanza: cualquier problema de red devuelve None.
        self.found.emit(updater.check_for_update())


class UpdateDownloadThread(QThread):
    """Descarga y verifica el instalador de una version nueva."""
    progress = pyqtSignal(int, int)   # bytes descargados, bytes totales
    done = pyqtSignal(str, str)       # ruta, mensaje de error ("" si todo bien)

    def __init__(self, info):
        super().__init__()
        self.info = info
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            path = updater.download_installer(
                self.info,
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancelled,
            )
            self.done.emit(path, "")
        except updater.UpdateCancelled:
            self.done.emit("", "cancelado")
        except Exception as ex:
            log.error("Error descargando la actualizacion", exc_info=True)
            self.done.emit("", str(ex))


class BaseTranscribeThread(QThread):
    """Base compartida entre grabacion y archivo subido.

    Las subclases implementan `_get_input_path()` para producir el audio a procesar.
    """
    status = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    SIN_VOZ = (
        "No se detecto voz en el audio.\n\n"
        "Sugerencias:\n"
        "  - Verifica que el audio tenga voz humana, no solo musica o silencio.\n"
        "  - Reproduci el audio.mp3 (boton Audio) para confirmar que se grabo bien.\n"
        "  - Si grabaste del sistema, asegurate de que estaba sonando algo."
    )

    def __init__(self, whisper, session_dir, lang, initial_prompt=None):
        super().__init__()
        self.whisper = whisper
        self.session_dir = session_dir
        self.lang = lang
        self.initial_prompt = initial_prompt
        self._active_procs = []
        self._cancelled = False

    def cancel(self):
        """Aborto cooperativo: mata FFmpeg y corta el bucle de Whisper."""
        self._cancelled = True
        self.kill_subprocesses()

    def kill_subprocesses(self):
        for p in self._active_procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        self._active_procs.clear()

    # ── A implementar por las subclases ──
    def _get_input_path(self):
        raise NotImplementedError

    def _ffmpeg_input_args(self):
        return []

    def _cleanup_input(self, input_path):
        """Que hacer con el audio de origen al terminar. Por defecto, nada."""

    # ── Proceso ──
    def _convert(self, input_path, mp3, mono):
        """Genera el mp3 para el usuario y el WAV mono 16 kHz para Whisper."""
        extra = self._ffmpeg_input_args()
        self._active_procs = [
            subprocess.Popen(
                [FFMPEG_BIN, "-y", "-i", input_path, *extra, "-b:a", "128k", mp3],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            ),
            subprocess.Popen(
                [FFMPEG_BIN, "-y", "-i", input_path, *extra, "-ac", "1", "-ar", "16000", mono],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            ),
        ]
        for p in list(self._active_procs):
            p.wait()
        self._active_procs.clear()

    def run(self):
        input_path = None
        mono = mp3 = None
        reached_transcribe = False
        try:
            input_path = self._get_input_path()
            if not input_path:
                self.finished_err.emit("Sin audio detectado")
                return

            mp3 = os.path.join(self.session_dir, "audio.mp3")
            mono = os.path.join(self.session_dir, "_mono.wav")

            self.status.emit("Convirtiendo audio...")
            self._convert(input_path, mp3, mono)

            if self._cancelled:
                self.finished_err.emit("Cancelado")
                return
            if not os.path.exists(mono):
                self.finished_err.emit(
                    "FFmpeg no pudo procesar este audio. Puede estar dañado o en un "
                    "formato no soportado."
                )
                return
            if not os.path.exists(mp3):
                log.warning("FFmpeg no genero %s; sigo sin copia de audio", mp3)

            if not self.whisper.is_loaded:
                self.status.emit("Preparando el modelo...")

            self.status.emit("Transcribiendo...")
            reached_transcribe = True
            result = self.whisper.transcribe(
                mono, language=self.lang,
                on_progress=lambda pct, partial: self.progress.emit(pct, partial),
                should_cancel=lambda: self._cancelled,
                initial_prompt=self.initial_prompt,
            )
            result["text"] = result["text"].strip()

            if result.get("cancelled"):
                self.finished_err.emit("Cancelado")
                return

            if not result["text"]:
                result["text"] = self.SIN_VOZ
            self.finished_ok.emit(result)

        except EngineCancelled:
            self.finished_err.emit("Cancelado")
        except Exception as ex:
            log.error("Error en el procesamiento", exc_info=True)
            self.finished_err.emit(f"Error: {ex}")
        finally:
            self.kill_subprocesses()
            # El WAV temporal de Whisper no se conserva nunca.
            unlink(mono)
            # Si cancelamos antes de transcribir, el mp3 quedo a medias.
            if not reached_transcribe:
                unlink(mp3)
            if input_path:
                self._cleanup_input(input_path)


class ProcessThread(BaseTranscribeThread):
    """Procesa una grabacion recien terminada."""

    def __init__(self, audio, whisper, session_dir, lang, initial_prompt=None):
        super().__init__(whisper, session_dir, lang, initial_prompt)
        self.audio = audio

    def _get_input_path(self):
        return self.audio.stop_raw()

    def _cleanup_input(self, input_path):
        # El WAV crudo es intermedio: se reemplaza por audio.mp3.
        unlink(input_path)


class FileTranscribeThread(BaseTranscribeThread):
    """Transcribe un archivo subido o arrastrado. Nunca borra el original."""

    def __init__(self, whisper, file_path, session_dir, lang, initial_prompt=None):
        super().__init__(whisper, session_dir, lang, initial_prompt)
        self.file_path = file_path

    def _get_input_path(self):
        return self.file_path

    def _ffmpeg_input_args(self):
        # El archivo puede traer video; -vn descarta esa pista.
        return ["-vn"]
