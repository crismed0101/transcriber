"""Piezas de interfaz reutilizables.

Existen para que ningun otro modulo tenga que recordar la secuencia exacta de
llamadas de Qt para lograr un efecto: se pide el efecto y listo.
"""

MB = 1024 * 1024


def set_text_silently(editor, text=""):
    """Cambia el contenido de un editor SIN disparar textChanged.

    La app usa esa senal para saber si el usuario edito el texto a mano. Al
    escribir por codigo (resultado de la transcripcion, avance parcial, cargar una
    sesion) hay que silenciarla o todo quedaria marcado como "modificado".
    """
    editor.blockSignals(True)
    try:
        editor.setPlainText(text)
    finally:
        editor.blockSignals(False)


def select_silently(combo, text):
    """Selecciona una opcion sin disparar currentTextChanged. True si existia."""
    idx = combo.findText(text)
    if idx < 0:
        return False
    combo.blockSignals(True)
    try:
        combo.setCurrentIndex(idx)
    finally:
        combo.blockSignals(False)
    return True


class ProgressReporter:
    """Dueno unico de la barra de progreso y del boton Cancelar.

    La barra sirve para cuatro cosas distintas -esperar sin saber cuanto, descargar
    un modelo, descargar una actualizacion y transcribir- y antes cada una armaba su
    combinacion de setRange/setFormat/setTextVisible en el lugar donde hacia falta.
    Once metodos la manipulaban y ninguno era responsable de su estado.

    Aca cada modo es una llamada, y `hide()` siempre deja todo como al principio.
    """

    def __init__(self, bar, cancel_button):
        self._bar = bar
        self._cancel = cancel_button
        self.hide()

    @property
    def is_indeterminate(self):
        """True si esta girando sin avance real todavia."""
        return self._bar.maximum() == 0

    def busy(self, cancelable=True):
        """Modo indeterminado: arranco algo que todavia no informa avance."""
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._reveal(cancelable)

    def percent(self, pct):
        """Avance conocido, en porcentaje."""
        if self.is_indeterminate:
            # Primer avance real: se sale del modo indeterminado.
            self._bar.setRange(0, 100)
            self._bar.setTextVisible(True)
            self._bar.setFormat("%p%")
        self._bar.setValue(max(0, min(int(pct), 100)))

    def megabytes(self, done_mb, total_mb, cancelable=False):
        """Descarga en curso, mostrada como '120 / 3000 MB'."""
        total_mb = max(1, int(total_mb))
        done_mb = max(0, int(done_mb))
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(True)
        self._bar.setFormat(f"{done_mb} / {total_mb} MB")
        # Se topa en 99 porque el 100 lo marca el final real de la operacion, no el
        # tamano estimado del archivo.
        self._bar.setValue(min(int(done_mb / total_mb * 100), 99))
        self._reveal(cancelable)

    def hide(self):
        """Oculta todo y restablece el formato para el proximo uso."""
        self._bar.hide()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("%p%")
        self._bar.setTextVisible(True)
        self._cancel.hide()

    def _reveal(self, cancelable):
        self._bar.show()
        self._cancel.setVisible(cancelable)
