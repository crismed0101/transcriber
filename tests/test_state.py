import os
import shutil
import tempfile
import unittest

import state


class SessionNumbering(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sesiones-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _mkdir(self, name):
        os.makedirs(os.path.join(self.dir, name), exist_ok=True)

    def test_carpeta_vacia_empieza_en_uno(self):
        self.assertEqual(state.next_session_number(self.dir), 1)

    def test_continua_despues_de_la_ultima(self):
        self._mkdir("transcripcion-1")
        self._mkdir("transcripcion-2")
        self.assertEqual(state.next_session_number(self.dir), 3)

    def test_cuenta_las_renombradas_por_el_usuario(self):
        self._mkdir("transcripcion-1 (reunion de equipo)")
        self.assertEqual(state.next_session_number(self.dir), 2)

    def test_no_reutiliza_numeros_si_hay_huecos(self):
        # Borrar la 2 no debe hacer que la proxima pise a la 3.
        self._mkdir("transcripcion-1")
        self._mkdir("transcripcion-3")
        self.assertEqual(state.next_session_number(self.dir), 4)

    def test_ignora_carpetas_ajenas(self):
        self._mkdir("otra-cosa")
        self._mkdir("transcripcion-sin-numero")
        self.assertEqual(state.next_session_number(self.dir), 1)

    def test_ignora_archivos_con_nombre_de_sesion(self):
        with open(os.path.join(self.dir, "transcripcion-9"), "w") as f:
            f.write("no soy una carpeta")
        self.assertEqual(state.next_session_number(self.dir), 1)

    def test_carpeta_inexistente_no_revienta(self):
        self.assertEqual(state.next_session_number(os.path.join(self.dir, "nada")), 1)

    def test_numeros_de_dos_digitos(self):
        self._mkdir("transcripcion-9")
        self._mkdir("transcripcion-10")
        self.assertEqual(state.next_session_number(self.dir), 11)


class SessionHasContent(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sesion-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _touch(self, name):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write("x")

    def test_carpeta_vacia_no_tiene_contenido(self):
        self.assertFalse(state.session_has_content(self.dir))

    def test_el_wav_crudo_no_cuenta_como_contenido(self):
        # Es un intermedio: si solo queda eso, la sesion se descarta.
        self._touch("_raw.wav")
        self.assertFalse(state.session_has_content(self.dir))

    def test_el_mp3_cuenta(self):
        self._touch("audio.mp3")
        self.assertTrue(state.session_has_content(self.dir))

    def test_la_transcripcion_cuenta(self):
        self._touch("transcripcion.txt")
        self.assertTrue(state.session_has_content(self.dir))

    def test_el_srt_cuenta(self):
        self._touch("transcripcion.srt")
        self.assertTrue(state.session_has_content(self.dir))

    def test_carpeta_inexistente(self):
        self.assertFalse(state.session_has_content(os.path.join(self.dir, "nada")))


class OldSessionPattern(unittest.TestCase):
    def test_reconoce_los_nombres_viejos(self):
        for nombre in ("archivo_20250131_101500", "grabacion_20240229_235959"):
            with self.subTest(nombre=nombre):
                self.assertIsNotNone(state._OLD_SESSION_RE.match(nombre))

    def test_extrae_la_fecha(self):
        m = state._OLD_SESSION_RE.match("grabacion_20250131_101500")
        self.assertEqual(m.group(2, 3, 4), ("2025", "01", "31"))

    def test_no_matchea_el_formato_nuevo(self):
        self.assertIsNone(state._OLD_SESSION_RE.match("transcripcion-1"))


class ModelCacheCleanup(unittest.TestCase):
    """La limpieza solo puede tocar el directorio propio de la app."""

    def setUp(self):
        self.models = tempfile.mkdtemp(prefix="modelos-")
        self.addCleanup(shutil.rmtree, self.models, ignore_errors=True)
        self._orig_models_dir = state.paths.models_dir
        state.paths.models_dir = lambda: self.models
        self.addCleanup(setattr, state.paths, "models_dir", self._orig_models_dir)

    def _mkmodel(self, name):
        path = os.path.join(self.models, name)
        os.makedirs(path, exist_ok=True)
        return path

    def test_conserva_el_modelo_activo(self):
        activo = self._mkmodel("models--Systran--faster-whisper-small")
        state.cleanup_model_cache("small")
        self.assertTrue(os.path.isdir(activo))

    def test_borra_otros_modelos_whisper(self):
        self._mkmodel("models--Systran--faster-whisper-small")
        viejo = self._mkmodel("models--Systran--faster-whisper-large-v3")
        state.cleanup_model_cache("small")
        self.assertFalse(os.path.isdir(viejo))

    def test_no_toca_modelos_que_no_son_whisper(self):
        ajeno = self._mkmodel("models--sentence-transformers--all-MiniLM-L6-v2")
        state.cleanup_model_cache("small")
        self.assertTrue(os.path.isdir(ajeno))

    def test_no_toca_archivos_sueltos(self):
        suelto = os.path.join(self.models, "version.txt")
        with open(suelto, "w") as f:
            f.write("1")
        state.cleanup_model_cache("small")
        self.assertTrue(os.path.isfile(suelto))


if __name__ == "__main__":
    unittest.main()
