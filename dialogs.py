"""Ventanas secundarias de la aplicacion."""
import os
import shutil
import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QVBoxLayout,
)

import state
import theme
from utils import open_in_explorer

# A 128 kbps constantes (lo que produce el conversor), un segundo de audio son 16 KB.
BYTES_POR_SEGUNDO_MP3 = 16000


class HistoryDialog(QDialog):
    """Lista las transcripciones pasadas, mas recientes arriba, y permite recargarlas.

    Lee el layout en disco con las expresiones de `state`, que es su dueno, en vez de
    repetirlas aca.
    """

    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historial de transcripciones")
        self.setMinimumSize(620, 480)
        self.output_dir = output_dir
        self.selected_dir = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        info = QLabel("Doble click para cargar; click derecho para abrir la carpeta o borrar.")
        info.setStyleSheet(f"color: {theme.C_TEXT_DIM}; font-size: 12px;")
        layout.addWidget(info)

        # El estilo de la lista viene de theme.STYLE, que el padre ya aplica.
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        for texto, estilo, accion in (
            ("Cargar", theme.S_DIALOG_OK, self._on_load),
            ("Cerrar", theme.S_DIALOG_CLOSE, self.reject),
        ):
            btn = QPushButton(texto)
            btn.setStyleSheet(estilo)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(accion)
            bottom.addWidget(btn)
        layout.addLayout(bottom)

        self._populate()

    # ── Contenido ──
    def _populate(self):
        for date_dir in self._sorted_date_dirs():
            date_path = os.path.join(self.output_dir, date_dir)
            for session in self._sorted_sessions(date_path):
                full = os.path.join(date_path, session)
                self.list_widget.addItem(self._make_item(date_dir, session, full))

    def _sorted_date_dirs(self):
        try:
            entries = os.listdir(self.output_dir)
        except OSError:
            return []
        return sorted(
            (d for d in entries
             if state.DATE_DIR_RE.match(d)
             and os.path.isdir(os.path.join(self.output_dir, d))),
            reverse=True,
        )

    @staticmethod
    def _sorted_sessions(date_path):
        try:
            entries = os.listdir(date_path)
        except OSError:
            return []
        sessions = [s for s in entries
                    if state.SESSION_RE.match(s)
                    and os.path.isdir(os.path.join(date_path, s))]
        # Por numero de sesion, no alfabetico: si no, la 10 iria antes que la 9.
        sessions.sort(key=lambda s: int(state.SESSION_RE.match(s).group(1)), reverse=True)
        return sessions

    @classmethod
    def _make_item(cls, date_dir, session, full_path):
        header = f"{date_dir}  -  {session}"
        meta = cls._metadata(full_path)
        if meta:
            header += f"   ({meta})"
        preview = cls._load_preview(full_path)
        item = QListWidgetItem(header + (f"\n   {preview}" if preview else ""))
        item.setData(Qt.ItemDataRole.UserRole, full_path)
        return item

    @staticmethod
    def _load_preview(session_dir, max_chars=120):
        txt = os.path.join(session_dir, "transcripcion.txt")
        if not os.path.isfile(txt):
            return "(sin transcripcion.txt)"
        try:
            with open(txt, encoding="utf-8") as f:
                content = f.read(max_chars + 20).replace("\n", " ").strip()
        except OSError:
            return ""
        return content[:max_chars] + "..." if len(content) > max_chars else content

    @staticmethod
    def _metadata(session_dir):
        """Hora del audio, duracion estimada e indicador de subtitulos."""
        bits = []
        mp3 = os.path.join(session_dir, "audio.mp3")
        if os.path.isfile(mp3):
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(mp3))
                bits.append(mtime.strftime("%H:%M"))
                segundos = int(os.path.getsize(mp3) / BYTES_POR_SEGUNDO_MP3)
                if segundos > 0:
                    m, s = divmod(segundos, 60)
                    h, m = divmod(m, 60)
                    bits.append(f"{h}h{m:02d}m" if h else
                                (f"{m}m{s:02d}s" if m else f"{s}s"))
            except OSError:
                pass
        if os.path.isfile(os.path.join(session_dir, "transcripcion.srt")):
            bits.append(".srt")
        return " - ".join(bits)

    # ── Interaccion ──
    def _selected_path(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_double_click(self, item):
        self.selected_dir = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_load(self):
        path = self._selected_path()
        if path:
            self.selected_dir = path
            self.accept()

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        cargar = menu.addAction("Cargar en el editor")
        abrir = menu.addAction("Abrir carpeta")
        menu.addSeparator()
        borrar = menu.addAction("Borrar transcripcion...")
        elegido = menu.exec(self.list_widget.mapToGlobal(pos))

        if elegido == cargar:
            self.selected_dir = path
            self.accept()
        elif elegido == abrir:
            open_in_explorer(path)
        elif elegido == borrar:
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
        # Si la carpeta del dia quedo vacia, tambien se va.
        date_dir = os.path.dirname(path)
        try:
            if os.path.isdir(date_dir) and not os.listdir(date_dir):
                os.rmdir(date_dir)
        except OSError:
            pass
        self.list_widget.takeItem(self.list_widget.row(item))
