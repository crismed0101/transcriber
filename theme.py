"""Apariencia de la aplicacion: paleta, hojas de estilo e iconos.

Presentacion pura. No contiene logica de la app, asi que se puede ajustar el aspecto
sin tocar nada de lo que hace el programa.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

import version
from utils import resource_path

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

C_SELECTION = "#264f78"

# ── Hoja de estilo global ──
STYLE = f"""
QMainWindow {{ background-color: {C_BG}; }}
QWidget {{ background-color: transparent; }}
QLabel {{ color: {C_TEXT_DIM}; font-size: 12px; }}

QTextEdit {{
    background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 12px; padding: 14px; font-family: 'Segoe UI', Consolas; font-size: 13px;
    selection-background-color: {C_SELECTION};
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
    selection-background-color: {C_SELECTION}; padding: 4px; outline: 0;
}}

QProgressBar {{
    background-color: {C_SURFACE}; border: 1px solid {C_BORDER}; border-radius: 6px;
    height: 12px; text-align: center; font-size: 10px; color: {C_TEXT_DIM};
}}
QProgressBar::chunk {{ background-color: {C_GREEN}; border-radius: 5px; }}

QMenu {{ background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER_HI}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {C_SELECTION}; }}
QMenu::separator {{ height: 1px; background: {C_BORDER_HI}; margin: 4px 6px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {C_BORDER_HI}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C_GRAY_HI}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QToolTip {{
    background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER_HI};
    padding: 4px 8px; border-radius: 6px;
}}

QListWidget {{
    background-color: {C_SURFACE}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 8px; padding: 4px;
}}
QListWidget::item {{ padding: 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background-color: {C_SELECTION}; }}
QListWidget::item:hover {{ background-color: {C_BORDER_HI}; }}
"""


# ── Generadores de estilo para botones ──
def btn_style(bg, hover_bg, height=34, radius=18, font_size=12, color="white"):
    """Boton solido con color de fondo y su variante al pasar el mouse."""
    return (
        f"QPushButton {{ background-color: {bg}; color: {color}; border: none; "
        f"border-radius: {radius}px; padding: 0 18px; font-weight: bold; font-size: {font_size}px; "
        f"min-height: {height}px; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; }}"
        f"QPushButton:pressed {{ background-color: {bg}; }}"
    )


def btn_disabled(height=34, radius=18, font_size=12):
    """Boton apagado: mismo tamano que el activo para que nada se mueva."""
    return (
        f"QPushButton {{ background-color: {C_SURFACE}; color: {C_BORDER_HI}; border: none; "
        f"border-radius: {radius}px; padding: 0 18px; font-weight: bold; font-size: {font_size}px; "
        f"min-height: {height}px; }}"
    )


def btn_outline(border, hover_border, color, height=32, radius=10, font_size=12):
    """Boton secundario: solo contorno, sin relleno."""
    return (
        f"QPushButton {{ background-color: transparent; color: {color}; border: 1px solid {border}; "
        f"border-radius: {radius}px; padding: 0 14px; font-weight: 600; font-size: {font_size}px; "
        f"min-height: {height}px; }}"
        f"QPushButton:hover {{ border-color: {hover_border}; color: {C_TEXT}; }}"
    )


# ── Estilos ya resueltos ──
S_REC = btn_style(C_RED, C_RED_HI, height=44, radius=22, font_size=13)
S_REC_OFF = btn_style(C_GRAY, C_GRAY_HI, height=44, radius=22, font_size=13)
S_REC_DISABLED = btn_disabled(height=44, radius=22, font_size=13)
S_PAUSE = btn_style(C_AMBER, C_AMBER_HI)
S_RESUME = btn_style(C_GREEN, C_GREEN_HI)
S_STOP = btn_style(C_RED, C_RED_HI)
S_UPLOAD = btn_style(C_BLUE, C_BLUE_HI)
S_BTN_DISABLED = btn_disabled()

S_OPEN = btn_style(C_GREEN, C_GREEN_HI, height=30, radius=10, font_size=11)
S_COPY = btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_DIM, height=30, radius=10, font_size=11)
S_FOLDER = btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_MUTED, height=30, radius=10, font_size=11)
S_OPEN_DISABLED = btn_disabled(height=30, radius=10, font_size=11)
S_COPY_DISABLED = btn_disabled(height=30, radius=10, font_size=11)
S_CANCEL = btn_outline(C_RED, C_RED_HI, C_RED_HI, height=24, radius=8, font_size=10)
S_DIALOG_OK = btn_style(C_GREEN, C_GREEN_HI, height=30, radius=8, font_size=11)
S_DIALOG_CLOSE = btn_outline(C_BORDER, C_BORDER_HI, C_TEXT_DIM, height=30, radius=8, font_size=11)

# Etiquetas redondeadas de estado
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


# ── Iconografia ──
def _draw_logo(painter, x, y, size, font_size):
    """Circulo rojo con la inicial. Es el logo, en cualquier tamano."""
    painter.setBrush(QColor(C_RED))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(x, y, size, size)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Arial", font_size, QFont.Weight.Bold))
    painter.drawText(x, y, size, size, Qt.AlignmentFlag.AlignCenter, version.APP_NAME[0])


def make_logo_pixmap(size=22):
    """Logo suelto, para la barra de titulo de la ventana."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_logo(p, 0, 0, size, int(size * 0.5))
    p.end()
    return pm


def make_app_icon():
    """Icono de la aplicacion: icon.ico si esta, o uno dibujado al vuelo."""
    ico_path = resource_path("icon.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)

    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        icon.addPixmap(make_logo_pixmap(size))
    return icon


def make_splash_pixmap():
    """Pantalla de bienvenida (380x220, tema oscuro)."""
    pm = QPixmap(380, 220)
    pm.fill(QColor(C_BG))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    p.setPen(QColor(C_BORDER))
    p.drawRoundedRect(0, 0, 379, 219, 12, 12)

    radio = 32
    _draw_logo(p, 190 - radio, 80 - radio, radio * 2, 28)

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
