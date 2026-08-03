import os
import unittest

import utils


class SamePath(unittest.TestCase):
    def test_rutas_identicas(self):
        self.assertTrue(utils.same_path("/a/b", "/a/b"))

    def test_normaliza_separadores_redundantes(self):
        self.assertTrue(utils.same_path("/a//b/", "/a/b"))

    def test_normaliza_punto(self):
        self.assertTrue(utils.same_path("/a/./b", "/a/b"))

    def test_rutas_distintas(self):
        self.assertFalse(utils.same_path("/a/b", "/a/c"))

    @unittest.skipUnless(os.name == "nt", "el case-insensitive solo aplica en Windows")
    def test_ignora_mayusculas_en_windows(self):
        self.assertTrue(utils.same_path(r"C:\Users\Test", r"c:\users\test"))


class SanitizeFolderName(unittest.TestCase):
    def test_texto_normal_pasa_igual(self):
        self.assertEqual(utils.sanitize_folder_name("Reunion equipo"), "Reunion equipo")

    def test_quita_caracteres_invalidos_de_windows(self):
        self.assertEqual(utils.sanitize_folder_name('a\\b/c:d*e?f"g<h>i|j'), "abcdefghij")

    def test_no_termina_en_punto_ni_espacio(self):
        # Windows rechaza esos nombres al crear la carpeta.
        self.assertEqual(utils.sanitize_folder_name("informe..."), "informe")
        self.assertEqual(utils.sanitize_folder_name("informe   "), "informe")

    def test_recorta_al_maximo(self):
        self.assertEqual(len(utils.sanitize_folder_name("x" * 200)), 60)

    def test_respeta_el_maximo_configurable(self):
        self.assertEqual(utils.sanitize_folder_name("x" * 50, max_len=10), "x" * 10)

    def test_devuelve_none_si_queda_vacio(self):
        for entrada in ("", "   ", None, '???', "..."):
            self.assertIsNone(utils.sanitize_folder_name(entrada), entrada)

    def test_conserva_acentos_y_enie(self):
        self.assertEqual(utils.sanitize_folder_name("Reunión Añejo"), "Reunión Añejo")


class ResourcePath(unittest.TestCase):
    def test_devuelve_ruta_existente_del_proyecto(self):
        # icon.ico vive junto al codigo, asi que debe resolverse.
        self.assertTrue(os.path.exists(utils.resource_path("icon.ico")))

    def test_inexistente_devuelve_ruta_canonica_sin_romper(self):
        out = utils.resource_path("no-existe-jamas.bin")
        self.assertTrue(out.endswith("no-existe-jamas.bin"))


if __name__ == "__main__":
    unittest.main()
