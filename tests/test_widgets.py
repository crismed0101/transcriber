import unittest

import widgets


class _BarraFalsa:
    """Doble de QProgressBar: solo lo que usa ProgressReporter."""

    def __init__(self):
        self.min = 0
        self.max = 100
        self.valor = 0
        self.formato = "%p%"
        self.visible = False
        self.texto_visible = True

    def setRange(self, a, b):
        self.min, self.max = a, b

    def maximum(self):
        return self.max

    def setValue(self, v):
        self.valor = v

    def setFormat(self, f):
        self.formato = f

    def setTextVisible(self, v):
        self.texto_visible = v

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class _BotonFalso:
    def __init__(self):
        self.visible = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def setVisible(self, v):
        self.visible = v


class ProgressReporterTest(unittest.TestCase):
    def setUp(self):
        self.barra = _BarraFalsa()
        self.boton = _BotonFalso()
        self.p = widgets.ProgressReporter(self.barra, self.boton)

    def test_arranca_oculto(self):
        self.assertFalse(self.barra.visible)
        self.assertFalse(self.boton.visible)

    # ── Modo indeterminado ──
    def test_busy_deja_la_barra_girando(self):
        self.p.busy()
        self.assertEqual(self.barra.max, 0)      # 0 = indeterminado en Qt
        self.assertFalse(self.barra.texto_visible)
        self.assertTrue(self.barra.visible)
        self.assertTrue(self.p.is_indeterminate)

    def test_busy_puede_no_ofrecer_cancelar(self):
        self.p.busy(cancelable=False)
        self.assertFalse(self.boton.visible)

    # ── Porcentaje ──
    def test_el_primer_porcentaje_sale_del_modo_indeterminado(self):
        self.p.busy()
        self.p.percent(30)
        self.assertFalse(self.p.is_indeterminate)
        self.assertEqual(self.barra.max, 100)
        self.assertEqual(self.barra.valor, 30)
        self.assertTrue(self.barra.texto_visible)

    def test_recorta_valores_fuera_de_rango(self):
        self.p.busy()
        self.p.percent(-5)
        self.assertEqual(self.barra.valor, 0)
        self.p.percent(150)
        self.assertEqual(self.barra.valor, 100)

    # ── Descarga ──
    def test_megabytes_muestra_lo_descargado_y_el_total(self):
        self.p.megabytes(120, 3000)
        self.assertEqual(self.barra.formato, "120 / 3000 MB")
        self.assertEqual(self.barra.valor, 4)
        self.assertTrue(self.barra.visible)

    def test_la_descarga_nunca_llega_a_cien(self):
        # El 100 lo marca el final real de la operacion, no el tamano estimado.
        self.p.megabytes(3000, 3000)
        self.assertEqual(self.barra.valor, 99)

    def test_un_total_desconocido_no_divide_por_cero(self):
        self.p.megabytes(10, 0)
        self.assertEqual(self.barra.valor, 99)

    def test_por_defecto_una_descarga_no_ofrece_cancelar(self):
        self.p.megabytes(10, 100)
        self.assertFalse(self.boton.visible)
        self.p.megabytes(10, 100, cancelable=True)
        self.assertTrue(self.boton.visible)

    # ── Restablecer ──
    def test_hide_deja_todo_listo_para_el_proximo_uso(self):
        self.p.megabytes(120, 3000, cancelable=True)
        self.p.hide()
        self.assertFalse(self.barra.visible)
        self.assertFalse(self.boton.visible)
        self.assertEqual(self.barra.formato, "%p%")
        self.assertEqual(self.barra.valor, 0)
        self.assertEqual(self.barra.max, 100)
        self.assertTrue(self.barra.texto_visible)

    def test_se_puede_reutilizar_despues_de_ocultar(self):
        self.p.megabytes(120, 3000)
        self.p.hide()
        self.p.busy()
        self.assertTrue(self.p.is_indeterminate)
        self.p.percent(50)
        self.assertEqual(self.barra.valor, 50)


class _EditorFalso:
    def __init__(self):
        self.texto = ""
        self.bloqueado = False
        self.cambios_notificados = 0

    def blockSignals(self, v):
        self.bloqueado = v

    def setPlainText(self, t):
        self.texto = t
        if not self.bloqueado:
            self.cambios_notificados += 1


class SetTextSilently(unittest.TestCase):
    def test_escribe_sin_notificar(self):
        # Si notificara, la app marcaria el texto como editado por el usuario.
        e = _EditorFalso()
        widgets.set_text_silently(e, "hola")
        self.assertEqual(e.texto, "hola")
        self.assertEqual(e.cambios_notificados, 0)

    def test_sin_argumento_vacia(self):
        e = _EditorFalso()
        e.texto = "algo"
        widgets.set_text_silently(e)
        self.assertEqual(e.texto, "")

    def test_desbloquea_aunque_falle(self):
        class Explota(_EditorFalso):
            def setPlainText(self, t):
                raise RuntimeError("boom")

        e = Explota()
        with self.assertRaises(RuntimeError):
            widgets.set_text_silently(e, "x")
        # Dejarlo bloqueado silenciaría al editor para siempre.
        self.assertFalse(e.bloqueado)


class _ComboFalso:
    def __init__(self, opciones):
        self.opciones = opciones
        self.indice = 0
        self.bloqueado = False
        self.cambios_notificados = 0

    def findText(self, t):
        return self.opciones.index(t) if t in self.opciones else -1

    def blockSignals(self, v):
        self.bloqueado = v

    def setCurrentIndex(self, i):
        self.indice = i
        if not self.bloqueado:
            self.cambios_notificados += 1


class SelectSilently(unittest.TestCase):
    def test_selecciona_sin_notificar(self):
        c = _ComboFalso(["a", "b", "c"])
        self.assertTrue(widgets.select_silently(c, "b"))
        self.assertEqual(c.indice, 1)
        self.assertEqual(c.cambios_notificados, 0)

    def test_una_opcion_inexistente_no_cambia_nada(self):
        c = _ComboFalso(["a", "b"])
        self.assertFalse(widgets.select_silently(c, "z"))
        self.assertEqual(c.indice, 0)


if __name__ == "__main__":
    unittest.main()
