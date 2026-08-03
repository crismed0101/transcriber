"""Transcriber — app de escritorio para transcribir audio a texto con Whisper."""
import os
import re
import sys
import glob
import getpass
import shutil
import tempfile
import logging
import logging.handlers
import subprocess
import datetime
import traceback
import ctypes

if sys.platform == "win32":
    # `import ctypes` no arrastra wintypes; hace falta para leer el MSG del
    # filtro de eventos nativo que atiende el hotkey global.
    import ctypes.wintypes

# paths.py se importa antes que faster_whisper para fijar HF_HOME al directorio
# de modelos de la app.
import paths
import state
import version

# El autodiagnostico corre sin interfaz: se atiende antes de construir nada de Qt.
if "--selftest" in sys.argv:
    import selftest

    sys.exit(selftest.run())

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QComboBox, QLabel, QProgressBar, QFileDialog,
    QSystemTrayIcon, QMenu, QSplashScreen, QMessageBox,
    QDialog, QListWidget, QListWidgetItem, QInputDialog,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSettings, QAbstractNativeEventFilter
from PyQt6.QtGui import (
    QShortcut, QKeySequence, QPixmap, QPainter, QColor, QFont, QIcon, QAction,
)
from PyQt6.QtNetwork import QLocalSocket, QLocalServer

# Pre-migrar log/settings ANTES de abrir el FileHandler: Windows no deja mover
# archivos en uso.
state.pre_migrate_log_settings()


# ── Constantes ──
# Clave per-user para que dos sesiones de Escritorio Remoto no colisionen.
try:
    _USER_TAG = getpass.getuser() or "default"
except Exception:
    _USER_TAG = "default"
SINGLE_INSTANCE_KEY = f"{version.APP_USER_MODEL_ID}.SingleInstance.v1.{_USER_TAG}"

LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
SOCKET_TIMEOUT_MS = 800
QUEUE_GAP_MS = 150          # respiro de UI entre archivos de una cola
THREAD_STOP_TIMEOUT_MS = 5000

# Hotkey global (Win32). Con hwnd=NULL el hotkey queda asociado al hilo y el
# WM_HOTKEY llega al filtro de eventos nativo de la aplicacion.
HOTKEY_ID = 1
_MOD_SHIFT = 0x0004
_MOD_CONTROL = 0x0002
_MOD_NOREPEAT = 0x4000
_VK_R = 0x52
_WM_HOTKEY = 0x0312
HOTKEY_TEXT = "Ctrl+Shift+R"


def _build_log_handlers():
    """Handler de archivo con rotacion, mas consola si la hay.

    Si la ubicacion preferida es de solo lectura, cae a %TEMP%.
    """
    handlers = []
    candidates = [
        paths.log_path(),
        os.path.join(tempfile.gettempdir(), "Transcriber", "transcriber.log"),
    ]
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handlers.append(logging.handlers.RotatingFileHandler(
                path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            ))
            break
        except OSError:
            continue
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    return handlers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_build_log_handlers(),
)
log = logging.getLogger(__name__)


def _excepthook(exc_type, exc_value, exc_tb):
    """Registra la excepcion y, si hay interfaz, la muestra.

    Con console=False una excepcion sin capturar mataba el proceso en silencio: el
    usuario veia la app "no abrir" y no habia forma de que reportara nada util.
    """
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.critical("Excepcion no capturada:\n%s", detail)
    if QApplication.instance() is not None:
        try:
            QMessageBox.critical(
                None, f"{version.APP_NAME} — error inesperado",
                f"Ocurrio un error inesperado:\n\n{exc_value}\n\n"
                f"El detalle quedo en:\n{paths.log_path()}",
            )
        except Exception:
            pass


sys.excepthook = _excepthook

# Identidad en la barra de tareas: sin esto Windows agrupa la ventana bajo Python.
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            version.APP_USER_MODEL_ID
        )
    except Exception as ex:
        log.warning("No se pudo fijar el AppUserModelID: %s", ex)

# En modo desarrollo las DLL de CUDA viven dentro del venv y hay que sumarlas al
# search path. En el .exe empaquetado ya quedan junto a ctranslate2 (ver el .spec).
if sys.platform == "win32" and not paths.is_frozen():
    for _base in (os.path.dirname(sys.executable),
                  os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Scripts")):
        for _dll_dir in glob.glob(os.path.join(_base, "..", "Lib", "site-packages",
                                               "nvidia", "*", "bin")):
            _dll_dir = os.path.abspath(_dll_dir)
            try:
                os.add_dll_directory(_dll_dir)
            except OSError:
                continue
            os.environ["PATH"] = _dll_dir + os.pathsep + os.environ.get("PATH", "")

import config
import hardware
import updater
from config import OUTPUT_DIR, LANGUAGES, FFMPEG_BIN, AUDIO_FORMATS, AUDIO_EXTS
from audio_capture import AudioCapture, SOURCE_LOOPBACK, SOURCE_MIC
from transcriber import (
    Transcriber, EngineCancelled, is_model_downloaded, model_cache_dir,
    DEFAULT_INITIAL_PROMPT,
)
from subtitles import build_srt, format_segments_with_timestamps
from utils import NO_WINDOW, resource_path, sanitize_folder_name

AUDIO_SOURCES = {
    "Audio del sistema": SOURCE_LOOPBACK,
    "Microfono": SOURCE_MIC,
}


# ── Paleta (inspirada en GitHub Dark) ──
C_BG = "#0d1117"
C_SURFACE = "#161b22"
C_BORDER = "#21262d"
C_BORDER_HI = "#30363d"
C_TEXT = "#c9d1d9"
C_TEXT_DIM = "#8b949e"
C_TEXT_MUTED = "#484f58"
C_ACCENT = "#388bfd"
C_RED = "#da3633"
C_RED_HI = "#f04438"
C_GREEN = "#238636"
C_GREEN_HI = "#2ea043"
C_AMBER = "#e6a817"
C_AMBER_HI = "#f1bf3a"
C_BLUE = "#1f6feb"
C_BLUE_HI = "#388bfd"
C_GRAY = "#484f58"
C_GRAY_HI = "#6e7681"

STYLE = f"""
QMainWindow {{ background-color: {C_BG}; }}
QWidget {{ background-color: transparent; }}
QLabel {{ color: {C_TEXT_DIM}; font-size: 12px; }}

QTextEdit {{
    background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 12px; padding: 14px; font-family: 'Segoe UI', Consolas; font-size: 13px;
    selection-background-color: #264f78;
}}
QTextEdit:focus {{ border: 1px solid {C_ACCENT}; }}
QTextEdit[droptarget="true"] {{ border: 2px dashed {C_BLUE}; background-color: #0c1a2b; }}

QComboBox {{
    background-color: {C_BORDER}; color: {C_TEXT}; border: 1px solid {C_BORDER_HI};
    border-radius: 8px; padding: 6px 12px; font-size: 12px; min-width: 120px;
}}
QComboBox:hover {{ border-color: {C_ACCENT}; }}
QComboBox:disabled {{ color: {C_TEXT_MUTED}; border-color: {C_BORDER}; }}
QComboBox::drop-down {{ border: none; padding-right: 10px; }}
QComboBox QAbstractItemView {{
    background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER_HI};
    selection-background-color: #264f78; padding: 4px; outline: 0;
}}

QProgressBar {{
    background-color: {C_SURFACE}; border: 1px solid {C_BORDER}; border-radius: 6px;
    height: 12px; text-align: center; font-size: 10px; color: {C_TEXT_DIM};
}}
QProgressBar::chunk {{ background-color: {C_GREEN}; border-radius: 5px; }}

QMenu {{ background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER_HI}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: #264f78; }}
QMenu::separator {{ height: 1px; background: {C_BORDER_HI}; margin: 4px 6px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {C_BORDER_HI}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C_GRAY_HI}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QToolTip {{
    background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER_HI};
    padding: 4px 8px; border-radius: 6px;
}}
"""


def _btn_style(bg, hover_bg, height=34, radius=18, font_size=12, color="white"):
    return (
        f"QPushButton {{ background-color: {bg}; color: {color}; border: none; "
        f"border-radius: {radius}px; padding: 0 18px; font-weight: bold; font-size: {font_size}px; "
        f"min-height: {height}px; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; }}"
        f"QPushButton:pressed {{ background-color: {bg}; }}"
    )


def _btn_disabled(height=34, radius=18, font_size=12):
    return (
        f"QPushButton {{ background-color: {C_SURFACE}; color: {C_BORDER_HI}; border: none; "
        f"border-radius: {radius}px; padding: 0 18px; font-weight: bold; font-size: {font_size}px; "
        f"min-height: {height}px; }}"
    )


def _btn_outline(border, hover_border, color, height=32, radius=10, font_size=12):
    return (
        f"QPushButton {{ background-color: transparent; color: {color}; border: 1px solid {border}; "
        f"border-radius: {radius}px; padding: 0 14px; font-weight: 600; font-size: {font_size}px; "
        f"min-height: {height}px; }}"
        f"QPushButton:hover {{ border-color: {hover_border}; color: {C_TEXT}; }}"
    )


S_REC = _btn_style(C_RED, C_RED_HI, height=44, radius=22, font_size=13)
S_REC_OFF = _btn_style(C_GRAY, C_GRAY_HI, height=44, radius=22, font_size=13)
S_REC_DISABLED = _btn_disabled(height=44, radius=22, font_size=13)
S_PAUSE = _btn_style(C_AMBER, C_AMBER_HI)
S_RESUME = _btn_style(C_GREEN, C_GREEN_HI)
S_STOP = _btn_style(C_RED, C_RED_HI)
S_UPLOAD = _btn_style(C_BLUE, C_BLUE_HI)
S_BTN_DISABLED = _btn_disabled()

S_OPEN = _btn_style(C_GREEN, C_GREEN_HI, height=30, radius=10, font_size=11)
S_COPY = _btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_DIM, height=30, radius=10, font_size=11)
S_FOLDER = _btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_MUTED, height=30, radius=10, font_size=11)
S_OPEN_DISABLED = _btn_disabled(height=30, radius=10, font_size=11)
S_COPY_DISABLED = _btn_disabled(height=30, radius=10, font_size=11)

S_CHIP = (f"background-color: {C_SURFACE}; border: 1px solid {C_BORDER}; "
          f"border-radius: 12px; padding: 4px 12px; font-size: 11px; color: {C_TEXT_DIM};")
S_CHIP_OK = (f"background-color: rgba(35,134,54,0.15); border: 1px solid {C_GREEN}; "
             f"border-radius: 12px; padding: 4px 12px; font-size: 11px; color: {C_GREEN_HI};")
S_CHIP_BUSY = (f"background-color: rgba(230,168,23,0.12); border: 1px solid {C_AMBER}; "
               f"border-radius: 12px; padding: 4px 12px; font-size: 11px; color: {C_AMBER_HI};")
S_CHIP_ERR = (f"background-color: {C_RED}; border: none; border-radius: 12px; "
              f"padding: 4px 12px; font-size: 11px; color: white;")
S_CHIP_HW = (f"background-color: transparent; border: 1px solid {C_BORDER_HI}; "
             f"border-radius: 10px; padding: 3px 10px; font-size: 10px; color: {C_TEXT_DIM};")
S_CHIP_HW_GPU = (f"background-color: rgba(56,139,253,0.10); border: 1px solid {C_BLUE_HI}; "
                 f"border-radius: 10px; padding: 3px 10px; font-size: 10px; "
                 f"color: {C_BLUE_HI}; font-weight: 600;")


def make_app_icon():
    """Carga icon.ico si existe; si no, dibuja uno en runtime."""
    ico_path = resource_path("icon.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)

    icon = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(C_RED))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, s - 2, s - 2)
        p.setPen(QColor("white"))
        p.setFont(QFont("Arial", int(s * 0.45), QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "T")
        p.end()
        icon.addPixmap(pm)
    return icon


def make_splash_pixmap():
    """Pixmap del splash (380x220, tema oscuro)."""
    pm = QPixmap(380, 220)
    pm.fill(QColor(C_BG))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    p.setPen(QColor(C_BORDER))
    p.drawRoundedRect(0, 0, 379, 219, 12, 12)

    cx, cy, r = 190, 80, 32
    p.setBrush(QColor(C_RED))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
    p.setPen(QColor("white"))
    p.setFont(QFont("Arial", 28, QFont.Weight.Bold))
    p.drawText(cx - r, cy - r, r * 2, r * 2, Qt.AlignmentFlag.AlignCenter, "T")

    p.setPen(QColor("#ff6b6b"))
    p.setFont(QFont("Arial", 16, QFont.Weight.Bold))
    p.drawText(pm.rect().adjusted(0, 130, 0, 0),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
               version.APP_NAME.upper())

    p.setPen(QColor(C_TEXT_MUTED))
    p.setFont(QFont("Arial", 9))
    p.drawText(pm.rect().adjusted(0, 158, 0, 0),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
               f"v{version.__version__}")
    p.end()
    return pm


# ── Hilos de trabajo ──
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


class _BaseTranscribeThread(QThread):
    """Base compartida entre grabacion y archivo subido.

    Las subclases implementan `_get_input_path()` para producir el audio a procesar.
    """
    status = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

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

    def _get_input_path(self):
        raise NotImplementedError

    def _ffmpeg_input_args(self):
        return []

    def _cleanup_input(self, input_path):
        """Que hacer con el audio de origen al terminar. Por defecto, nada."""

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
                result["text"] = (
                    "No se detecto voz en el audio.\n\n"
                    "Sugerencias:\n"
                    "  - Verifica que el audio tenga voz humana, no solo musica o silencio.\n"
                    "  - Reproduci el audio.mp3 (boton Audio) para confirmar que se grabo bien.\n"
                    "  - Si grabaste del sistema, asegurate de que estaba sonando algo."
                )
            self.finished_ok.emit(result)

        except EngineCancelled:
            self.finished_err.emit("Cancelado")
        except Exception as ex:
            log.error("Error en el procesamiento", exc_info=True)
            self.finished_err.emit(f"Error: {ex}")
        finally:
            self.kill_subprocesses()
            # El WAV temporal de Whisper no se conserva nunca.
            _unlink(mono)
            # Si cancelamos antes de transcribir, el mp3 quedo a medias.
            if not reached_transcribe:
                _unlink(mp3)
            if input_path:
                self._cleanup_input(input_path)


class ProcessThread(_BaseTranscribeThread):
    """Procesa una grabacion recien terminada."""

    def __init__(self, audio, whisper, session_dir, lang, initial_prompt=None):
        super().__init__(whisper, session_dir, lang, initial_prompt)
        self.audio = audio

    def _get_input_path(self):
        return self.audio.stop_raw()

    def _cleanup_input(self, input_path):
        # El WAV crudo es intermedio: se reemplaza por audio.mp3.
        _unlink(input_path)


class FileTranscribeThread(_BaseTranscribeThread):
    """Transcribe un archivo subido o arrastrado. Nunca borra el original."""

    def __init__(self, whisper, file_path, session_dir, lang, initial_prompt=None):
        super().__init__(whisper, session_dir, lang, initial_prompt)
        self.file_path = file_path

    def _get_input_path(self):
        return self.file_path

    def _ffmpeg_input_args(self):
        # El archivo puede traer video; -vn descarta esa pista.
        return ["-vn"]


def _unlink(path):
    """Borra un archivo si existe, sin quejarse."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Instancia unica ──
def try_acquire_single_instance():
    """False si ya hay otra instancia (a la que se le pide que se muestre)."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
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
    """Escucha a instancias posteriores y trae la ventana al frente."""

    def __init__(self, window):
        self.window = window
        self.server = QLocalServer()
        # Limpiar un socket huerfano de un cierre anterior anormal.
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        if not self.server.listen(SINGLE_INSTANCE_KEY):
            log.warning("listen() fallo: %s; reintento la deteccion",
                        self.server.errorString())
            if not try_acquire_single_instance():
                log.info("Otra instancia gano la carrera; salgo")
                QApplication.quit()
                sys.exit(0)
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
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)


# ── Hotkey global ──
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
            # Tipicamente otra aplicacion ya se quedo con la combinacion.
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


# ── Historial ──
_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRANSCRIPCION_DIR_RE = re.compile(r"^transcripcion-(\d+)( \(.+\))?$")


class HistoryDialog(QDialog):
    """Lista las transcripciones pasadas (mas recientes arriba) y permite recargarlas."""

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historial de transcripciones")
        self.setMinimumSize(620, 480)
        self.output_dir = output_dir
        self.selected_dir = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        info = QLabel("Doble click para cargar; click derecho para abrir la carpeta o borrar.")
        info.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px;")
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            f"QListWidget {{ background-color: {C_SURFACE}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 8px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 10px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background-color: #264f78; }}"
            f"QListWidget::item:hover {{ background-color: {C_BORDER_HI}; }}"
        )
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        load_btn = QPushButton("Cargar")
        load_btn.setStyleSheet(_btn_style(C_GREEN, C_GREEN_HI, height=30, radius=8, font_size=11))
        load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.clicked.connect(self._on_load)
        bottom.addWidget(load_btn)
        close_btn = QPushButton("Cerrar")
        close_btn.setStyleSheet(_btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_DIM,
                                             height=30, radius=8, font_size=11))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self._populate()

    def _populate(self):
        if not os.path.isdir(self.output_dir):
            return
        try:
            date_dirs = sorted(
                (d for d in os.listdir(self.output_dir)
                 if _DATE_DIR_RE.match(d)
                 and os.path.isdir(os.path.join(self.output_dir, d))),
                reverse=True,
            )
        except OSError:
            return
        for date_dir in date_dirs:
            date_path = os.path.join(self.output_dir, date_dir)
            try:
                sessions = [s for s in os.listdir(date_path)
                            if _TRANSCRIPCION_DIR_RE.match(s)
                            and os.path.isdir(os.path.join(date_path, s))]
            except OSError:
                continue
            sessions.sort(key=lambda x: int(_TRANSCRIPCION_DIR_RE.match(x).group(1)),
                          reverse=True)
            for s in sessions:
                full = os.path.join(date_path, s)
                header = f"{date_dir}  -  {s}"
                meta = self._metadata(full)
                if meta:
                    header += f"   ({meta})"
                preview = self._load_preview(full)
                item = QListWidgetItem(header + (f"\n   {preview}" if preview else ""))
                item.setData(Qt.ItemDataRole.UserRole, full)
                self.list_widget.addItem(item)

    @staticmethod
    def _load_preview(session_dir, max_chars=120):
        txt = os.path.join(session_dir, "transcripcion.txt")
        if not os.path.isfile(txt):
            return "(sin transcripcion.txt)"
        try:
            with open(txt, encoding="utf-8") as f:
                content = f.read(max_chars + 20).replace("\n", " ").strip()
            return content[:max_chars] + "..." if len(content) > max_chars else content
        except OSError:
            return ""

    @staticmethod
    def _metadata(session_dir):
        """Hora del audio, duracion estimada e indicador de SRT."""
        bits = []
        mp3 = os.path.join(session_dir, "audio.mp3")
        if os.path.isfile(mp3):
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(mp3))
                bits.append(mtime.strftime("%H:%M"))
                # A 128 kbps constantes, 1 segundo son 16 KB.
                dur_sec = int(os.path.getsize(mp3) / 16000)
                if dur_sec > 0:
                    m, s = divmod(dur_sec, 60)
                    h, m = divmod(m, 60)
                    bits.append(f"{h}h{m:02d}m" if h else
                                (f"{m}m{s:02d}s" if m else f"{s}s"))
            except OSError:
                pass
        if os.path.isfile(os.path.join(session_dir, "transcripcion.srt")):
            bits.append(".srt")
        return " - ".join(bits)

    def _on_double_click(self, item):
        self.selected_dir = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_load(self):
        item = self.list_widget.currentItem()
        if item:
            self.selected_dir = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        load_act = menu.addAction("Cargar en el editor")
        open_act = menu.addAction("Abrir carpeta")
        menu.addSeparator()
        delete_act = menu.addAction("Borrar transcripcion...")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))

        if chosen == load_act:
            self.selected_dir = path
            self.accept()
        elif chosen == open_act:
            open_in_explorer(path)
        elif chosen == delete_act:
            self._delete(item, path)

    def _delete(self, item, path):
        reply = QMessageBox.question(
            self, "Borrar transcripcion",
            f"¿Borrar permanentemente esta sesion?\n\n{os.path.basename(path)}\n\n"
            "Se elimina la carpeta entera (audio.mp3 + transcripcion.txt + .srt si lo hay).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(path, ignore_errors=True)
        date_dir = os.path.dirname(path)
        try:
            if os.path.isdir(date_dir) and not os.listdir(date_dir):
                os.rmdir(date_dir)
        except OSError:
            pass
        self.list_widget.takeItem(self.list_widget.row(item))


def open_in_explorer(path):
    """Abre una carpeta o archivo con la aplicacion asociada del sistema."""
    try:
        os.startfile(path)
    except (OSError, AttributeError) as ex:
        log.warning("No se pudo abrir %s: %s", path, ex)


class TranscriberApp(QMainWindow):
    def __init__(self, app_icon=None):
        super().__init__()
        self._hw = hardware.summary()
        log.info("Hardware: %s", self._hw)

        self.audio = AudioCapture()
        self.whisper = Transcriber()
        self.settings = QSettings(paths.settings_ini_path(), QSettings.Format.IniFormat)

        self.is_recording = False
        self.is_paused = False
        self.is_processing = False
        self.current_text = ""

        self._session_dir = None
        self._segments = []
        self._text_dirty = False
        self._record_start = None
        self._pause_total = datetime.timedelta()
        self._pause_start = None
        self._pending_name = None
        self._file_queue = []
        self._queue_total = 0
        self._quit_requested = False
        self._capture_error_shown = False
        self._transcribe_started_at = None
        self._process_thread = None
        self._file_thread = None
        self._load_thread = None
        self._update_check_thread = None
        self._update_download_thread = None
        self._manual_update_check = False
        self._download_timer = None
        self._download_dir = None
        self._download_target_mb = 0
        self._app_icon = app_icon or make_app_icon()
        self._hotkey = None
        self._hotkey_shortcut = None
        self._single_server = None

        self._init_ui()
        self._restore_settings()
        self._init_timer()
        self._init_tray()
        self.setAcceptDrops(True)
        self._check_dependencies()
        self._start_engine_load()
        QTimer.singleShot(800, self._maybe_warn_cpu)
        # Unos segundos despues, para no competir con la carga del modelo.
        QTimer.singleShot(6000, self._check_updates_if_due)

    # ── Persistencia ──
    def _restore_settings(self):
        defaults = {
            config.SETTING_LANGUAGE: "Español",
            config.SETTING_SOURCE: "Audio del sistema",
            config.SETTING_MODEL: config.MODEL_AUTO,
        }
        combos = {
            config.SETTING_LANGUAGE: self.lang_combo,
            config.SETTING_SOURCE: self.source_combo,
            config.SETTING_MODEL: self.model_combo,
        }
        for key, combo in combos.items():
            value = self.settings.value(key, type=str) or defaults[key]
            idx = combo.findText(value)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

        self.whisper.set_preferred_model(self._selected_model())

        geom = self.settings.value(config.SETTING_GEOMETRY)
        if geom is not None:
            try:
                self.restoreGeometry(geom)
            except (TypeError, ValueError):
                pass

    def _save_settings(self):
        self.settings.setValue(config.SETTING_LANGUAGE, self.lang_combo.currentText())
        self.settings.setValue(config.SETTING_SOURCE, self.source_combo.currentText())
        self.settings.setValue(config.SETTING_MODEL, self.model_combo.currentText())
        self.settings.setValue(config.SETTING_GEOMETRY, self.saveGeometry())

    def _selected_model(self):
        """Modelo elegido en la interfaz; None significa automatico."""
        text = self.model_combo.currentText()
        return None if text == config.MODEL_AUTO else text

    def _current_initial_prompt(self):
        """Texto que orienta el estilo y el vocabulario de la transcripcion."""
        guardado = self.settings.value(config.SETTING_INITIAL_PROMPT, None, type=str)
        return DEFAULT_INITIAL_PROMPT if guardado is None else guardado

    def _edit_initial_prompt(self):
        """Permite ajustar el texto de referencia que se le pasa al modelo."""
        texto, ok = QInputDialog.getMultiLineText(
            self, "Vocabulario y estilo",
            "Whisper imita este texto: escribilo con la puntuación y los acentos que\n"
            "querés, e incluí nombres propios, siglas o jerga que aparezcan en tus\n"
            "audios para que no los escriba mal.\n\n"
            "Dejalo vacío para no usar ninguno.",
            self._current_initial_prompt(),
        )
        if not ok:
            return
        self.settings.setValue(config.SETTING_INITIAL_PROMPT, texto.strip())
        self._set_status("Vocabulario actualizado")

    # ── Construccion de la interfaz ──
    def _init_ui(self):
        self.setWindowTitle(version.APP_NAME)
        self._apply_adaptive_geometry()
        self.setStyleSheet(STYLE)
        self.setWindowIcon(self._app_icon)

        central = QWidget()
        central.setStyleSheet(f"background-color: {C_BG};")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_record_row())
        layout.addWidget(self._build_options_row())
        layout.addWidget(self._build_editor(), stretch=1)
        layout.addWidget(self._build_progress_row())
        layout.addWidget(self._build_footer())

        # Parpadeo del punto rojo mientras se graba.
        self._rec_pulse = QTimer(self)
        self._rec_pulse.setInterval(600)
        self._rec_pulse.timeout.connect(self._toggle_rec_dot)
        self._rec_dot_visible = True

    def _apply_adaptive_geometry(self):
        """Tamano inicial proporcional a la pantalla.

        Un tamano fijo se sale de pantalla en netbooks de 1366x768 y se ve diminuto
        en un monitor 4K.
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(680, 520)
            return
        available = screen.availableGeometry()
        width = max(560, min(760, int(available.width() * 0.55)))
        height = max(420, min(640, int(available.height() * 0.70)))
        self.setMinimumSize(min(560, available.width() - 40),
                            min(400, available.height() - 60))
        self.resize(width, height)
        self.move(available.center().x() - width // 2,
                  available.center().y() - height // 2)

    def _build_header(self):
        header = QWidget()
        header.setStyleSheet(f"background-color: {C_SURFACE}; border-bottom: 1px solid {C_BORDER};")
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(10)

        logo = QLabel()
        pm = QPixmap(22, 22)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(C_RED))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 22, 22)
        p.setPen(QColor("white"))
        p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "T")
        p.end()
        logo.setPixmap(pm)
        row.addWidget(logo)

        title = QLabel(version.APP_NAME.upper())
        title.setStyleSheet(
            f"color: {C_TEXT}; font-size: 14px; font-weight: bold; letter-spacing: 2px;"
        )
        row.addWidget(title)

        self.hw_chip = QLabel()
        row.addWidget(self.hw_chip)
        self._refresh_hw_chip()

        row.addStretch()

        self.rec_dot = QLabel("●")
        self.rec_dot.setStyleSheet(f"color: {C_RED}; font-size: 18px;")
        self.rec_dot.hide()
        row.addWidget(self.rec_dot)

        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet(
            f"color: {C_RED_HI}; font-size: 15px; font-weight: bold; "
            f"font-family: 'Consolas', monospace;"
        )
        row.addWidget(self.timer_label)

        self.status_chip = QLabel("Iniciando...")
        self.status_chip.setStyleSheet(S_CHIP_BUSY)
        row.addWidget(self.status_chip)
        return header

    def _refresh_hw_chip(self):
        """Muestra donde va a correr Whisper. Se actualiza si el motor degrada."""
        hw = self._hw
        if self.whisper.device == "cuda":
            text = f"GPU: {hw['gpu_short'] or 'NVIDIA'}"
            style = S_CHIP_HW_GPU
        else:
            text = f"CPU (lento) - {hw['ram_gb']:.0f} GB RAM"
            style = S_CHIP_BUSY
        self.hw_chip.setText(text)
        self.hw_chip.setStyleSheet(style)
        self.hw_chip.setToolTip(
            f"Motor: {self.whisper.describe()}\n"
            f"VRAM: {hw['vram_gb']:.1f} GB - RAM: {hw['ram_gb']:.1f} GB"
            + (f"\nDriver NVIDIA: {hw['driver']}" if hw["driver"] else "")
        )

    def _build_record_row(self):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(20, 14, 20, 6)
        row.setSpacing(8)

        self.rec_btn = QPushButton("GRABAR")
        self.rec_btn.setStyleSheet(S_REC)
        self.rec_btn.setMinimumWidth(140)
        self.rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rec_btn.setToolTip(f"Grabar audio del sistema. Atajo: {HOTKEY_TEXT}")
        self.rec_btn.clicked.connect(self._on_record)
        row.addWidget(self.rec_btn)

        self.pause_btn = QPushButton("PAUSAR")
        self.pause_btn.setStyleSheet(S_BTN_DISABLED)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self._on_pause)
        row.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("DETENER")
        self.stop_btn.setStyleSheet(S_BTN_DISABLED)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self._on_stop)
        row.addWidget(self.stop_btn)

        row.addStretch()

        label = QLabel("Fuente")
        label.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        row.addWidget(label)

        self.source_combo = QComboBox()
        self.source_combo.addItems(AUDIO_SOURCES.keys())
        self.source_combo.setMinimumHeight(30)
        self.source_combo.setToolTip(
            "Audio del sistema: lo que escuchas por parlantes o auriculares.\n"
            "Microfono: tu voz, para dictado."
        )
        self.source_combo.currentTextChanged.connect(
            lambda text: self.settings.setValue(config.SETTING_SOURCE, text)
        )
        row.addWidget(self.source_combo)
        return row_widget

    def _build_options_row(self):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(20, 0, 20, 8)
        row.setSpacing(8)

        self.upload_btn = QPushButton("SUBIR ARCHIVO")
        self.upload_btn.setStyleSheet(S_UPLOAD)
        self.upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_btn.setToolTip("Transcribir archivos de audio, o arrastralos a la ventana")
        self.upload_btn.clicked.connect(self._on_upload)
        row.addWidget(self.upload_btn)

        row.addStretch()

        model_label = QLabel("Modelo")
        model_label.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        row.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.addItem(config.MODEL_AUTO)
        self.model_combo.addItems(hardware.MODEL_NAMES)
        self.model_combo.setMinimumHeight(34)
        self.model_combo.setToolTip(
            f"{config.MODEL_AUTO}: elige el mejor modelo que tu equipo aguanta.\n"
            "Modelos mas grandes transcriben mejor pero son mas lentos y pesan mas.\n"
            "Si el elegido no entra en memoria, la app baja al siguiente sola."
        )
        # _on_model_changed ademas de persistir recarga el motor.
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        row.addWidget(self.model_combo)


        lang_label = QLabel("Idioma")
        lang_label.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        row.addWidget(lang_label)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(LANGUAGES.keys())
        self.lang_combo.setMinimumHeight(34)
        self.lang_combo.setToolTip(
            "Idioma del audio.\n"
            "Auto-detectar puede confundirse en audios cortos (toma español por\n"
            "portugués). Si sabes el idioma, elegilo a mano."
        )
        self.lang_combo.currentTextChanged.connect(
            lambda text: self.settings.setValue(config.SETTING_LANGUAGE, text)
        )
        row.addWidget(self.lang_combo)
        return row_widget

    def _build_editor(self):
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "Arrastra un audio aqui, o usa GRABAR para capturar el audio del sistema, "
            "o SUBIR ARCHIVO para transcribir audios existentes.\n\n"
            "La transcripcion aparece en este area y se guarda sola. Podes editarla "
            "y volver a guardar.\n\n"
            "Tip: click derecho para exportar subtitulos (.srt)."
        )
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._show_text_context_menu)

        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(20, 4, 20, 6)
        box.addWidget(self.text_edit)
        return container

    def _build_progress_row(self):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(20, 0, 20, 4)
        row.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.hide()
        row.addWidget(self.progress_bar, stretch=1)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setStyleSheet(
            _btn_outline(C_RED, C_RED_HI, C_RED_HI, height=24, radius=8, font_size=10)
        )
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setToolTip("Cancela la operacion en curso")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.hide()
        row.addWidget(self.cancel_btn)
        return container

    def _build_footer(self):
        footer = QWidget()
        footer.setStyleSheet(f"border-top: 1px solid {C_BORDER};")
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 10, 20, 12)
        row.setSpacing(6)

        self.play_btn = QPushButton("Audio")
        self.play_btn.setToolTip("Reproduce el audio.mp3 de la transcripcion actual")
        self.play_btn.clicked.connect(self._play_audio)

        self.save_btn = QPushButton("Guardar")
        self.save_btn.setToolTip("Sobreescribe transcripcion.txt con el texto editado")
        self.save_btn.clicked.connect(self._save_edited)

        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setToolTip("Copia la seleccion, o todo el texto si no hay seleccion")
        self.copy_btn.clicked.connect(self._copy)

        self.open_btn = QPushButton("Abrir")
        self.open_btn.setToolTip("Abre la carpeta de la transcripcion actual")
        self.open_btn.clicked.connect(self._open_session)

        for btn in (self.play_btn, self.save_btn, self.copy_btn, self.open_btn):
            btn.setEnabled(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
        self._disable_action_buttons()

        row.addStretch()

        self.lang_chip = QLabel("")
        self.lang_chip.setStyleSheet(S_CHIP_HW)
        self.lang_chip.hide()
        row.addWidget(self.lang_chip)

        history_btn = QPushButton("Historial")
        history_btn.setStyleSheet(S_FOLDER)
        history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        history_btn.setToolTip("Ver transcripciones pasadas")
        history_btn.clicked.connect(self._open_history)
        row.addWidget(history_btn)
        return footer

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_timer)
        self._timer.start(500)

    def attach_single_instance_server(self, server):
        """Guarda el servidor de instancia unica para cerrarlo al salir."""
        self._single_server = server

    def install_hotkey(self, app):
        """Registra el atajo global; si no se puede, deja uno de ventana."""
        self._hotkey = GlobalHotkey(self._on_hotkey)
        if not self._hotkey.install(app):
            self._hotkey = None
            self._hotkey_shortcut = QShortcut(QKeySequence(HOTKEY_TEXT), self)
            self._hotkey_shortcut.activated.connect(self._on_hotkey)
            log.info("Usando atajo local (solo con la ventana enfocada)")

    # ── Bandeja ──
    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            log.info("La bandeja del sistema no esta disponible")
            return

        self.tray = QSystemTrayIcon(self._app_icon, self)
        self.tray.setToolTip(version.APP_NAME)

        menu = QMenu()
        show_action = QAction("Mostrar", self)
        show_action.triggered.connect(self.show_from_tray)
        menu.addAction(show_action)

        record_action = QAction("Grabar / Detener", self)
        record_action.triggered.connect(self._on_hotkey)
        menu.addAction(record_action)

        menu.addSeparator()

        prompt_action = QAction("Vocabulario y estilo...", self)
        prompt_action.triggered.connect(self._edit_initial_prompt)
        menu.addAction(prompt_action)

        updates_action = QAction("Buscar actualizaciones", self)
        updates_action.triggered.connect(self.check_updates_now)
        menu.addAction(updates_action)

        about_action = QAction("Acerca de...", self)
        about_action.triggered.connect(self._show_about)
        menu.addAction(about_action)

        quit_action = QAction("Salir", self)
        quit_action.triggered.connect(self._request_quit)
        menu.addAction(quit_action)

        self._tray_menu = menu  # Qt no toma referencia propia del menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_from_tray()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_from_tray()

    def show_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _show_about(self):
        hw = self._hw
        QMessageBox.information(
            self, f"Acerca de {version.APP_NAME}",
            f"<b>{version.APP_NAME} {version.__version__}</b><br>{version.APP_PUBLISHER}<br><br>"
            f"<b>Motor:</b> {self.whisper.describe()}<br>"
            f"<b>GPU:</b> {hw['gpu_name'] or 'no detectada'}<br>"
            f"<b>RAM:</b> {hw['ram_gb']:.1f} GB<br><br>"
            f"<b>Transcripciones:</b><br>{OUTPUT_DIR}<br><br>"
            f"<b>Registro:</b><br>{paths.log_path()}",
        )

    def _request_quit(self):
        """Salir de verdad. La confirmacion de grabacion la hace closeEvent."""
        self._quit_requested = True
        self.close()

    # ── Dependencias y avisos ──
    def _check_dependencies(self):
        if not FFMPEG_BIN:
            self._set_status("Falta FFmpeg", error=True)
            log.error("FFmpeg no esta disponible")
            QMessageBox.critical(
                self, "FFmpeg no encontrado",
                f"{version.APP_NAME} necesita FFmpeg para procesar audio.\n\n"
                "Si instalaste la app, reinstalala: la carpeta 'bin' debe estar "
                "junto al ejecutable.\n\n"
                "Si corres desde el codigo fuente, instalalo con:\n"
                "    winget install Gyan.FFmpeg",
            )
        else:
            log.info("FFmpeg: %s", FFMPEG_BIN)

        if not self.audio.available:
            log.warning("Grabacion no disponible: %s", self.audio.init_error)
            self.rec_btn.setToolTip(
                "La grabacion no esta disponible en este equipo.\n"
                "Revisa que el servicio de audio de Windows este activo.\n"
                "Podes seguir transcribiendo archivos."
            )
        self._refresh_controls()

    def _maybe_warn_cpu(self):
        """Avisa una unica vez si Whisper va a correr en CPU."""
        if self.whisper.device != "cpu":
            return
        if self.settings.value(config.SETTING_CPU_WARNING_SHOWN, False, type=bool):
            return

        hw = self._hw
        if hw["driver_too_old"]:
            title = "Driver de NVIDIA desactualizado"
            msg = (
                f"Detectamos una {hw['gpu_short']}, pero el driver instalado "
                f"({hw['driver']}) es anterior al que esa GPU necesita.\n\n"
                "Actualizalo desde nvidia.com/drivers o GeForce Experience y volve "
                "a abrir la app para transcribir mucho mas rapido.\n\n"
                "Mientras tanto se usa la CPU."
            )
        elif hw["gpu_name"]:
            title = "GPU NVIDIA detectada, pero sin CUDA"
            msg = (
                f"Detectamos una {hw['gpu_short']}, pero CUDA no esta disponible, "
                "asi que se va a usar la CPU (mucho mas lento).\n\n"
                "Suele resolverse actualizando los drivers de NVIDIA."
            )
        else:
            title = "Sin GPU NVIDIA: modo CPU"
            msg = (
                "No detectamos una GPU NVIDIA en este equipo.\n\n"
                f"{version.APP_NAME} funciona igual, pero transcribe en CPU, que es "
                "bastante mas lento.\n\n"
                f"Se eligio el modelo '{self.whisper.model_name}' para que no demore de mas."
            )
        QMessageBox.warning(self, title, msg)
        self.settings.setValue(config.SETTING_CPU_WARNING_SHOWN, True)

    # ── Actualizaciones ──
    def _check_updates_if_due(self):
        """Comprobacion automatica, como mucho una vez por dia."""
        last = self.settings.value(config.SETTING_LAST_UPDATE_CHECK, "", type=str)
        if last:
            try:
                elapsed = datetime.datetime.now() - datetime.datetime.fromisoformat(last)
                if elapsed.total_seconds() < config.UPDATE_CHECK_INTERVAL_HOURS * 3600:
                    return
            except ValueError:
                pass  # valor corrupto: se vuelve a comprobar
        self._start_update_check(manual=False)

    def check_updates_now(self):
        """Comprobacion manual desde el menu de la bandeja."""
        self._start_update_check(manual=True)

    def _start_update_check(self, manual):
        if self._update_check_thread is not None or self._update_download_thread is not None:
            return
        self._manual_update_check = manual
        if manual:
            self._set_status("Buscando actualizaciones...")
        self._update_check_thread = UpdateCheckThread()
        self._update_check_thread.found.connect(self._on_update_found)
        self._update_check_thread.finished.connect(self._on_update_check_done)
        self._update_check_thread.start()

    def _on_update_check_done(self):
        self._update_check_thread = None

    def _on_update_found(self, info):
        self.settings.setValue(
            config.SETTING_LAST_UPDATE_CHECK,
            datetime.datetime.now().isoformat(timespec="seconds"),
        )
        if info is None:
            if self._manual_update_check:
                self._set_status("Listo")
                QMessageBox.information(
                    self, "Sin novedades",
                    f"Ya tenes la ultima version ({version.__version__}).",
                )
            return

        skipped = self.settings.value(config.SETTING_SKIPPED_VERSION, "", type=str)
        if not self._manual_update_check and info.version == skipped:
            log.info("La version %s fue omitida por el usuario", info.version)
            return
        self._prompt_update(info)

    def _prompt_update(self, info):
        """Ofrece actualizar. No interrumpe una grabacion ni una transcripcion."""
        if self.is_recording or self.is_processing:
            QTimer.singleShot(120_000, lambda: self._prompt_update(info))
            return
        self._set_status("Listo")

        notes = info.notes
        if len(notes) > 600:
            notes = notes[:600].rsplit("\n", 1)[0] + "\n..."

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Hay una version nueva")
        box.setText(
            f"<b>{version.APP_NAME} {info.version}</b> ya esta disponible.<br>"
            f"Tenes instalada la {version.__version__}."
        )
        if notes:
            box.setInformativeText(notes)
        if info.size:
            box.setDetailedText(
                f"Se descargaran {info.size / 1024 / 1024:.0f} MB desde:\n{info.installer_url}"
            )
        update_btn = box.addButton("Actualizar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Ahora no", QMessageBox.ButtonRole.RejectRole)
        skip_btn = box.addButton("Omitir esta version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(update_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is update_btn:
            self._start_update_download(info)
        elif clicked is skip_btn:
            self.settings.setValue(config.SETTING_SKIPPED_VERSION, info.version)
            log.info("El usuario omitio la version %s", info.version)

    def _start_update_download(self, info):
        self._set_status("Descargando actualizacion...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.show()
        self.cancel_btn.show()

        self._update_download_thread = UpdateDownloadThread(info)
        self._update_download_thread.progress.connect(self._on_update_progress)
        self._update_download_thread.done.connect(self._on_update_downloaded)
        self._update_download_thread.finished.connect(self._on_update_download_done)
        self._update_download_thread.start()
        self._refresh_controls()

    def _on_update_progress(self, downloaded, total):
        mb = downloaded / 1024 / 1024
        if total > 0:
            self.progress_bar.setValue(int(downloaded / total * 100))
            self.progress_bar.setFormat(f"{mb:.0f} / {total / 1024 / 1024:.0f} MB")
        else:
            self.progress_bar.setFormat(f"{mb:.0f} MB")

    def _on_update_download_done(self):
        self._update_download_thread = None
        self._refresh_controls()

    def _on_update_downloaded(self, path, error):
        self.progress_bar.hide()
        self.progress_bar.setFormat("%p%")
        self.cancel_btn.hide()

        if error == "cancelado":
            self._set_status("Actualizacion cancelada")
            return
        if error:
            self._set_status("No se pudo actualizar", error=True)
            QMessageBox.warning(
                self, "No se pudo actualizar",
                f"{error}\n\nPodes descargarla a mano desde:\n{version.RELEASES_URL}",
            )
            return

        QMessageBox.information(
            self, "Listo para instalar",
            f"{version.APP_NAME} se va a cerrar para instalar la version nueva.\n\n"
            "Cuando el instalador termine, la app se abre de nuevo.",
        )
        updater.launch_installer(path)
        self._quit_requested = True
        self.close()

    # ── Carga del motor ──
    def _start_engine_load(self):
        """Carga el motor en segundo plano, mostrando el progreso de descarga."""
        model = self.whisper.model_name
        if is_model_downloaded(model):
            self._set_status(f"Cargando {model}...")
        else:
            target_mb = hardware.MODEL_SIZES_MB.get(model, 3000)
            self._set_status(f"Descargando modelo {model} ({target_mb} MB, una sola vez)...")
            self._start_download_monitor(model, target_mb)

        self._load_thread = ModelLoadThread(self.whisper)
        self._load_thread.attempt.connect(self._on_engine_attempt)
        self._load_thread.done.connect(self._on_engine_loaded)
        self._load_thread.start()
        self._refresh_controls()

    def _on_engine_attempt(self, model_name, device):
        """La carga cambio de candidato: puede implicar otra descarga."""
        where = "GPU" if device == "cuda" else "CPU"
        self._set_status(f"Preparando {model_name} en {where}...")
        if not is_model_downloaded(model_name):
            self._start_download_monitor(
                model_name, hardware.MODEL_SIZES_MB.get(model_name, 3000)
            )
        else:
            self._stop_download_monitor()

    def _on_engine_loaded(self, error):
        self._load_thread = None
        self._stop_download_monitor()
        self._refresh_controls()

        if error == "cancelado":
            self._set_status("Carga cancelada")
            return
        if error:
            self._set_status("No se pudo cargar el modelo", error=True)
            QMessageBox.critical(
                self, "No se pudo cargar el modelo",
                "No se pudo iniciar el motor de transcripcion en este equipo.\n\n"
                f"{error}\n\n"
                f"El detalle esta en:\n{paths.log_path()}",
            )
            return

        self._refresh_hw_chip()
        self._set_status("Listo")
        log.info("Motor listo: %s", self.whisper.describe())
        # El motor pudo degradar a un modelo distinto del pedido: limpiamos el
        # cache recien ahora, sabiendo cual quedo realmente en uso.
        try:
            state.cleanup_model_cache(model_cache_dir(self.whisper.model_name))
        except OSError as ex:
            log.warning("No se pudo limpiar el cache de modelos: %s", ex)

    def _on_model_changed(self, text):
        """El usuario eligio otro modelo: se recarga el motor en caliente."""
        self.settings.setValue(config.SETTING_MODEL, text)
        # El selector esta deshabilitado mientras se graba, se procesa o se carga,
        # asi que esto es una red de contencion por si la senal llega igual.
        if self.is_recording or self.is_processing or self._load_thread is not None:
            return
        if self.whisper.set_preferred_model(self._selected_model()):
            self._start_engine_load()

    def _start_download_monitor(self, model_name, target_mb):
        """Sondea el tamano del directorio del modelo para mostrar la descarga."""
        self._download_dir = model_cache_dir(model_name)
        self._download_target_mb = max(1, target_mb)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat(f"0 / {target_mb} MB")
        self.progress_bar.show()

        if self._download_timer is None:
            self._download_timer = QTimer(self)
            self._download_timer.setInterval(800)
            self._download_timer.timeout.connect(self._poll_download)
        self._download_timer.start()

    def _poll_download(self):
        if not self._download_dir or not os.path.isdir(self._download_dir):
            return
        total = 0
        try:
            for root, _, files in os.walk(self._download_dir):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except OSError:
            return
        mb = int(total / 1024 / 1024)
        self.progress_bar.setValue(min(int(mb / self._download_target_mb * 100), 99))
        self.progress_bar.setFormat(f"{mb} / {self._download_target_mb} MB")

    def _stop_download_monitor(self):
        if self._download_timer is not None:
            self._download_timer.stop()
        self._download_dir = None
        if not self.is_processing:
            self.progress_bar.hide()
        self.progress_bar.setFormat("%p%")

    # ── Estado y controles ──
    def _set_status(self, text, error=False):
        self.status_chip.setText(text)
        if error:
            self.status_chip.setStyleSheet(S_CHIP_ERR)
        elif text == "Listo" or text.startswith(("Copiad", "Guardado")):
            self.status_chip.setStyleSheet(S_CHIP_OK)
        elif text.startswith(("Grabando", "Procesando", "Convirtiendo", "Cargando",
                              "Descargando", "Preparando", "Transcribiendo", "Pausado",
                              "Cancelando")):
            self.status_chip.setStyleSheet(S_CHIP_BUSY)
        else:
            self.status_chip.setStyleSheet(S_CHIP)
        self._update_window_title()
        self._update_tray_tooltip()

    def _refresh_controls(self):
        """Unico lugar que decide si los controles principales estan habilitados."""
        # Descargar una actualizacion tambien bloquea: la app se va a cerrar al
        # terminar, asi que no conviene dejar empezar una grabacion.
        busy = (self.is_recording or self.is_processing
                or self._update_download_thread is not None)
        loading = self._load_thread is not None
        can_record = not busy and self.audio.available and bool(FFMPEG_BIN)
        can_upload = not busy and bool(FFMPEG_BIN)

        self.rec_btn.setEnabled(can_record)
        self.rec_btn.setStyleSheet(
            S_REC_OFF if self.is_recording else (S_REC if can_record else S_REC_DISABLED)
        )
        self.upload_btn.setEnabled(can_upload)
        self.upload_btn.setStyleSheet(S_UPLOAD if can_upload else S_BTN_DISABLED)

        self.pause_btn.setEnabled(self.is_recording)
        self.pause_btn.setStyleSheet(
            (S_RESUME if self.is_paused else S_PAUSE) if self.is_recording else S_BTN_DISABLED
        )
        self.pause_btn.setText("REANUDAR" if self.is_paused else "PAUSAR")

        self.stop_btn.setEnabled(self.is_recording)
        self.stop_btn.setStyleSheet(S_STOP if self.is_recording else S_BTN_DISABLED)

        self.lang_combo.setEnabled(not busy)
        self.source_combo.setEnabled(not busy)
        # Cambiar de modelo mientras se carga uno dejaria dos cargas compitiendo por
        # el mismo motor, asi que el selector espera a que termine.
        self.model_combo.setEnabled(not busy and not loading)

    def _disable_action_buttons(self):
        for btn, style in ((self.open_btn, S_OPEN_DISABLED),
                           (self.copy_btn, S_COPY_DISABLED),
                           (self.play_btn, S_OPEN_DISABLED),
                           (self.save_btn, S_OPEN_DISABLED)):
            btn.setEnabled(False)
            btn.setStyleSheet(style)

    def _enable_action_buttons(self):
        self.open_btn.setEnabled(True)
        self.open_btn.setStyleSheet(S_OPEN)
        self.copy_btn.setEnabled(True)
        self.copy_btn.setStyleSheet(S_COPY)
        if self._session_dir and os.path.exists(os.path.join(self._session_dir, "audio.mp3")):
            self.play_btn.setEnabled(True)
            self.play_btn.setStyleSheet(S_OPEN)
        self._refresh_save_btn()

    def _refresh_save_btn(self):
        can_save = bool(self._session_dir) and self._text_dirty and not self.is_processing
        self.save_btn.setEnabled(can_save)
        self.save_btn.setStyleSheet(S_OPEN if can_save else S_OPEN_DISABLED)

    @staticmethod
    def _short_device(name):
        """'Speakers (Realtek(R) Audio) [Loopback]' -> 'Speakers (Realtek(R) Audio)'."""
        if not name:
            return ""
        cut = name.split(" [")[0].strip()
        if len(cut) > 32:
            cut = cut[:32].rsplit(" ", 1)[0] + "..."
        return cut

    @staticmethod
    def _fmt_hms(total_seconds, force_hours=False):
        secs = max(0, int(total_seconds))
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if (h or force_hours) else f"{m:02d}:{s:02d}"

    def _elapsed(self):
        if not self._record_start:
            return datetime.timedelta()
        return datetime.datetime.now() - self._record_start - self._pause_total

    def _update_window_title(self):
        suffix = ""
        if self.is_recording:
            suffix = f"Grabando {self._fmt_hms(self._elapsed().total_seconds())}"
        elif self.is_processing:
            suffix = "Procesando"
        elif self._session_dir:
            try:
                suffix = os.path.relpath(self._session_dir, OUTPUT_DIR).replace(os.sep, "/")
            except ValueError:
                pass
        title = version.APP_NAME + ("*" if self._text_dirty else "")
        if suffix:
            title += f" - {suffix}"
        if self.windowTitle() != title:
            self.setWindowTitle(title)

    def _update_tray_tooltip(self):
        if not self.tray:
            return
        if self.is_recording:
            text = f"{version.APP_NAME} - Grabando {self._fmt_hms(self._elapsed().total_seconds())}"
        elif self.is_processing:
            text = f"{version.APP_NAME} - Procesando"
        else:
            text = f"{version.APP_NAME} - Listo"
        self.tray.setToolTip(text)

    def _toggle_rec_dot(self):
        self._rec_dot_visible = not self._rec_dot_visible
        self.rec_dot.setVisible(self._rec_dot_visible and self.is_recording and not self.is_paused)

    def _update_timer(self):
        if not (self.is_recording and not self.is_paused):
            return
        if self._check_capture_error():
            return
        self.timer_label.setText(self._fmt_hms(self._elapsed().total_seconds(), force_hours=True))
        self._update_window_title()
        self._update_tray_tooltip()

    def _check_capture_error(self):
        """Detiene la grabacion si la captura fallo. True si hubo error.

        `_capture_error_shown` evita una cascada: el QMessageBox corre un bucle de
        eventos anidado, con lo que este mismo timer vuelve a entrar cada 500 ms y
        antes apilaba un dialogo nuevo cada vez.
        """
        if self._capture_error_shown:
            return False
        if self.audio.size_limit_hit:
            title = "Limite de tamano alcanzado"
            body = ("La grabacion supero el limite del formato WAV (~4 GB).\n\n"
                    "Se detuvo sola y se procesa lo capturado hasta ahora.")
        elif self.audio.disk_error:
            title = "Error al guardar el audio"
            body = ("Se detuvo la grabacion porque no se pudo escribir el audio "
                    "(probablemente el disco esta lleno).\n\n"
                    "Se procesa lo capturado hasta ahora. Libera espacio antes de "
                    "volver a grabar.")
        else:
            return False

        self._capture_error_shown = True
        self._set_status("Grabacion detenida por un error", error=True)
        # Primero se ordena el estado y despues se avisa: al abrir el dialogo,
        # is_recording ya es False y el timer no puede reentrar.
        self._on_stop(ask_name=False)
        QMessageBox.warning(self, title, body)
        return True

    # ── Sesiones ──
    def _create_session_dir(self):
        """Crea la carpeta de la sesion, o informa el problema y devuelve None.

        Unico punto de creacion: lo usan tanto la grabacion como la subida. Antes
        estaba duplicado y sin proteger, y una excepcion aca aborta el proceso
        entero porque corre dentro de un slot de Qt.
        """
        try:
            return state.make_session_folder()
        except OSError as ex:
            log.error("No se pudo crear la carpeta de la sesion: %s", ex)
            QMessageBox.critical(
                self, "No se pudo crear la carpeta",
                f"No se pudo crear la carpeta para esta transcripcion.\n\n{ex}\n\n"
                f"Carpeta de destino:\n{OUTPUT_DIR}",
            )
            self._set_status("No se pudo crear la carpeta", error=True)
            return None

    def _cleanup_empty_session_dir(self):
        """Borra la carpeta de la sesion si no quedo nada util adentro."""
        if not self._session_dir or not os.path.isdir(self._session_dir):
            return
        if state.session_has_content(self._session_dir):
            return
        shutil.rmtree(self._session_dir, ignore_errors=True)
        log.info("Eliminada carpeta de sesion vacia: %s", self._session_dir)
        self._session_dir = None

    # ── Grabacion ──
    def _on_hotkey(self):
        if self.is_processing:
            return
        if self.is_recording:
            self._on_stop()
        elif self.audio.available:
            self.show_from_tray()
            self._on_record()

    def _on_record(self):
        if self.is_recording or self.is_processing:
            return
        if not FFMPEG_BIN or not self.audio.available:
            return
        if not self._confirm_discard_unsaved():
            return

        session_dir = self._create_session_dir()
        if not session_dir:
            return

        source = AUDIO_SOURCES.get(self.source_combo.currentText(), SOURCE_LOOPBACK)
        try:
            self.audio.start(os.path.join(session_dir, "_raw.wav"), source=source)
        except Exception as ex:
            log.error("No se pudo iniciar la grabacion: %s", ex)
            shutil.rmtree(session_dir, ignore_errors=True)
            self._set_status(f"{ex}", error=True)
            QMessageBox.warning(self, "No se pudo grabar", str(ex))
            return

        self._session_dir = session_dir
        self.is_recording = True
        self.is_paused = False
        self._capture_error_shown = False
        self._record_start = datetime.datetime.now()
        self._pause_total = datetime.timedelta()
        self._pause_start = None
        self.current_text = ""
        self._segments = []
        self._text_dirty = False

        self.text_edit.blockSignals(True)
        self.text_edit.clear()
        self.text_edit.blockSignals(False)
        self.timer_label.setText("00:00:00")
        self.lang_chip.hide()

        self._disable_action_buttons()
        self._refresh_controls()
        self.rec_dot.show()
        self._rec_dot_visible = True
        self._rec_pulse.start()

        device = self._short_device(self.audio.device_name)
        self._set_status(f"Grabando ({device})" if device else "Grabando...")

    def _on_pause(self):
        if not self.is_recording:
            return
        if not self.is_paused:
            self.is_paused = True
            self._pause_start = datetime.datetime.now()
            self.audio.pause()
            self.rec_dot.hide()
            self._rec_pulse.stop()
            self._set_status("Pausado")
        else:
            self.is_paused = False
            if self._pause_start:
                self._pause_total += datetime.datetime.now() - self._pause_start
                self._pause_start = None
            self.audio.resume()
            self.rec_dot.show()
            self._rec_dot_visible = True
            self._rec_pulse.start()
            self._set_status("Grabando...")
        self._refresh_controls()

    def _on_stop(self, ask_name=True):
        if not self.is_recording or self.is_processing:
            return
        if not self._session_dir:
            # No deberia pasar (_on_record siempre la crea), pero seguir sin
            # carpeta destino haria fallar el hilo de procesamiento.
            log.error("Se pidio detener sin carpeta de sesion activa")
            self.is_recording = False
            self._refresh_controls()
            return

        # Congelar la captura mientras se pide el nombre.
        self.audio.pause()
        self.rec_dot.hide()
        self._rec_pulse.stop()

        self.is_recording = False
        self.is_paused = False
        self._pending_name = self._ask_session_name() if ask_name else None

        self.is_processing = True
        self._refresh_controls()
        self._set_status("Procesando...")
        self.timer_label.setText("")

        thread = ProcessThread(
            self.audio, self.whisper, self._session_dir,
            LANGUAGES.get(self.lang_combo.currentText()),
            self._current_initial_prompt(),
        )
        self._process_thread = thread
        self._wire_thread(thread, self._on_process_thread_done)
        self._start_busy_progress()
        thread.start()

    def _ask_session_name(self):
        """Nombre opcional para la carpeta de esta grabacion."""
        base = os.path.basename(self._session_dir) if self._session_dir else "transcripcion"
        text, ok = QInputDialog.getText(
            self, "Nombre de la grabacion",
            f"Ponele un nombre (opcional).\nSe guarda como:   {base} (tu nombre)",
        )
        return sanitize_folder_name(text) if ok else None

    def _apply_pending_name(self):
        """Renombra la sesion a 'transcripcion-N (nombre)' si el usuario puso uno."""
        name, self._pending_name = self._pending_name, None
        if not name or not self._session_dir or not os.path.isdir(self._session_dir):
            return
        parent = os.path.dirname(self._session_dir)
        new_dir = os.path.join(parent, f"{os.path.basename(self._session_dir)} ({name})")
        if os.path.exists(new_dir):
            log.warning("Ya existe %s; no renombro", new_dir)
            return
        if len(new_dir) > state.MAX_SESSION_DIR_LEN:
            log.warning("El nombre haria la ruta demasiado larga; no renombro")
            return
        try:
            os.rename(self._session_dir, new_dir)
            self._session_dir = new_dir
            log.info("Sesion renombrada: %s", new_dir)
        except OSError as ex:
            log.warning("No se pudo renombrar la sesion: %s", ex)

    # ── Subida de archivos ──
    def _on_upload(self):
        if self.is_recording or self.is_processing:
            return
        if not self._confirm_discard_unsaved():
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar uno o varios archivos de audio", "", AUDIO_FORMATS,
        )
        if file_paths:
            self._start_file_queue(file_paths)

    def _start_file_queue(self, file_paths):
        """Encola archivos y arranca el primero."""
        if self.is_recording or self.is_processing or not FFMPEG_BIN:
            return
        valid = [p for p in file_paths if self._is_audio_path(p)]
        if not valid:
            rejected = ", ".join(sorted({os.path.splitext(p)[1] or "?" for p in file_paths}))
            self._set_status("Formato de audio no soportado", error=True)
            QMessageBox.warning(
                self, "Formato no soportado",
                f"No se puede transcribir ese tipo de archivo ({rejected}).\n\n"
                "Formatos soportados:\n" + ", ".join(AUDIO_EXTS),
            )
            return
        self._file_queue = valid[1:]
        self._queue_total = len(valid)
        self._start_single_file(valid[0], position=1)

    def _start_single_file(self, file_path, position=1):
        session_dir = self._create_session_dir()
        if not session_dir:
            self._file_queue.clear()
            self._queue_total = 0
            self._finish_processing("No se pudo crear la carpeta", error=True)
            return

        self._session_dir = session_dir
        self._pending_name = None   # las subidas no llevan nombre personalizado
        self.is_processing = True
        self.current_text = ""
        self._segments = []
        self._text_dirty = False
        self.lang_chip.hide()

        self.text_edit.blockSignals(True)
        self.text_edit.clear()
        self.text_edit.blockSignals(False)

        self._refresh_controls()
        self._disable_action_buttons()
        prefix = f"({position}/{self._queue_total}) " if self._queue_total > 1 else ""
        self._set_status(f"{prefix}Procesando: {os.path.basename(file_path)}")

        thread = FileTranscribeThread(
            self.whisper, file_path, session_dir,
            LANGUAGES.get(self.lang_combo.currentText()),
            self._current_initial_prompt(),
        )
        self._file_thread = thread
        self._wire_thread(thread, self._on_file_thread_done)
        self._start_busy_progress()
        thread.start()

    def _process_next_in_queue(self):
        if not self._file_queue:
            # No deberia ocurrir (solo se encola con la cola no vacia), pero salir
            # sin cerrar el procesamiento dejaria la interfaz trabada para siempre.
            self._queue_total = 0
            self._finish_processing("Listo", enable_actions=True)
            return
        next_path = self._file_queue.pop(0)
        self._start_single_file(next_path, position=self._queue_total - len(self._file_queue))

    def _schedule_next_in_queue(self):
        """Encadena el proximo archivo dejando respirar la interfaz.

        `is_processing` se mantiene en True durante la pausa: si se bajara, habria
        una ventana en la que el atajo global, la bandeja o un drag & drop podrian
        arrancar otra operacion encima del lote en curso.
        """
        self.cancel_btn.hide()
        self.progress_bar.hide()
        QTimer.singleShot(QUEUE_GAP_MS, self._process_next_in_queue)

    def _wire_thread(self, thread, on_done):
        thread.status.connect(self._set_status)
        thread.progress.connect(self._on_progress)
        thread.finished_ok.connect(self._on_process_ok)
        thread.finished_err.connect(self._on_process_err)
        thread.finished.connect(on_done)

    def _start_busy_progress(self):
        """Barra indeterminada hasta que llegue el primer progreso real."""
        self._transcribe_started_at = None
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.show()
        self.cancel_btn.show()

    # ── Callbacks de procesamiento ──
    def _on_progress(self, pct, partial_text):
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("%p%")
            self.progress_bar.setTextVisible(True)
            self._transcribe_started_at = datetime.datetime.now()
        self.progress_bar.setValue(pct)

        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(partial_text)
        self.text_edit.blockSignals(False)

        eta = ""
        if pct > 5 and self._transcribe_started_at:
            elapsed = (datetime.datetime.now() - self._transcribe_started_at).total_seconds()
            remaining = max(0, int(elapsed * (100 / pct) - elapsed))
            if remaining > 60:
                m, s = divmod(remaining, 60)
                eta = f" (~{m}m {s:02d}s)"
            elif remaining > 0:
                eta = f" (~{remaining}s)"
        self._set_status(f"Transcribiendo... {pct}%{eta}")

    def _on_process_ok(self, result):
        self._segments = result.get("segments", [])
        text = (format_segments_with_timestamps(self._segments)
                if self._segments else result.get("text", ""))
        self.current_text = text

        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(text)
        self.text_edit.blockSignals(False)
        self._text_dirty = False

        self._auto_save_transcription()
        self._apply_pending_name()
        self._show_detected_language(result)

        if self._file_queue:
            log.info("Cola: quedan %d archivos", len(self._file_queue))
            self._schedule_next_in_queue()
            return

        self._queue_total = 0
        self._finish_processing("Listo", enable_actions=True)
        if self.tray and not self.isActiveWindow():
            self.tray.showMessage(
                "Transcripcion lista",
                text[:120] + ("..." if len(text) > 120 else ""),
                QSystemTrayIcon.MessageIcon.Information, 4000,
            )

    def _on_process_err(self, msg):
        log.warning("Procesamiento: %s", msg)
        self._cleanup_empty_session_dir()

        if msg == "Cancelado" and self._file_queue:
            # Cancelar es una decision sobre el lote entero, no sobre un archivo.
            log.info("Cola cancelada (%d archivos descartados)", len(self._file_queue))
            self._file_queue.clear()
            self._queue_total = 0
        elif self._file_queue:
            # Un error puntual no debe tirar abajo el resto del lote.
            self._schedule_next_in_queue()
            return

        self._queue_total = 0
        self._finish_processing(msg, error=True)

    def _finish_processing(self, status, enable_actions=False, error=False):
        self.is_processing = False
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self._set_status(status, error=error)
        self._refresh_controls()
        if enable_actions:
            self._enable_action_buttons()

    def _on_process_thread_done(self):
        self._process_thread = None

    def _on_file_thread_done(self):
        self._file_thread = None

    def _on_cancel(self):
        """Aborta la operacion en curso (cooperativo)."""
        cancelled = False
        for thread in (self._process_thread, self._file_thread, self._load_thread,
                       self._update_download_thread):
            if thread is not None and thread.isRunning():
                thread.cancel()
                cancelled = True
        if cancelled:
            log.info("Cancelacion solicitada")
            self._set_status("Cancelando...")

    def _show_detected_language(self, result):
        """Muestra 'Detectado: es (98%)' solo si se uso auto-deteccion."""
        if self.lang_combo.currentText() != "Auto-detectar":
            self.lang_chip.hide()
            return
        lang = result.get("language", "")
        if not lang:
            self.lang_chip.hide()
            return
        self.lang_chip.setText(f"Detectado: {lang} ({int(result.get('language_probability', 0) * 100)}%)")
        self.lang_chip.show()

    # ── Texto y archivos de salida ──
    def _auto_save_transcription(self):
        if not self.current_text or not self._session_dir:
            return
        try:
            path = os.path.join(self._session_dir, "transcripcion.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.current_text)
            log.info("Guardado: %s", path)
        except OSError as ex:
            log.warning("No se pudo guardar la transcripcion: %s", ex)
            self._set_status("No se pudo guardar el texto", error=True)

    def _save_edited(self):
        if not self._session_dir:
            return
        edited = self.text_edit.toPlainText()
        try:
            path = os.path.join(self._session_dir, "transcripcion.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(edited)
        except OSError as ex:
            log.error("Error guardando: %s", ex)
            self._set_status(f"Error guardando: {ex}", error=True)
            return
        self.current_text = edited
        self._text_dirty = False
        self._set_status("Guardado")
        self._refresh_save_btn()

    def _export_srt(self):
        if not self._session_dir:
            return
        if not self._segments:
            self._set_status("SRT no disponible (sesion cargada sin segmentos)", error=True)
            return
        try:
            path = os.path.join(self._session_dir, "transcripcion.srt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(build_srt(self._segments))
        except OSError as ex:
            log.error("Error exportando SRT: %s", ex)
            self._set_status(f"Error: {ex}", error=True)
            return
        log.info("Guardado SRT: %s", path)
        self._set_status("transcripcion.srt exportado")

    def _show_text_context_menu(self, pos):
        menu = self.text_edit.createStandardContextMenu()
        menu.addSeparator()
        action = menu.addAction("Exportar como subtitulos (.srt)")
        action.setEnabled(bool(self._segments) and bool(self._session_dir))
        action.triggered.connect(self._export_srt)
        menu.exec(self.text_edit.mapToGlobal(pos))

    def _on_text_changed(self):
        if not self._session_dir or self.is_processing:
            return
        self._text_dirty = self.text_edit.toPlainText() != self.current_text
        self._refresh_save_btn()
        self._update_window_title()

    def _confirm_discard_unsaved(self):
        """True si no hay ediciones pendientes o el usuario acepta descartarlas."""
        if not self._text_dirty:
            return True
        reply = QMessageBox.question(
            self, "Cambios sin guardar",
            "Tenes ediciones sin guardar en la transcripcion actual.\n\n"
            "Si continuas, los cambios se pierden.\n\n"
            "Elegi Cancelar y despues Guardar si los queres conservar.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    def _copy(self):
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            # selectedText() usa U+2029 (parrafo) y U+2028 (linea) como saltos.
            text = cursor.selectedText().replace(" ", "\n").replace(" ", "\n")
            label = f"Copiada la seleccion ({len(text)} caracteres)"
        else:
            text = self.text_edit.toPlainText() or self.current_text
            label = "Copiado al portapapeles"
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._set_status(label)

    def _play_audio(self):
        if not self._session_dir:
            return
        mp3 = os.path.join(self._session_dir, "audio.mp3")
        if os.path.exists(mp3):
            open_in_explorer(mp3)
        else:
            self._set_status("No hay audio.mp3 en esta sesion", error=True)

    def _open_session(self):
        """Abre la carpeta de la transcripcion actual.

        Se abre la carpeta directamente y no `explorer /select`, que falla cuando el
        nombre tiene espacios o parentesis (p.ej. 'transcripcion-3 (prueba)').
        """
        target = (self._session_dir
                  if self._session_dir and os.path.isdir(self._session_dir)
                  else OUTPUT_DIR)
        open_in_explorer(target)

    # ── Historial ──
    def _open_history(self):
        if self.is_processing or self.is_recording:
            self._set_status("Espera a que termine la operacion actual", error=True)
            return
        if not self._confirm_discard_unsaved():
            return
        dlg = HistoryDialog(OUTPUT_DIR, parent=self)
        dlg.setWindowIcon(self._app_icon)
        dlg.setStyleSheet(STYLE)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_dir:
            self._load_session(dlg.selected_dir)

    def _load_session(self, session_dir):
        """Carga una transcripcion previa en el editor."""
        txt_path = os.path.join(session_dir, "transcripcion.txt")
        try:
            with open(txt_path, encoding="utf-8") as f:
                text = f.read()
        except OSError as ex:
            log.error("No se pudo leer %s: %s", txt_path, ex)
            self._set_status("No se pudo abrir esa transcripcion", error=True)
            return

        self._session_dir = session_dir
        self.current_text = text
        # Los segmentos con timestamps no se persisten, asi que una sesion cargada
        # no puede re-exportar el .srt (el que ya exista sigue estando).
        self._segments = []
        self._text_dirty = False
        self.lang_chip.hide()

        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(text)
        self.text_edit.blockSignals(False)

        self._enable_action_buttons()
        self._set_status(f"Cargado: {os.path.relpath(session_dir, OUTPUT_DIR)}")
        log.info("Sesion cargada: %s", session_dir)

    # ── Arrastrar y soltar ──
    @staticmethod
    def _is_audio_path(path):
        return bool(path) and path.lower().endswith(AUDIO_EXTS)

    def dragEnterEvent(self, event):
        accept = False
        if not (self.is_recording or self.is_processing) and FFMPEG_BIN:
            urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
            accept = any(u.isLocalFile() and self._is_audio_path(u.toLocalFile()) for u in urls)
        self._set_drop_target(accept)
        if accept:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_target(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_target(False)
        dropped = [u.toLocalFile() for u in event.mimeData().urls()
                   if u.isLocalFile() and self._is_audio_path(u.toLocalFile())]
        if not dropped:
            event.ignore()
            return
        event.acceptProposedAction()
        self.show_from_tray()
        if self._confirm_discard_unsaved():
            self._start_file_queue(dropped)

    def _set_drop_target(self, active):
        self.text_edit.setProperty("droptarget", "true" if active else "false")
        self.text_edit.style().unpolish(self.text_edit)
        self.text_edit.style().polish(self.text_edit)

    # ── Cierre ──
    def closeEvent(self, event):
        if self.is_recording and not self._confirm_discard_recording():
            self._quit_requested = False
            event.ignore()
            return

        # Cerrar la ventana con la bandeja activa solo la esconde.
        if self.tray is not None and not self._quit_requested:
            self.hide()
            if not self.settings.value(config.SETTING_TRAY_MESSAGE_SHOWN, False, type=bool):
                self.tray.showMessage(
                    version.APP_NAME,
                    "Sigo corriendo en la bandeja. Click derecho > Salir para cerrar.",
                    QSystemTrayIcon.MessageIcon.Information, 3500,
                )
                self.settings.setValue(config.SETTING_TRAY_MESSAGE_SHOWN, True)
            event.ignore()
            return

        self._shutdown()
        event.accept()
        # QuitOnLastWindowClosed esta en False (la app vive en la bandeja), asi que
        # sin este quit quedaria un proceso sin ventana ni icono.
        QApplication.quit()

    def _confirm_discard_recording(self):
        """Pide confirmacion para descartar la grabacion en curso."""
        reply = QMessageBox.question(
            self, "Grabacion en curso",
            "Hay una grabacion en curso.\n\n"
            "Si cerras ahora se descarta y no se transcribe.\n\n"
            "¿Cerrar igual?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        self.is_recording = False
        self._rec_pulse.stop()
        # discard() borra el WAV parcial: puede pesar cientos de MB.
        self.audio.discard()
        self._cleanup_empty_session_dir()
        # Confirmar el descarte implica cerrar de verdad, no minimizar.
        self._quit_requested = True
        return True

    def _shutdown(self):
        """Detiene todo de forma ordenada. Se llama una sola vez al cerrar."""
        self._timer.stop()
        self._rec_pulse.stop()
        if self._download_timer is not None:
            self._download_timer.stop()

        threads = (self._process_thread, self._file_thread, self._load_thread,
                   self._update_check_thread, self._update_download_thread)

        # 1) Pedir el aborto cooperativo y desconectar las senales: una senal en
        #    vuelo que llegue a un widget ya destruido revienta con
        #    "wrapped C/C++ object has been deleted".
        for thread in threads:
            if thread is None:
                continue
            try:
                thread.disconnect()
            except (RuntimeError, TypeError):
                pass
            # UpdateCheckThread no es cancelable: es una sola peticion con timeout
            # corto, asi que termina sola.
            if thread.isRunning() and hasattr(thread, "cancel"):
                thread.cancel()

        # 2) Esperar. Si un hilo no responde (descarga de varios GB sin puntos de
        #    cancelacion), se lo termina: es preferible a dejar el proceso vivo sin
        #    ventana ni icono en la bandeja.
        for thread in threads:
            if thread is None or not thread.isRunning():
                continue
            if not thread.wait(THREAD_STOP_TIMEOUT_MS):
                log.warning("Un hilo no termino a tiempo; se fuerza su cierre")
                thread.terminate()
                thread.wait(1000)

        self.audio.cleanup()
        self._save_settings()

        if self._hotkey is not None:
            self._hotkey.remove(QApplication.instance())
        if self._single_server is not None:
            self._single_server.close()
        if self.tray:
            self.tray.hide()
        log.info("Cierre ordenado completo")


# ── Punto de entrada ──
def _splash_message(splash, app, text):
    splash.showMessage(
        text,
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor(C_TEXT_DIM),
    )
    app.processEvents()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(version.APP_ORG)
    app.setApplicationName(version.APP_NAME)
    app.setApplicationVersion(version.__version__)
    # La app vive en la bandeja: cerrar la ventana no debe matar el proceso.
    app.setQuitOnLastWindowClosed(False)

    if not try_acquire_single_instance():
        log.info("Ya hay otra instancia corriendo; salgo")
        return 0

    log.info("%s %s iniciando", version.APP_NAME, version.__version__)

    icon = make_app_icon()
    app.setWindowIcon(icon)

    splash = QSplashScreen(make_splash_pixmap(), Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    _splash_message(splash, app, "Iniciando...")

    _splash_message(splash, app, "Organizando archivos...")
    try:
        state.migrate_old_layout()
    except OSError as ex:
        log.warning("La migracion fallo (no es critico): %s", ex, exc_info=True)

    _splash_message(splash, app, "Cargando interfaz...")
    window = TranscriberApp(app_icon=icon)
    window.attach_single_instance_server(SingleInstanceServer(window))
    window.install_hotkey(app)

    _splash_message(splash, app, "Listo. El modelo se carga en segundo plano.")
    window.show()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
