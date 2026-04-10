import os
import sys
import glob
import logging
import subprocess
import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QComboBox, QLabel, QProgressBar, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence, QPixmap, QPainter, QColor, QFont, QIcon

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Agregar DLLs de NVIDIA al PATH
for _base in [os.path.dirname(sys.executable), os.path.join(os.path.dirname(__file__), "venv", "Scripts")]:
    _sp = os.path.join(_base, "..", "Lib", "site-packages")
    for _d in glob.glob(os.path.join(_sp, "nvidia", "*", "bin")):
        os.add_dll_directory(os.path.abspath(_d))
        os.environ["PATH"] = os.path.abspath(_d) + os.pathsep + os.environ.get("PATH", "")

from config import OUTPUT_DIR, LANGUAGES, FFMPEG_BIN, WHISPER_DEVICE, AUDIO_FORMATS
from audio_capture import AudioCapture
from transcriber import Transcriber


# ── Estilos ──
STYLE = """
QMainWindow { background-color: #0d1117; }
QWidget { background-color: transparent; }
QLabel { color: #8b949e; font-size: 12px; }

QTextEdit {
    background-color: #161b22; color: #c9d1d9; border: 1px solid #21262d;
    border-radius: 10px; padding: 12px; font-family: Consolas; font-size: 13px;
    selection-background-color: #264f78;
}
QTextEdit:focus { border: 1px solid #388bfd; }

QComboBox {
    background-color: #21262d; color: #c9d1d9; border: 1px solid #30363d;
    border-radius: 10px; padding: 6px 12px; font-size: 12px; min-width: 130px;
}
QComboBox::drop-down { border: none; padding-right: 10px; }
QComboBox QAbstractItemView {
    background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d;
    selection-background-color: #264f78; padding: 4px;
}

QProgressBar {
    background-color: #161b22; border: 1px solid #21262d; border-radius: 6px;
    height: 12px; text-align: center; font-size: 10px; color: #8b949e;
}
QProgressBar::chunk { background-color: #238636; border-radius: 5px; }
"""

# Estilos inline para botones (evita problemas con selectores #id en Windows)
BTN = "border: none; border-radius: 18px; padding: 8px 18px; font-weight: bold; font-size: 12px; color: white;"
BTN_DISABLED = "border: none; border-radius: 18px; padding: 8px 18px; font-weight: bold; font-size: 12px; background-color: #161b22; color: #30363d;"
BTN_SM = "border: none; border-radius: 10px; padding: 6px 14px; font-weight: bold; font-size: 12px; color: white;"

S_REC = BTN + "background-color: #da3633;"
S_REC_OFF = BTN + "background-color: #484f58;"
S_PAUSE = BTN + "background-color: #e6a817;"
S_RESUME = BTN + "background-color: #238636;"
S_STOP = BTN + "background-color: #da3633;"
S_UPLOAD = BTN + "background-color: #1f6feb;"
S_SAVE = BTN_SM + "background-color: #238636;"
S_COPY = BTN_SM + "background-color: #21262d; color: #8b949e;"
S_FOLDER = "border: 1px solid #21262d; border-radius: 10px; padding: 6px 14px; font-size: 12px; background-color: transparent; color: #484f58;"
S_CHIP = "background-color: #161b22; border: 1px solid #21262d; border-radius: 12px; padding: 4px 12px; font-size: 11px; color: #8b949e;"
S_CHIP_ERR = "background-color: #da3633; border: none; border-radius: 12px; padding: 4px 12px; font-size: 11px; color: white;"


class ProcessThread(QThread):
    """Hilo para procesar audio grabado."""
    status = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, audio, whisper, whisper_loaded, session_dir, session_ts, lang):
        super().__init__()
        self.audio = audio
        self.whisper = whisper
        self.whisper_loaded = whisper_loaded
        self.session_dir = session_dir
        self.session_ts = session_ts
        self.lang = lang
        self.model_loaded = False

    def run(self):
        try:
            wav_path = self.audio.stop_raw()
            if not wav_path:
                self.finished_err.emit("Sin audio detectado")
                return

            mp3 = os.path.join(self.session_dir, f"audio_{self.session_ts}.mp3")
            mono = os.path.join(self.session_dir, f"_mono_{self.session_ts}.wav")

            self.status.emit("Convirtiendo audio...")
            procs = [
                subprocess.Popen(
                    [FFMPEG_BIN, "-y", "-i", wav_path, "-b:a", "128k", mp3],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ),
                subprocess.Popen(
                    [FFMPEG_BIN, "-y", "-i", wav_path, "-ac", "1", "-ar", "16000", mono],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ),
            ]
            for p in procs:
                p.wait()

            if not os.path.exists(mono):
                self.finished_err.emit("Error: FFmpeg fallo")
                return

            try:
                os.unlink(wav_path)
            except OSError as ex:
                log.warning("No se pudo eliminar WAV: %s", ex)

            if not self.whisper_loaded:
                self.status.emit("Cargando modelo Whisper...")
                self.whisper.load_model()
                self.model_loaded = True

            self.status.emit("Transcribiendo...")
            text = self.whisper.transcribe(
                mono, language=self.lang,
                on_progress=lambda pct, partial: self.progress.emit(pct, partial),
            ).strip()

            try:
                os.unlink(mono)
            except OSError:
                pass

            self.finished_ok.emit(text if text else "No se detecto voz en el audio.")

        except Exception as ex:
            log.error("Error en procesamiento", exc_info=True)
            self.finished_err.emit(f"Error: {ex}")


class FileTranscribeThread(QThread):
    """Hilo para transcribir un archivo subido."""
    status = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, whisper, whisper_loaded, file_path, session_dir, lang):
        super().__init__()
        self.whisper = whisper
        self.whisper_loaded = whisper_loaded
        self.file_path = file_path
        self.session_dir = session_dir
        self.lang = lang
        self.model_loaded = False

    def run(self):
        try:
            mono = os.path.join(self.session_dir, "_mono_upload.wav")

            self.status.emit("Convirtiendo audio...")
            proc = subprocess.run(
                [FFMPEG_BIN, "-y", "-i", self.file_path, "-ac", "1", "-ar", "16000", mono],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if proc.returncode != 0 or not os.path.exists(mono):
                self.finished_err.emit("Error: FFmpeg no pudo convertir el archivo")
                return

            if not self.whisper_loaded:
                self.status.emit("Cargando modelo Whisper...")
                self.whisper.load_model()
                self.model_loaded = True

            self.status.emit("Transcribiendo...")
            text = self.whisper.transcribe(
                mono, language=self.lang,
                on_progress=lambda pct, partial: self.progress.emit(pct, partial),
            ).strip()

            try:
                os.unlink(mono)
            except OSError:
                pass

            self.finished_ok.emit(text if text else "No se detecto voz en el audio.")

        except Exception as ex:
            log.error("Error en procesamiento de archivo", exc_info=True)
            self.finished_err.emit(f"Error: {ex}")


class TranscriberApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.audio = AudioCapture()
        self.whisper = Transcriber()
        self.is_recording = False
        self.is_paused = False
        self.is_processing = False
        self._whisper_loaded = False
        self._session_dir = None
        self._session_ts = ""
        self._record_start = None
        self._pause_total = datetime.timedelta()
        self._pause_start = None
        self.current_text = ""
        self._process_thread = None
        self._file_thread = None

        self._init_ui()
        self._init_timer()
        self._init_hotkey()
        self._check_deps()
        self._preload_whisper()

    @staticmethod
    def _create_icon():
        sizes = [16, 32, 48, 64]
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

    def _init_ui(self):
        self.setWindowTitle("Transcriber")
        self.resize(520, 440)
        self.setMinimumSize(380, 300)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(self._create_icon())

        central = QWidget()
        central.setStyleSheet("background-color: #0d1117;")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setStyleSheet("background-color: #161b22; border-bottom: 1px solid #21262d;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("TRANSCRIBER")
        title.setStyleSheet("color: #ff6b6b; font-size: 15px; font-weight: bold; letter-spacing: 2px;")
        h_layout.addWidget(title)

        h_layout.addStretch()

        self.rec_dot = QLabel("●")
        self.rec_dot.setStyleSheet("color: #da3633; font-size: 16px;")
        self.rec_dot.hide()
        h_layout.addWidget(self.rec_dot)

        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet("color: #ff6b6b; font-size: 16px; font-weight: bold;")
        h_layout.addWidget(self.timer_label)

        self.status_chip = QLabel("Listo")
        self.status_chip.setStyleSheet(S_CHIP)
        h_layout.addWidget(self.status_chip)

        layout.addWidget(header)

        # ── Controls row 1: grabar / pausar / detener ──
        row1 = QWidget()
        r1 = QHBoxLayout(row1)
        r1.setContentsMargins(20, 8, 20, 0)
        r1.setSpacing(6)

        self.rec_btn = QPushButton("GRABAR")
        self.rec_btn.setStyleSheet(S_REC)
        self.rec_btn.setFixedHeight(34)
        self.rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rec_btn.clicked.connect(self._on_record)
        if not self.audio.available:
            self.rec_btn.setEnabled(False)
            self.rec_btn.setStyleSheet(BTN_DISABLED)
            self.rec_btn.setToolTip("Grabacion loopback solo disponible en Windows")
        r1.addWidget(self.rec_btn)

        self.pause_btn = QPushButton("PAUSAR")
        self.pause_btn.setStyleSheet(BTN_DISABLED)
        self.pause_btn.setFixedHeight(34)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self._on_pause)
        r1.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("DETENER")
        self.stop_btn.setStyleSheet(BTN_DISABLED)
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self._on_stop)
        r1.addWidget(self.stop_btn)

        r1.addStretch()
        layout.addWidget(row1)

        # ── Controls row 2: archivo / idioma ──
        row2 = QWidget()
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(20, 4, 20, 6)
        r2.setSpacing(6)

        self.upload_btn = QPushButton("SUBIR ARCHIVO")
        self.upload_btn.setStyleSheet(S_UPLOAD)
        self.upload_btn.setFixedHeight(34)
        self.upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_btn.setToolTip("Transcribir un archivo de audio (mp3, wav, m4a...)")
        self.upload_btn.clicked.connect(self._on_upload)
        r2.addWidget(self.upload_btn)

        r2.addStretch()

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(LANGUAGES.keys())
        self.lang_combo.setFixedHeight(34)
        r2.addWidget(self.lang_combo)

        layout.addWidget(row2)

        # ── Text area ──
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText("La transcripcion aparecera aqui...")
        te_container = QWidget()
        te_layout = QVBoxLayout(te_container)
        te_layout.setContentsMargins(20, 6, 20, 6)
        te_layout.addWidget(self.text_edit)
        layout.addWidget(te_container, stretch=1)

        # ── Progress bar ──
        prog_container = QWidget()
        prog_layout = QHBoxLayout(prog_container)
        prog_layout.setContentsMargins(20, 0, 20, 4)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.hide()
        prog_layout.addWidget(self.progress_bar)

        layout.addWidget(prog_container)

        # ── Footer ──
        footer = QWidget()
        footer.setStyleSheet("border-top: 1px solid #21262d;")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20, 8, 20, 12)
        f_layout.setSpacing(6)

        self.save_btn = QPushButton("Guardar")
        self.save_btn.setStyleSheet(BTN_DISABLED)
        self.save_btn.setFixedHeight(32)
        self.save_btn.setEnabled(False)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._save)
        f_layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setStyleSheet(BTN_DISABLED)
        self.copy_btn.setFixedHeight(32)
        self.copy_btn.setEnabled(False)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy)
        f_layout.addWidget(self.copy_btn)

        f_layout.addStretch()

        device_label = QLabel(f"Whisper: {WHISPER_DEVICE.upper()}")
        device_label.setStyleSheet("color: #30363d; font-size: 10px;")
        f_layout.addWidget(device_label)

        folder_btn = QPushButton("Carpeta")
        folder_btn.setStyleSheet(S_FOLDER)
        folder_btn.setFixedHeight(32)
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.clicked.connect(lambda: os.startfile(OUTPUT_DIR))
        f_layout.addWidget(folder_btn)

        layout.addWidget(footer)

    def _init_timer(self):
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_timer)
        self._timer.start(500)

    def _init_hotkey(self):
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        shortcut.activated.connect(self._on_hotkey)

    def _check_deps(self):
        if not FFMPEG_BIN:
            self._set_status("FFmpeg no encontrado", error=True)
            self.rec_btn.setEnabled(False)
            self.rec_btn.setStyleSheet(BTN_DISABLED)
            self.upload_btn.setEnabled(False)
            self.upload_btn.setStyleSheet(BTN_DISABLED)
            log.error("FFmpeg no esta instalado o no esta en el PATH")
        else:
            log.info("FFmpeg: %s", FFMPEG_BIN)
        if not self.audio.available:
            log.info("Grabacion loopback no disponible (solo Windows)")

    def _preload_whisper(self):
        """Precarga el modelo Whisper en segundo plano al abrir la app."""
        self._preload_thread = QThread()
        self._preload_thread.run = self._do_preload
        self._set_status("Cargando modelo Whisper...")
        self._preload_thread.finished.connect(self._on_preload_done)
        self._preload_thread.start()

    def _do_preload(self):
        try:
            self.whisper.load_model()
        except Exception as ex:
            log.error("Error precargando Whisper: %s", ex)

    def _on_preload_done(self):
        self._whisper_loaded = True
        self._preload_thread = None
        self._set_status("Listo")
        log.info("Modelo Whisper precargado")

    def _set_status(self, text, error=False):
        self.status_chip.setText(text)
        self.status_chip.setStyleSheet(S_CHIP_ERR if error else S_CHIP)

    def _set_busy(self, busy):
        """Deshabilita/habilita controles durante procesamiento."""
        rec_ok = not busy and self.audio.available and bool(FFMPEG_BIN)
        upload_ok = not busy and bool(FFMPEG_BIN)
        self.rec_btn.setEnabled(rec_ok)
        self.rec_btn.setStyleSheet(S_REC if rec_ok else BTN_DISABLED)
        self.upload_btn.setEnabled(upload_ok)
        self.upload_btn.setStyleSheet(S_UPLOAD if upload_ok else BTN_DISABLED)
        self.lang_combo.setEnabled(not busy)

    # ── Timer ──
    def _update_timer(self):
        if self.is_recording and self._record_start and not self.is_paused:
            elapsed = datetime.datetime.now() - self._record_start - self._pause_total
            m, s = divmod(int(elapsed.total_seconds()), 60)
            h, m = divmod(m, 60)
            self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    # ── Hotkey ──
    def _on_hotkey(self):
        if self.is_processing:
            return
        if self.is_recording:
            self._on_stop()
        elif self.audio.available:
            self._on_record()

    # ── Record ──
    def _on_record(self):
        if self.is_recording or self.is_processing or not FFMPEG_BIN or not self.audio.available:
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = os.path.join(OUTPUT_DIR, f"grabacion_{ts}")
        os.makedirs(session_dir, exist_ok=True)

        try:
            self.audio.start(os.path.join(session_dir, f"audio_{ts}.wav"))
        except Exception as ex:
            log.error("Error al iniciar grabacion: %s", ex)
            os.rmdir(session_dir)
            self._set_status(f"Error: {ex}", error=True)
            return

        self._session_dir = session_dir
        self._session_ts = ts
        self.is_recording = True
        self.is_paused = False
        self._record_start = datetime.datetime.now()
        self._pause_total = datetime.timedelta()
        self._pause_start = None
        self.current_text = ""
        self.text_edit.clear()
        self.timer_label.setText("00:00:00")

        self.rec_btn.setEnabled(False)
        self.rec_btn.setStyleSheet(S_REC_OFF)
        self.upload_btn.setEnabled(False)
        self.upload_btn.setStyleSheet(BTN_DISABLED)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setStyleSheet(S_PAUSE)
        self.pause_btn.setText("PAUSAR")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet(S_STOP)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(BTN_DISABLED)
        self.copy_btn.setEnabled(False)
        self.copy_btn.setStyleSheet(BTN_DISABLED)
        self.rec_dot.show()
        self._set_status("Grabando...")

    # ── Pause ──
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
            self._set_status("Grabando...")

    # ── Stop ──
    def _on_stop(self):
        if not self.is_recording or self.is_processing:
            return

        self.is_recording = False
        self.is_processing = True
        self.is_paused = False

        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(BTN_DISABLED)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setStyleSheet(BTN_DISABLED)
        self.pause_btn.setText("PAUSAR")
        self.rec_dot.hide()
        self._set_status("Procesando...")
        self.timer_label.setText("")

        lang = LANGUAGES.get(self.lang_combo.currentText())
        self._process_thread = ProcessThread(
            self.audio, self.whisper, self._whisper_loaded,
            self._session_dir, self._session_ts, lang,
        )
        self._process_thread.status.connect(lambda msg: self._set_status(msg))
        self._process_thread.progress.connect(self._on_progress)
        self._process_thread.finished_ok.connect(self._on_process_ok)
        self._process_thread.finished_err.connect(self._on_process_err)
        self._process_thread.finished.connect(self._on_thread_done)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._process_thread.start()

    # ── Upload file ──
    def _on_upload(self):
        if self.is_recording or self.is_processing:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo de audio", "", AUDIO_FORMATS,
        )
        if not file_path:
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = os.path.join(OUTPUT_DIR, f"archivo_{ts}")
        os.makedirs(self._session_dir, exist_ok=True)
        self._session_ts = ts

        self.is_processing = True
        self.current_text = ""
        self.text_edit.clear()
        self._set_busy(True)
        self._set_status(f"Procesando: {os.path.basename(file_path)}")

        lang = LANGUAGES.get(self.lang_combo.currentText())
        self._file_thread = FileTranscribeThread(
            self.whisper, self._whisper_loaded, file_path, self._session_dir, lang,
        )
        self._file_thread.status.connect(lambda msg: self._set_status(msg))
        self._file_thread.progress.connect(self._on_progress)
        self._file_thread.finished_ok.connect(self._on_process_ok)
        self._file_thread.finished_err.connect(self._on_process_err)
        self._file_thread.finished.connect(self._on_file_thread_done)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._file_thread.start()

    # ── Shared callbacks ──
    def _on_progress(self, pct, partial_text):
        self.progress_bar.setValue(pct)
        self.text_edit.setPlainText(partial_text)
        self._set_status(f"Transcribiendo... {pct}%")

    def _on_process_ok(self, text):
        if self._process_thread and self._process_thread.model_loaded:
            self._whisper_loaded = True
        if self._file_thread and self._file_thread.model_loaded:
            self._whisper_loaded = True
        self.current_text = text
        self.text_edit.setPlainText(text)
        self._finish_processing("Listo", enable_save=True)

    def _on_process_err(self, msg):
        log.warning("Procesamiento: %s", msg)
        self._finish_processing(msg, error=True)

    def _on_thread_done(self):
        self._process_thread = None

    def _on_file_thread_done(self):
        self._file_thread = None

    def _finish_processing(self, status, enable_save=False, error=False):
        self.is_processing = False
        self.progress_bar.hide()
        self._set_status(status, error=error)
        self._set_busy(False)
        if enable_save:
            self.save_btn.setEnabled(True)
            self.save_btn.setStyleSheet(S_SAVE)
            self.copy_btn.setEnabled(True)
            self.copy_btn.setStyleSheet(S_COPY)

    # ── Save / Copy ──
    def _save(self):
        if not self.current_text or not self._session_dir:
            return
        path = os.path.join(self._session_dir, f"transcripcion_{self._session_ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.current_text)
        log.info("Guardado: %s", path)
        self._set_status(f"Guardado en {os.path.basename(self._session_dir)}/")

    def _copy(self):
        if not self.current_text:
            return
        QApplication.clipboard().setText(self.current_text)
        self._set_status("Copiado al portapapeles")

    def closeEvent(self, event):
        if self._process_thread and self._process_thread.isRunning():
            self._process_thread.wait(5000)
        if self._file_thread and self._file_thread.isRunning():
            self._file_thread.wait(5000)
        self.audio.cleanup()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriberApp()
    window.show()
    sys.exit(app.exec())
