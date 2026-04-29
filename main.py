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

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QComboBox, QLabel, QProgressBar, QFileDialog,
    QSystemTrayIcon, QMenu, QSplashScreen, QMessageBox,
    QDialog, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import (
    QShortcut, QKeySequence, QPixmap, QPainter, QColor, QFont, QIcon, QAction,
)
from PyQt6.QtNetwork import QLocalSocket, QLocalServer

# paths.py se importa antes que faster_whisper para fijar HF_HOME al directorio portable
import paths
import state

# Pre-migrar log/settings ANTES de abrir el FileHandler (file lock issue en Windows)
state.pre_migrate_log_settings()


# ── Constantes ──
APP_ORG = "CrisMed"
APP_NAME = "Transcriber"
APP_USER_MODEL_ID = "CrisMed.Transcriber.1"
# Per-user para evitar colisiones en sesiones de Remote Desktop / multi-usuario
try:
    _USER_TAG = getpass.getuser() or "default"
except Exception:
    _USER_TAG = "default"
SINGLE_INSTANCE_KEY = f"CrisMed.Transcriber.SingleInstance.v1.{_USER_TAG}"

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".wma", ".aac", ".opus", ".webm")

LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
LOG_BACKUP_COUNT = 3
SOCKET_TIMEOUT_MS = 800

# Limites de Windows MAX_PATH para audio.mp3 / transcripcion.txt
MAX_SESSION_DIR_LEN = 240


def _build_log_handlers():
    """File handler con rotacion + StreamHandler si hay consola.

    Si la ubicacion preferida es read-only, fallback a %TEMP%.
    """
    handlers = []
    candidates = [paths.log_path(), os.path.join(tempfile.gettempdir(), "Transcriber", "transcriber.log")]
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            h = logging.handlers.RotatingFileHandler(
                path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8",
            )
            handlers.append(h)
            break
        except Exception:
            continue
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    return handlers


_handlers = _build_log_handlers()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
log = logging.getLogger(__name__)


def _excepthook(exc_type, exc_value, exc_tb):
    log.critical("Excepcion no capturada:\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


sys.excepthook = _excepthook

# Identidad para la barra de tareas (Windows): que NO use el icono de Python
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception as ex:
        log.warning("No se pudo setear AppUserModelID: %s", ex)

# Agregar DLLs de NVIDIA al PATH (para CUDA en dev mode)
for _base in [os.path.dirname(sys.executable), os.path.join(os.path.dirname(__file__), "venv", "Scripts")]:
    _sp = os.path.join(_base, "..", "Lib", "site-packages")
    for _d in glob.glob(os.path.join(_sp, "nvidia", "*", "bin")):
        os.add_dll_directory(os.path.abspath(_d))
        os.environ["PATH"] = os.path.abspath(_d) + os.pathsep + os.environ.get("PATH", "")

from config import OUTPUT_DIR, LANGUAGES, FFMPEG_BIN, WHISPER_DEVICE, AUDIO_FORMATS, WHISPER_MODEL
from audio_capture import AudioCapture
from transcriber import Transcriber
from utils import NO_WINDOW, resource_path
from transcriber import build_srt
from audio_capture import SOURCE_LOOPBACK, SOURCE_MIC
import hardware

# Tamanos aproximados (MB) de cada modelo Whisper, para mostrar progreso de descarga.
MODEL_SIZES_MB = {
    "tiny": 75,
    "base": 145,
    "small": 480,
    "medium": 1500,
    "large-v3": 3000,
}

AUDIO_SOURCES = {
    "Audio del sistema": SOURCE_LOOPBACK,
    "Microfono": SOURCE_MIC,
}


# ── Paleta (GitHub Dark inspired) ──
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

# ── Estilos globales (hovers, focus, menus, scrollbars) ──
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
    border-radius: 8px; padding: 6px 12px; font-size: 12px; min-width: 130px;
}}
QComboBox:hover {{ border-color: {C_ACCENT}; }}
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
    """Genera QSS para un boton con hover."""
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


# Estilos por boton (height + colores). Hover incluido.
S_REC = _btn_style(C_RED, C_RED_HI, height=44, radius=22, font_size=13)
S_REC_OFF = _btn_style(C_GRAY, C_GRAY_HI, height=44, radius=22, font_size=13)
S_REC_DISABLED = _btn_disabled(height=44, radius=22, font_size=13)
S_PAUSE = _btn_style(C_AMBER, C_AMBER_HI)
S_RESUME = _btn_style(C_GREEN, C_GREEN_HI)
S_STOP = _btn_style(C_RED, C_RED_HI)
S_UPLOAD = _btn_style(C_BLUE, C_BLUE_HI)
S_BTN_DISABLED = _btn_disabled()

# Pequenos (footer)
S_OPEN = _btn_style(C_GREEN, C_GREEN_HI, height=30, radius=10, font_size=11)
S_COPY = _btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_DIM, height=30, radius=10, font_size=11)
S_FOLDER = _btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_MUTED, height=30, radius=10, font_size=11)
S_OPEN_DISABLED = _btn_disabled(height=30, radius=10, font_size=11)
S_COPY_DISABLED = _btn_disabled(height=30, radius=10, font_size=11)

# Chips (status, hardware)
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
                 f"border-radius: 10px; padding: 3px 10px; font-size: 10px; color: {C_BLUE_HI}; font-weight: 600;")


def make_app_icon():
    """Carga icon.ico si existe; si no, genera uno en runtime."""
    ico_path = resource_path("icon.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)

    sizes = [16, 32, 48, 64, 128, 256]
    icon = QIcon()
    for s in sizes:
        pm = QPixmap(s, s)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#da3633"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, s - 2, s - 2)
        p.setPen(QColor("white"))
        f = QFont("Arial", int(s * 0.45), QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "T")
        p.end()
        icon.addPixmap(pm)
    return icon


def make_splash_pixmap():
    """Pixmap del splash screen (380x220, dark themed)."""
    pm = QPixmap(380, 220)
    pm.fill(QColor("#0d1117"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    p.setPen(QColor("#21262d"))
    p.drawRoundedRect(0, 0, 379, 219, 12, 12)

    cx, cy, r = 190, 80, 32
    p.setBrush(QColor("#da3633"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
    p.setPen(QColor("white"))
    p.setFont(QFont("Arial", 28, QFont.Weight.Bold))
    p.drawText(cx - r, cy - r, r * 2, r * 2, Qt.AlignmentFlag.AlignCenter, "T")

    p.setPen(QColor("#ff6b6b"))
    p.setFont(QFont("Arial", 16, QFont.Weight.Bold))
    p.drawText(pm.rect().adjusted(0, 130, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "TRANSCRIBER")

    p.end()
    return pm


# ── Threads de procesamiento ──
class _BaseTranscribeThread(QThread):
    """Base compartida para grabacion y subida de archivo.

    Subclases implementan `_get_input_path()` para producir el audio a procesar.
    """
    status = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(dict)   # {text, segments, language, language_probability, cancelled}
    finished_err = pyqtSignal(str)

    def __init__(self, whisper, whisper_loaded, session_dir, lang):
        super().__init__()
        self.whisper = whisper
        self.whisper_loaded = whisper_loaded
        self.session_dir = session_dir
        self.lang = lang
        self.model_loaded = False
        self._active_procs = []
        self._cancelled = False

    def cancel(self):
        """Solicita aborto cooperativo (mata FFmpeg + corta el loop de Whisper)."""
        self._cancelled = True
        self.kill_subprocesses()

    def _get_input_path(self):
        raise NotImplementedError

    def _ffmpeg_input_args(self, input_path):
        return []

    def _cleanup_input(self, input_path):
        pass

    def kill_subprocesses(self):
        for p in self._active_procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        self._active_procs.clear()

    def run(self):
        try:
            input_path = self._get_input_path()
            if not input_path:
                self.finished_err.emit("Sin audio detectado")
                return

            mp3 = os.path.join(self.session_dir, "audio.mp3")
            mono = os.path.join(self.session_dir, "_mono.wav")
            extra = self._ffmpeg_input_args(input_path)

            self.status.emit("Convirtiendo audio...")
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
            for p in self._active_procs:
                p.wait()
            self._active_procs.clear()

            if self._cancelled:
                self.finished_err.emit("Cancelado")
                return

            if not os.path.exists(mono):
                self.finished_err.emit("Error: FFmpeg no pudo generar el audio para transcribir")
                return
            if not os.path.exists(mp3):
                log.warning("FFmpeg no genero %s (la transcripcion sigue, pero no quedara audio.mp3)", mp3)

            self._cleanup_input(input_path)

            if not self.whisper_loaded:
                self.status.emit("Cargando modelo Whisper...")
                self.whisper.load_model()
                self.model_loaded = True

            self.status.emit("Transcribiendo...")
            result = self.whisper.transcribe(
                mono, language=self.lang,
                on_progress=lambda pct, partial: self.progress.emit(pct, partial),
                should_cancel=lambda: self._cancelled,
            )
            result["text"] = result["text"].strip()

            try:
                os.unlink(mono)
            except OSError:
                pass

            if result.get("cancelled"):
                self.finished_err.emit("Cancelado")
            else:
                if not result["text"]:
                    result["text"] = "No se detecto voz en el audio."
                self.finished_ok.emit(result)

        except Exception as ex:
            log.error("Error en procesamiento", exc_info=True)
            self.finished_err.emit(f"Error: {ex}")
        finally:
            self.kill_subprocesses()


class ProcessThread(_BaseTranscribeThread):
    """Procesa una grabacion (loopback) recien terminada."""

    def __init__(self, audio, whisper, whisper_loaded, session_dir, lang):
        super().__init__(whisper, whisper_loaded, session_dir, lang)
        self.audio = audio

    def _get_input_path(self):
        return self.audio.stop_raw()

    def _cleanup_input(self, input_path):
        try:
            os.unlink(input_path)
        except OSError as ex:
            log.warning("No se pudo eliminar WAV: %s", ex)


class FileTranscribeThread(_BaseTranscribeThread):
    """Transcribe un archivo de audio subido o arrastrado."""

    def __init__(self, whisper, whisper_loaded, file_path, session_dir, lang):
        super().__init__(whisper, whisper_loaded, session_dir, lang)
        self.file_path = file_path

    def _get_input_path(self):
        return self.file_path

    def _ffmpeg_input_args(self, input_path):
        # Archivos pueden tener video; -vn descarta el track
        return ["-vn"]


# ── Single-instance lock (QLocalServer/Socket) ──
def try_acquire_single_instance():
    """Si ya hay otra instancia, le pide que muestre su ventana y devuelve False.

    True = somos la primera (o unica) instancia; podemos seguir.
    False = otra instancia ya corre; debemos salir.
    """
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(800):
        try:
            sock.write(b"SHOW")
            sock.flush()
            sock.waitForBytesWritten(500)
        finally:
            sock.disconnectFromServer()
        return False
    return True


class SingleInstanceServer:
    """Acepta conexiones de futuras instancias y trae la ventana al frente."""

    def __init__(self, window):
        self.window = window
        self.server = QLocalServer()
        # Limpiar socket leftover de un crash anterior
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        if not self.server.listen(SINGLE_INSTANCE_KEY):
            # Race: alguien gano la carrera entre nuestro try_acquire y este listen.
            # Reintentamos try_acquire y si ahora SI hay otra, salimos limpiamente.
            log.warning("listen() fallo: %s; reintentando deteccion", self.server.errorString())
            if not try_acquire_single_instance():
                log.info("Confirmado: otra instancia gano la carrera, saliendo")
                QApplication.quit()
                sys.exit(0)
            # Si aun asi no hay otra, dejamos al daemon sin escuchar (modo degradado).
            return
        self.server.newConnection.connect(self._on_new)

    def _on_new(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        try:
            if sock.waitForReadyRead(500):
                msg = bytes(sock.readAll().data())
                if msg == b"SHOW":
                    log.info("Otra instancia pidio mostrar la ventana")
                    self.window.showNormal()
                    self.window.activateWindow()
                    self.window.raise_()
        finally:
            sock.disconnectFromServer()


_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRANSCRIPCION_DIR_RE = re.compile(r"^transcripcion-(\d+)$")


class HistoryDialog(QDialog):
    """Dialog que lista transcripciones pasadas (mas recientes arriba) y permite recargar una."""

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historial de transcripciones")
        self.setMinimumSize(580, 420)
        self.output_dir = output_dir
        self.selected_dir = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        info = QLabel("Doble click para cargar una transcripcion en la ventana principal:")
        info.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px;")
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            f"QListWidget {{ background-color: {C_SURFACE}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 8px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 8px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background-color: #264f78; }}"
            f"QListWidget::item:hover {{ background-color: {C_BORDER_HI}; }}"
        )
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        load_btn = QPushButton("Cargar")
        load_btn.setStyleSheet(_btn_style(C_GREEN, C_GREEN_HI, height=30, radius=8, font_size=11))
        load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.clicked.connect(self._on_load)
        bottom.addWidget(load_btn)
        close_btn = QPushButton("Cerrar")
        close_btn.setStyleSheet(_btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_DIM, height=30, radius=8, font_size=11))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self._populate()

    def _populate(self):
        if not os.path.isdir(self.output_dir):
            return
        date_dirs = sorted(
            [d for d in os.listdir(self.output_dir)
             if _DATE_DIR_RE.match(d) and os.path.isdir(os.path.join(self.output_dir, d))],
            reverse=True,
        )
        for date_dir in date_dirs:
            date_path = os.path.join(self.output_dir, date_dir)
            try:
                sessions = [s for s in os.listdir(date_path)
                            if _TRANSCRIPCION_DIR_RE.match(s)
                            and os.path.isdir(os.path.join(date_path, s))]
            except OSError:
                continue
            sessions.sort(key=lambda x: int(_TRANSCRIPCION_DIR_RE.match(x).group(1)), reverse=True)
            for s in sessions:
                full = os.path.join(date_path, s)
                preview = self._load_preview(full)
                label = f"{date_dir}  -  {s}"
                if preview:
                    label += f"\n   {preview}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, full)
                self.list_widget.addItem(item)

    @staticmethod
    def _load_preview(session_dir, max_chars=120):
        txt = os.path.join(session_dir, "transcripcion.txt")
        if not os.path.isfile(txt):
            return ""
        try:
            with open(txt, encoding="utf-8") as f:
                content = f.read(max_chars + 20).replace("\n", " ").strip()
            if len(content) > max_chars:
                content = content[:max_chars] + "..."
            return content
        except Exception:
            return ""

    def _on_double_click(self, item):
        self.selected_dir = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_load(self):
        item = self.list_widget.currentItem()
        if item:
            self.selected_dir = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


class TranscriberApp(QMainWindow):
    def __init__(self, app_icon=None):
        super().__init__()
        log.info("Hardware: %s", hardware.hardware_summary())

        self.audio = AudioCapture()
        self.whisper = Transcriber(model_name=WHISPER_MODEL)
        self.is_recording = False
        self.is_paused = False
        self.is_processing = False
        self._whisper_loaded = False
        self._preload_error = None
        self._session_dir = None
        self._record_start = None
        self._pause_total = datetime.timedelta()
        self._pause_start = None
        self.current_text = ""
        self._segments = []
        self._text_dirty = False
        self._process_thread = None
        self._file_thread = None
        self._preload_thread = None
        self._download_timer = None
        self._file_queue = []
        self._queue_total = 0
        self._allow_quit = False
        self._app_icon = app_icon or make_app_icon()

        self.settings = QSettings(paths.settings_ini_path(), QSettings.Format.IniFormat)

        self._init_ui()
        self._restore_settings()
        self._init_timer()
        self._init_hotkey()
        self._init_tray()
        self.setAcceptDrops(True)
        self._check_deps()
        self._preload_whisper()

    # ── Persistencia ──
    def _restore_settings(self):
        for key, combo in (("language", self.lang_combo), ("source", self.source_combo)):
            val = self.settings.value(key, type=str)
            if val:
                idx = combo.findText(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        geom = self.settings.value("geometry")
        if geom is not None:
            try:
                self.restoreGeometry(geom)
            except Exception:
                pass

    def _save_settings(self):
        self.settings.setValue("language", self.lang_combo.currentText())
        self.settings.setValue("source", self.source_combo.currentText())
        self.settings.setValue("geometry", self.saveGeometry())

    def _on_lang_changed(self, text):
        self.settings.setValue("language", text)

    def _on_source_changed(self, text):
        self.settings.setValue("source", text)

    # ── UI ──
    def _init_ui(self):
        self.setWindowTitle("Transcriber")
        self.resize(580, 500)
        self.setMinimumSize(440, 360)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(self._app_icon)

        central = QWidget()
        central.setStyleSheet(f"background-color: {C_BG};")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setStyleSheet(f"background-color: {C_SURFACE}; border-bottom: 1px solid {C_BORDER};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 12, 20, 12)
        h_layout.setSpacing(10)

        # Logo + titulo
        logo_label = QLabel()
        logo_pm = QPixmap(22, 22)
        logo_pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(logo_pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(C_RED))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 22, 22)
        p.setPen(QColor("white"))
        p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        p.drawText(logo_pm.rect(), Qt.AlignmentFlag.AlignCenter, "T")
        p.end()
        logo_label.setPixmap(logo_pm)
        h_layout.addWidget(logo_label)

        title = QLabel("TRANSCRIBER")
        title.setStyleSheet(f"color: {C_TEXT}; font-size: 14px; font-weight: bold; letter-spacing: 2px;")
        h_layout.addWidget(title)

        h_layout.addStretch()

        # Indicador de grabacion (dot + timer)
        self.rec_dot = QLabel("●")
        self.rec_dot.setStyleSheet(f"color: {C_RED}; font-size: 18px;")
        self.rec_dot.hide()
        h_layout.addWidget(self.rec_dot)

        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet(
            f"color: {C_RED_HI}; font-size: 15px; font-weight: bold; "
            f"font-family: 'Consolas', monospace;"
        )
        h_layout.addWidget(self.timer_label)

        # Status chip (color-coded)
        self.status_chip = QLabel("Listo")
        self.status_chip.setStyleSheet(S_CHIP_OK)
        h_layout.addWidget(self.status_chip)

        layout.addWidget(header)

        # ── Row 1: GRABAR (primario, grande) + Pausar/Detener (secundarios) ──
        row1 = QWidget()
        r1 = QHBoxLayout(row1)
        r1.setContentsMargins(20, 14, 20, 6)
        r1.setSpacing(8)

        self.rec_btn = QPushButton("GRABAR")
        self.rec_btn.setStyleSheet(S_REC)
        self.rec_btn.setMinimumWidth(140)
        self.rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rec_btn.setToolTip("Grabar audio del sistema (loopback). Atajo: Ctrl+Shift+R")
        self.rec_btn.clicked.connect(self._on_record)
        if not self.audio.available:
            self.rec_btn.setEnabled(False)
            self.rec_btn.setStyleSheet(S_REC_DISABLED)
            self.rec_btn.setToolTip("Grabacion loopback solo disponible en Windows")
        r1.addWidget(self.rec_btn)

        self.pause_btn = QPushButton("PAUSAR")
        self.pause_btn.setStyleSheet(S_BTN_DISABLED)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self._on_pause)
        r1.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("DETENER")
        self.stop_btn.setStyleSheet(S_BTN_DISABLED)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self._on_stop)
        r1.addWidget(self.stop_btn)

        r1.addStretch()

        # Fuente de audio: sistema (loopback) o microfono
        src_label = QLabel("Fuente")
        src_label.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        r1.addWidget(src_label)

        self.source_combo = QComboBox()
        self.source_combo.addItems(AUDIO_SOURCES.keys())
        self.source_combo.setMinimumHeight(30)
        self.source_combo.setMinimumWidth(140)
        self.source_combo.setToolTip(
            "Audio del sistema: lo que escuchas por parlantes/auriculares (loopback).\n"
            "Microfono: tu voz para dictado."
        )
        self.source_combo.currentTextChanged.connect(self._on_source_changed)
        r1.addWidget(self.source_combo)

        layout.addWidget(row1)

        # ── Row 2: SUBIR ARCHIVO + Idioma ──
        row2 = QWidget()
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(20, 0, 20, 8)
        r2.setSpacing(8)

        self.upload_btn = QPushButton("SUBIR ARCHIVO")
        self.upload_btn.setStyleSheet(S_UPLOAD)
        self.upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_btn.setToolTip("Transcribir un archivo de audio o arrastralo a la ventana")
        self.upload_btn.clicked.connect(self._on_upload)
        r2.addWidget(self.upload_btn)

        r2.addStretch()

        lang_label = QLabel("Idioma")
        lang_label.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        r2.addWidget(lang_label)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(LANGUAGES.keys())
        self.lang_combo.setMinimumHeight(34)
        self.lang_combo.currentTextChanged.connect(self._on_lang_changed)
        r2.addWidget(self.lang_combo)

        layout.addWidget(row2)

        # ── Text area (editable) ──
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(False)
        self.text_edit.setPlaceholderText(
            "Arrastra un audio aqui, o usa GRABAR para capturar el audio del sistema, "
            "o SUBIR ARCHIVO para transcribir un audio existente.\n\n"
            "La transcripcion aparecera en este area y se guarda automaticamente. "
            "Podes editarla y volver a guardar."
        )
        self.text_edit.textChanged.connect(self._on_text_changed)
        te_container = QWidget()
        te_layout = QVBoxLayout(te_container)
        te_layout.setContentsMargins(20, 4, 20, 6)
        te_layout.addWidget(self.text_edit)
        layout.addWidget(te_container, stretch=1)

        # ── Progress bar + Cancelar ──
        prog_container = QWidget()
        prog_layout = QHBoxLayout(prog_container)
        prog_layout.setContentsMargins(20, 0, 20, 4)
        prog_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.hide()
        prog_layout.addWidget(self.progress_bar, stretch=1)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setStyleSheet(_btn_outline(C_RED, C_RED_HI, C_RED_HI, height=24, radius=8, font_size=10))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setToolTip("Cancela la transcripcion en curso")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.hide()
        prog_layout.addWidget(self.cancel_btn)

        layout.addWidget(prog_container)

        # ── Footer ──
        footer = QWidget()
        footer.setStyleSheet(f"border-top: 1px solid {C_BORDER};")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20, 10, 20, 12)
        f_layout.setSpacing(6)

        self.play_btn = QPushButton("Audio")
        self.play_btn.setStyleSheet(S_OPEN_DISABLED)
        self.play_btn.setEnabled(False)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setToolTip("Reproduce el audio.mp3 de la transcripcion actual")
        self.play_btn.clicked.connect(self._play_audio)
        f_layout.addWidget(self.play_btn)

        self.save_btn = QPushButton("Guardar")
        self.save_btn.setStyleSheet(S_OPEN_DISABLED)
        self.save_btn.setEnabled(False)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setToolTip("Sobreescribe transcripcion.txt con el texto editado")
        self.save_btn.clicked.connect(self._save_edited)
        f_layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setStyleSheet(S_COPY_DISABLED)
        self.copy_btn.setEnabled(False)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy)
        f_layout.addWidget(self.copy_btn)

        self.open_btn = QPushButton("Abrir carpeta")
        self.open_btn.setStyleSheet(S_OPEN_DISABLED)
        self.open_btn.setEnabled(False)
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setToolTip("Abre la carpeta de la transcripcion actual")
        self.open_btn.clicked.connect(self._open_session)
        f_layout.addWidget(self.open_btn)

        f_layout.addStretch()

        # Chip de idioma detectado (visible solo cuando hay deteccion automatica)
        self.lang_chip = QLabel("")
        self.lang_chip.setStyleSheet(S_CHIP_HW)
        self.lang_chip.hide()
        f_layout.addWidget(self.lang_chip)

        # Hardware badge: GPU si CUDA, sino CPU
        hw = hardware.hardware_summary()
        if hw["cuda"]:
            gpu_name = self._gpu_name() or "NVIDIA"
            hw_text = f"GPU: {gpu_name}"
            hw_style = S_CHIP_HW_GPU
        else:
            hw_text = f"CPU - {hw['ram_gb']:.0f} GB RAM"
            hw_style = S_CHIP_HW
        self.hw_chip = QLabel(hw_text)
        self.hw_chip.setStyleSheet(hw_style)
        self.hw_chip.setToolTip(
            f"Whisper corre en {WHISPER_DEVICE.upper()}\n"
            f"VRAM: {hw['vram_gb']:.1f} GB - RAM: {hw['ram_gb']:.1f} GB"
        )
        f_layout.addWidget(self.hw_chip)

        history_btn = QPushButton("Historial")
        history_btn.setStyleSheet(S_FOLDER)
        history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        history_btn.setToolTip("Ver transcripciones pasadas")
        history_btn.clicked.connect(self._open_history)
        f_layout.addWidget(history_btn)

        folder_btn = QPushButton("Carpeta")
        folder_btn.setStyleSheet(S_FOLDER)
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.setToolTip("Abre la carpeta raiz de transcripciones")
        folder_btn.clicked.connect(lambda: os.startfile(OUTPUT_DIR))
        f_layout.addWidget(folder_btn)

        layout.addWidget(footer)

        # Pulso del rec_dot (parpadea cada 600ms mientras grabo)
        self._rec_pulse = QTimer(self)
        self._rec_pulse.setInterval(600)
        self._rec_pulse.timeout.connect(self._toggle_rec_dot)
        self._rec_dot_visible = True

    @staticmethod
    def _gpu_name():
        """Nombre corto de la GPU primaria via nvidia-smi (e.g. 'RTX 5070'). Vacio si falla."""
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=3,
                creationflags=NO_WINDOW,
            )
            if r.returncode == 0:
                name = r.stdout.strip().splitlines()[0]
                # Acortar "NVIDIA GeForce RTX 5070" -> "RTX 5070"
                for tok in ("RTX", "GTX", "Quadro", "Tesla", "RTX A"):
                    if tok in name:
                        idx = name.find(tok)
                        return name[idx:]
                return name
        except Exception:
            pass
        return ""

    def _toggle_rec_dot(self):
        self._rec_dot_visible = not self._rec_dot_visible
        self.rec_dot.setVisible(self._rec_dot_visible and self.is_recording and not self.is_paused)

    def _init_timer(self):
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_timer)
        self._timer.start(500)

    def _init_hotkey(self):
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        shortcut.activated.connect(self._on_hotkey)

    # ── System tray ──
    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            log.info("System tray no disponible")
            return

        self.tray = QSystemTrayIcon(self._app_icon, self)
        self.tray.setToolTip("Transcriber")

        menu = QMenu()
        show_action = QAction("Mostrar", self)
        show_action.triggered.connect(self._show_from_tray)
        menu.addAction(show_action)

        record_action = QAction("Grabar / Detener", self)
        record_action.triggered.connect(self._on_hotkey)
        menu.addAction(record_action)

        menu.addSeparator()

        quit_action = QAction("Salir", self)
        quit_action.triggered.connect(self._real_quit)
        menu.addAction(quit_action)

        self._tray_menu = menu  # mantener referencia (Qt no aumenta refcount)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_from_tray()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _real_quit(self):
        self._allow_quit = True
        self.close()
        QApplication.quit()

    def _check_deps(self):
        if not FFMPEG_BIN:
            self._set_status("FFmpeg no encontrado", error=True)
            self.rec_btn.setEnabled(False)
            self.rec_btn.setStyleSheet(S_REC_DISABLED)
            self.upload_btn.setEnabled(False)
            self.upload_btn.setStyleSheet(S_BTN_DISABLED)
            log.error("FFmpeg no esta instalado o no esta en el PATH")
            QMessageBox.critical(
                self,
                "FFmpeg no encontrado",
                "Transcriber necesita FFmpeg para procesar audio.\n\n"
                "Si descargaste la version portable, asegurate de que la carpeta 'bin' "
                "este junto al ejecutable.\n\n"
                "Si estas corriendo desde codigo fuente, instalalo con:\n"
                "    winget install Gyan.FFmpeg",
            )
        else:
            log.info("FFmpeg: %s", FFMPEG_BIN)
        if not self.audio.available:
            log.info("Grabacion loopback no disponible (solo Windows)")

    # ── Preload del modelo ──
    def _is_model_downloaded(self):
        """Heuristica: dir del modelo existe y > 50 MB total = descargado."""
        model_dir = os.path.join(
            paths.models_dir(),
            f"models--Systran--faster-whisper-{self.whisper.model_name}",
        )
        if not os.path.isdir(model_dir):
            return False
        total = 0
        try:
            for root, _, files in os.walk(model_dir):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
                    if total > 50 * 1024 * 1024:
                        return True
        except Exception:
            pass
        return False

    def _preload_whisper(self):
        self._preload_error = None
        self._download_timer = None
        is_downloaded = self._is_model_downloaded()

        if is_downloaded:
            self._set_status(f"Cargando modelo {self.whisper.model_name}...")
        else:
            target_mb = MODEL_SIZES_MB.get(self.whisper.model_name, 3000)
            self._set_status(
                f"Descargando modelo {self.whisper.model_name} ({target_mb} MB, una sola vez)..."
            )
            self._start_download_monitor(target_mb)

        self._preload_thread = QThread()
        self._preload_thread.run = self._do_preload
        self._preload_thread.finished.connect(self._on_preload_done)
        self._preload_thread.start()

    def _start_download_monitor(self, target_mb):
        """Polea el tamano del dir del modelo cada 800ms para mostrar progreso."""
        self._download_target_mb = target_mb
        self._download_dir = os.path.join(
            paths.models_dir(),
            f"models--Systran--faster-whisper-{self.whisper.model_name}",
        )
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 / {target_mb} MB")
        self.progress_bar.show()

        self._download_timer = QTimer(self)
        self._download_timer.setInterval(800)
        self._download_timer.timeout.connect(self._poll_download)
        self._download_timer.start()

    def _poll_download(self):
        """Lee el tamano del dir y actualiza la barra."""
        if not os.path.isdir(self._download_dir):
            return
        total = 0
        try:
            for root, _, files in os.walk(self._download_dir):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except Exception:
            return
        mb = int(total / 1024 / 1024)
        pct = min(int(mb / self._download_target_mb * 100), 99)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{mb} / {self._download_target_mb} MB")

    def _stop_download_monitor(self):
        if self._download_timer is not None:
            self._download_timer.stop()
            self._download_timer.deleteLater()
            self._download_timer = None
        self.progress_bar.hide()
        self.progress_bar.setFormat("%p%")  # restablecer formato para transcripcion

    def _do_preload(self):
        try:
            self.whisper.load_model()
        except Exception as ex:
            log.error("Error precargando Whisper: %s", ex, exc_info=True)
            self._preload_error = str(ex)

    def _on_preload_done(self):
        self._preload_thread = None
        self._stop_download_monitor()
        if self._preload_error:
            self._whisper_loaded = False
            self._set_status("Error cargando modelo", error=True)
            QMessageBox.critical(
                self,
                "Error cargando modelo Whisper",
                f"No se pudo cargar el modelo {self.whisper.model_name}.\n\n"
                f"{self._preload_error}\n\n"
                "Verifica el log en _sistema\\transcriber.log (modo portable) "
                "o %LOCALAPPDATA%\\Transcriber\\transcriber.log (modo estandar).",
            )
            return
        self._whisper_loaded = True
        self._set_status("Listo")
        log.info("Modelo Whisper precargado")

    def _set_status(self, text, error=False):
        """Status chip color-coded segun el contenido."""
        self.status_chip.setText(text)
        if error:
            self.status_chip.setStyleSheet(S_CHIP_ERR)
        elif text in ("Listo", "Copiado al portapapeles") or text.startswith("Guardado"):
            self.status_chip.setStyleSheet(S_CHIP_OK)
        elif text.startswith(("Grabando", "Procesando", "Convirtiendo", "Cargando", "Transcribiendo", "Pausado")):
            self.status_chip.setStyleSheet(S_CHIP_BUSY)
        else:
            self.status_chip.setStyleSheet(S_CHIP)

    def _set_busy(self, busy):
        rec_ok = not busy and self.audio.available and bool(FFMPEG_BIN)
        upload_ok = not busy and bool(FFMPEG_BIN)
        self.rec_btn.setEnabled(rec_ok)
        self.rec_btn.setStyleSheet(S_REC if rec_ok else S_REC_DISABLED)
        self.upload_btn.setEnabled(upload_ok)
        self.upload_btn.setStyleSheet(S_UPLOAD if upload_ok else S_BTN_DISABLED)
        self.lang_combo.setEnabled(not busy)

    # ── Timer / hotkey ──
    def _update_timer(self):
        if self.is_recording and self._record_start and not self.is_paused:
            elapsed = datetime.datetime.now() - self._record_start - self._pause_total
            m, s = divmod(int(elapsed.total_seconds()), 60)
            h, m = divmod(m, 60)
            self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def _on_hotkey(self):
        if self.is_processing:
            return
        if self.is_recording:
            self._on_stop()
        elif self.audio.available:
            self._on_record()

    # ── Drag and drop ──
    @staticmethod
    def _is_audio_path(p):
        return p and p.lower().endswith(AUDIO_EXTS)

    def dragEnterEvent(self, event):
        # Por defecto no estamos en drop-target
        accept = False
        if not (self.is_recording or self.is_processing or not FFMPEG_BIN):
            md = event.mimeData()
            if md.hasUrls():
                for url in md.urls():
                    if url.isLocalFile() and self._is_audio_path(url.toLocalFile()):
                        accept = True
                        break
        if accept:
            event.acceptProposedAction()
            self._set_drop_target(True)
        else:
            self._set_drop_target(False)
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_target(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_target(False)
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = url.toLocalFile()
                if self._is_audio_path(p):
                    paths.append(p)
        if paths:
            event.acceptProposedAction()
            self._show_from_tray()
            self._start_file_queue(paths)
        else:
            event.ignore()

    def _set_drop_target(self, active):
        """Resalta el text area cuando hay un audio arrastrandose encima."""
        self.text_edit.setProperty("droptarget", "true" if active else "false")
        self.text_edit.style().unpolish(self.text_edit)
        self.text_edit.style().polish(self.text_edit)

    # ── Record ──
    def _on_record(self):
        if self.is_recording or self.is_processing or not FFMPEG_BIN or not self.audio.available:
            return

        session_dir = state.make_session_folder()
        if len(session_dir) > MAX_SESSION_DIR_LEN:
            log.error("Path de sesion muy largo (%d chars): %s", len(session_dir), session_dir)
            QMessageBox.warning(
                self, "Path muy largo",
                f"La carpeta de transcripciones esta demasiado adentro del filesystem ({len(session_dir)} caracteres).\n\n"
                "Movela a una ruta mas corta (ej: C:\\Transcriber\\) o usa el modo portable.",
            )
            shutil.rmtree(session_dir, ignore_errors=True)
            return

        source = AUDIO_SOURCES.get(self.source_combo.currentText(), SOURCE_LOOPBACK)
        try:
            self.audio.start(os.path.join(session_dir, "_raw.wav"), source=source)
        except Exception as ex:
            log.error("Error al iniciar grabacion: %s", ex)
            shutil.rmtree(session_dir, ignore_errors=True)
            self._set_status(f"Error: {ex}", error=True)
            return

        self._session_dir = session_dir
        self.is_recording = True
        self.is_paused = False
        self._record_start = datetime.datetime.now()
        self._pause_total = datetime.timedelta()
        self._pause_start = None
        self.current_text = ""
        self.text_edit.clear()
        self.timer_label.setText("00:00:00")

        self._segments = []
        self._text_dirty = False
        self.lang_chip.hide()

        self.rec_btn.setEnabled(False)
        self.rec_btn.setStyleSheet(S_REC_OFF)
        self.upload_btn.setEnabled(False)
        self.upload_btn.setStyleSheet(S_BTN_DISABLED)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setStyleSheet(S_PAUSE)
        self.pause_btn.setText("PAUSAR")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet(S_STOP)
        for btn, dis in (
            (self.open_btn, S_OPEN_DISABLED),
            (self.copy_btn, S_COPY_DISABLED),
            (self.play_btn, S_OPEN_DISABLED),
            (self.save_btn, S_OPEN_DISABLED),
        ):
            btn.setEnabled(False)
            btn.setStyleSheet(dis)
        self.rec_dot.show()
        self._rec_dot_visible = True
        self._rec_pulse.start()
        self._set_status("Grabando...")

    def _on_pause(self):
        if not self.is_recording:
            return
        if not self.is_paused:
            self.is_paused = True
            self._pause_start = datetime.datetime.now()
            self.audio.pause()
            self.pause_btn.setText("REANUDAR")
            self.pause_btn.setStyleSheet(S_RESUME)
            self.rec_dot.hide()
            self._rec_pulse.stop()
            self._set_status("Pausado")
        else:
            self.is_paused = False
            if self._pause_start:
                self._pause_total += datetime.datetime.now() - self._pause_start
                self._pause_start = None
            self.audio.resume()
            self.pause_btn.setText("PAUSAR")
            self.pause_btn.setStyleSheet(S_PAUSE)
            self.rec_dot.show()
            self._rec_dot_visible = True
            self._rec_pulse.start()
            self._set_status("Grabando...")

    def _on_stop(self):
        if not self.is_recording or self.is_processing:
            return

        self.is_recording = False
        self.is_processing = True
        self.is_paused = False

        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(S_BTN_DISABLED)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet(S_BTN_DISABLED)
        self.pause_btn.setText("PAUSAR")
        self.rec_dot.hide()
        self._rec_pulse.stop()
        self._set_status("Procesando...")
        self.timer_label.setText("")

        lang = LANGUAGES.get(self.lang_combo.currentText())
        self._process_thread = ProcessThread(
            self.audio, self.whisper, self._whisper_loaded, self._session_dir, lang,
        )
        self._wire_thread(self._process_thread, on_done=self._on_thread_done)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_btn.show()
        self._process_thread.start()

    # ── Upload (uno o varios) ──
    def _on_upload(self):
        if self.is_recording or self.is_processing:
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar uno o varios archivos de audio", "", AUDIO_FORMATS,
        )
        if not file_paths:
            return
        self._start_file_queue(file_paths)

    def _start_file_queue(self, file_paths):
        """Encola N archivos y arranca el primero. Los siguientes se disparan en _on_process_ok."""
        if self.is_recording or self.is_processing or not FFMPEG_BIN:
            return
        # Filtrar solo audios validos
        valid = [p for p in file_paths if self._is_audio_path(p)]
        if not valid:
            return
        self._file_queue = valid[1:]  # los siguientes despues del primero
        self._queue_total = len(valid)
        self._start_single_file(valid[0], queue_position=1)

    def _start_single_file(self, file_path, queue_position=1):
        self._session_dir = state.make_session_folder()
        self.is_processing = True
        self.current_text = ""
        self._segments = []
        self._text_dirty = False
        self.lang_chip.hide()
        self.text_edit.blockSignals(True)
        self.text_edit.clear()
        self.text_edit.blockSignals(False)
        self._set_busy(True)
        prefix = (f"({queue_position}/{self._queue_total}) "
                  if self._queue_total > 1 else "")
        self._set_status(f"{prefix}Procesando: {os.path.basename(file_path)}")

        lang = LANGUAGES.get(self.lang_combo.currentText())
        self._file_thread = FileTranscribeThread(
            self.whisper, self._whisper_loaded, file_path, self._session_dir, lang,
        )
        self._wire_thread(self._file_thread, on_done=self._on_file_thread_done)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_btn.show()
        self._file_thread.start()

    def _process_next_in_queue(self):
        if not self._file_queue:
            self._queue_total = 0
            return
        next_path = self._file_queue.pop(0)
        position = self._queue_total - len(self._file_queue)
        self._start_single_file(next_path, queue_position=position)

    def _wire_thread(self, thread, on_done):
        thread.status.connect(self._set_status)
        thread.progress.connect(self._on_progress)
        thread.finished_ok.connect(self._on_process_ok)
        thread.finished_err.connect(self._on_process_err)
        thread.finished.connect(on_done)

    # ── Callbacks de procesamiento ──
    def _on_progress(self, pct, partial_text):
        self.progress_bar.setValue(pct)
        self.text_edit.setPlainText(partial_text)
        self._set_status(f"Transcribiendo... {pct}%")

    def _on_process_ok(self, result):
        """result es dict: {text, segments, language, language_probability, cancelled}."""
        if self._process_thread and self._process_thread.model_loaded:
            self._whisper_loaded = True
        if self._file_thread and self._file_thread.model_loaded:
            self._whisper_loaded = True

        text = result.get("text", "")
        self.current_text = text
        self._segments = result.get("segments", [])

        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(text)
        self.text_edit.blockSignals(False)
        self._text_dirty = False

        self._auto_save_transcription()
        self._show_detected_language(result)

        # Si quedan archivos en la cola, procesar el siguiente
        if self._file_queue:
            log.info("Cola: %d archivos restantes", len(self._file_queue))
            # Limpieza intermedia: hide cancel/progress momentaneamente, no enable acciones
            self.cancel_btn.hide()
            self.progress_bar.hide()
            self.is_processing = False  # _start_single_file lo vuelve a poner True
            QTimer.singleShot(150, self._process_next_in_queue)
            return

        # Cola vacia: terminado
        self._finish_processing("Listo", enable_actions=True)
        if self.tray and not self.isActiveWindow():
            self.tray.showMessage(
                "Transcripcion lista",
                text[:120] + ("..." if len(text) > 120 else ""),
                QSystemTrayIcon.MessageIcon.Information, 4000,
            )

    def _show_detected_language(self, result):
        """Muestra chip 'Detectado: es (98%)' si la deteccion fue automatica."""
        chosen = self.lang_combo.currentText()
        # Solo muestro el chip si el usuario uso Auto (sino el idioma es el que eligio)
        if chosen != "Auto-detectar":
            self.lang_chip.hide()
            return
        lang = result.get("language", "")
        prob = result.get("language_probability", 0.0)
        if not lang:
            self.lang_chip.hide()
            return
        self.lang_chip.setText(f"Detectado: {lang} ({int(prob * 100)}%)")
        self.lang_chip.show()

    def _auto_save_transcription(self):
        """Guarda transcripcion.txt + transcripcion.srt en la carpeta de sesion."""
        if not self.current_text or not self._session_dir:
            return
        # .txt
        try:
            txt_path = os.path.join(self._session_dir, "transcripcion.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(self.current_text)
            log.info("Auto-guardado: %s", txt_path)
        except Exception as ex:
            log.warning("No se pudo auto-guardar txt: %s", ex)
        # .srt (si hay segmentos)
        if self._segments:
            try:
                srt_path = os.path.join(self._session_dir, "transcripcion.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(build_srt(self._segments))
                log.info("Auto-guardado SRT: %s", srt_path)
            except Exception as ex:
                log.warning("No se pudo auto-guardar srt: %s", ex)

    def _save_edited(self):
        """Sobreescribe transcripcion.txt con el texto editado actualmente en el TextEdit."""
        if not self._session_dir:
            return
        edited = self.text_edit.toPlainText()
        try:
            path = os.path.join(self._session_dir, "transcripcion.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(edited)
            self.current_text = edited
            self._text_dirty = False
            self._set_status("Guardado")
            self._refresh_save_btn()
        except Exception as ex:
            log.error("Error guardando: %s", ex)
            self._set_status(f"Error guardando: {ex}", error=True)

    def _on_text_changed(self):
        """Marca el texto como 'modificado' si el usuario lo edita manualmente."""
        # Solo activar cuando hay sesion activa (no durante setPlainText programatico)
        if not self._session_dir or self.is_processing:
            return
        edited = self.text_edit.toPlainText()
        self._text_dirty = (edited != self.current_text)
        self._refresh_save_btn()

    def _refresh_save_btn(self):
        """Habilita Guardar solo cuando el texto esta editado y hay sesion."""
        can_save = bool(self._session_dir) and self._text_dirty and not self.is_processing
        self.save_btn.setEnabled(can_save)
        self.save_btn.setStyleSheet(S_OPEN if can_save else S_OPEN_DISABLED)

    def _play_audio(self):
        """Abre el audio.mp3 de la sesion actual en el reproductor por default."""
        if not self._session_dir:
            return
        mp3 = os.path.join(self._session_dir, "audio.mp3")
        if os.path.exists(mp3):
            os.startfile(mp3)
        else:
            self._set_status("audio.mp3 no encontrado en la sesion", error=True)

    def _on_cancel(self):
        """Aborta la transcripcion en curso (cooperativo)."""
        for t in (self._process_thread, self._file_thread):
            if t is not None and t.isRunning():
                log.info("Cancelando thread...")
                t.cancel()
                self._set_status("Cancelando...")

    def _on_process_err(self, msg):
        log.warning("Procesamiento: %s", msg)
        # Si hay cola, decisiones segun tipo de error:
        # - Cancelado por usuario: vaciar cola entera
        # - Otro error: continuar con el proximo (no perder el batch)
        if msg == "Cancelado" and self._file_queue:
            n = len(self._file_queue)
            self._file_queue.clear()
            self._queue_total = 0
            log.info("Cola cancelada (%d archivos descartados)", n)
        elif self._file_queue:
            self.cancel_btn.hide()
            self.progress_bar.hide()
            self.is_processing = False
            QTimer.singleShot(150, self._process_next_in_queue)
            return
        self._finish_processing(msg, error=True)

    def _on_thread_done(self):
        self._process_thread = None

    def _on_file_thread_done(self):
        self._file_thread = None

    def _finish_processing(self, status, enable_actions=False, error=False):
        self.is_processing = False
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self._set_status(status, error=error)
        self._set_busy(False)
        if enable_actions:
            self.open_btn.setEnabled(True)
            self.open_btn.setStyleSheet(S_OPEN)
            self.copy_btn.setEnabled(True)
            self.copy_btn.setStyleSheet(S_COPY)
            # Audio play disponible solo si audio.mp3 existe
            mp3 = os.path.join(self._session_dir or "", "audio.mp3")
            if os.path.exists(mp3):
                self.play_btn.setEnabled(True)
                self.play_btn.setStyleSheet(S_OPEN)
            self._refresh_save_btn()

    # ── Acciones del footer ──
    def _open_session(self):
        if self._session_dir and os.path.isdir(self._session_dir):
            os.startfile(self._session_dir)
        else:
            os.startfile(OUTPUT_DIR)

    def _open_history(self):
        """Abre el historial de transcripciones; si el usuario carga una, la trae al editor."""
        if self.is_processing or self.is_recording:
            self._set_status("Espera a que termine la operacion actual", error=True)
            return
        dlg = HistoryDialog(OUTPUT_DIR, parent=self)
        dlg.setWindowIcon(self._app_icon)
        dlg.setStyleSheet(STYLE)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_dir:
            self._load_session(dlg.selected_dir)

    def _load_session(self, session_dir):
        """Carga transcripcion.txt + transcripcion.srt de una sesion previa al editor."""
        txt_path = os.path.join(session_dir, "transcripcion.txt")
        if not os.path.isfile(txt_path):
            self._set_status("La transcripcion no existe en esa sesion", error=True)
            return
        try:
            with open(txt_path, encoding="utf-8") as f:
                text = f.read()
        except Exception as ex:
            log.error("No se pudo leer %s: %s", txt_path, ex)
            self._set_status(f"Error leyendo: {ex}", error=True)
            return

        self._session_dir = session_dir
        self.current_text = text
        self._segments = []  # podriamos parsear .srt si quisiera, no necesario para edit
        self._text_dirty = False
        self.lang_chip.hide()
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(text)
        self.text_edit.blockSignals(False)

        # Habilitar acciones
        self.open_btn.setEnabled(True)
        self.open_btn.setStyleSheet(S_OPEN)
        self.copy_btn.setEnabled(True)
        self.copy_btn.setStyleSheet(S_COPY)
        if os.path.exists(os.path.join(session_dir, "audio.mp3")):
            self.play_btn.setEnabled(True)
            self.play_btn.setStyleSheet(S_OPEN)
        self._refresh_save_btn()

        rel = os.path.relpath(session_dir, OUTPUT_DIR)
        self._set_status(f"Cargado: {rel}")
        log.info("Sesion cargada: %s", session_dir)

    def _copy(self):
        if not self.current_text:
            return
        QApplication.clipboard().setText(self.current_text)
        self._set_status("Copiado al portapapeles")

    # ── Cierre ──
    def closeEvent(self, event):
        if self.tray and not self._allow_quit and not self.is_recording:
            self.hide()
            if not self.settings.value("tray_message_shown", False, type=bool):
                self.tray.showMessage(
                    "Transcriber",
                    "Sigo corriendo en la bandeja. Click derecho > Salir para cerrar.",
                    QSystemTrayIcon.MessageIcon.Information, 3500,
                )
                self.settings.setValue("tray_message_shown", True)
            event.ignore()
            return

        # Desconectar callbacks que podrian dispararse despues de destruir widgets
        if self._preload_thread is not None:
            try:
                self._preload_thread.finished.disconnect(self._on_preload_done)
            except (RuntimeError, TypeError):
                pass

        # Matar procesos FFmpeg activos antes de esperar (no zombies)
        for t in (self._process_thread, self._file_thread):
            if t is not None and t.isRunning():
                if hasattr(t, "kill_subprocesses"):
                    t.kill_subprocesses()

        for t in (self._process_thread, self._file_thread, self._preload_thread):
            if t is not None and t.isRunning():
                t.wait(5000)

        self.audio.cleanup()
        self._save_settings()
        if self.tray:
            self.tray.hide()
        event.accept()


# ── Entry point ──
def _splash_msg(splash, app, text):
    splash.showMessage(
        text,
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#8b949e"),
    )
    app.processEvents()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # tray-aware: cerrar ventana no mata el proceso

    if not try_acquire_single_instance():
        log.info("Otra instancia ya corre, saliendo")
        sys.exit(0)

    icon = make_app_icon()
    app.setWindowIcon(icon)

    splash = QSplashScreen(make_splash_pixmap(), Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    _splash_msg(splash, app, "Iniciando...")

    _splash_msg(splash, app, "Organizando archivos...")
    try:
        state.migrate_old_layout()
    except Exception as ex:
        log.warning("Migracion fallo (no critica): %s", ex, exc_info=True)

    _splash_msg(splash, app, "Verificando modelos...")
    try:
        state.dedupe_models_at_startup(WHISPER_MODEL)
    except Exception as ex:
        log.warning("Dedupe fallo (no critico): %s", ex, exc_info=True)

    _splash_msg(splash, app, "Cargando interfaz...")
    window = TranscriberApp(app_icon=icon)
    window._single_server = SingleInstanceServer(window)

    _splash_msg(splash, app, "Listo. Whisper se carga en segundo plano.")
    window.show()
    splash.finish(window)
    sys.exit(app.exec())
