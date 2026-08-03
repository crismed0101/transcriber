import os
import shutil
import tempfile
import unittest
from unittest import mock

import build


class LimiteDeTamano(unittest.TestCase):
    """GitHub rechaza archivos de mas de 2 GiB adjuntos a un release."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="build-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "Transcriber-Setup.exe")
        with open(self.path, "wb") as f:
            f.write(b"x" * 1024)

    def test_el_limite_es_dos_gibibytes(self):
        self.assertEqual(build.GITHUB_ASSET_LIMIT, 2 * 1024 ** 3)

    def test_acepta_un_instalador_normal(self):
        # El instalador real pesa ~1,5 GB: entra con margen.
        with mock.patch.object(os.path, "getsize", return_value=int(1.5 * 1024 ** 3)):
            build.check_publishable(self.path)

    def test_rechaza_uno_que_no_se_podria_subir(self):
        # Mejor un mensaje claro antes de empezar que una subida que muere a la hora.
        with mock.patch.object(os.path, "getsize", return_value=3 * 1024 ** 3):
            with self.assertRaises(build.BuildError) as ctx:
                build.check_publishable(self.path)
        self.assertIn("GiB", str(ctx.exception))

    def test_el_limite_exacto_pasa(self):
        with mock.patch.object(os.path, "getsize", return_value=build.GITHUB_ASSET_LIMIT):
            build.check_publishable(self.path)


class AutenticacionParaPublicar(unittest.TestCase):
    """Se comprueba la autenticacion real, no la variable de entorno.

    En una PC ya autenticada con `gh auth login` no hay ninguna variable definida, y
    mirar solo el entorno daria un falso negativo.
    """

    def _resultado(self, returncode):
        return mock.Mock(returncode=returncode, stdout="", stderr="")

    def test_pasa_si_gh_esta_autenticado(self):
        with mock.patch.object(build.subprocess, "run", return_value=self._resultado(0)):
            build.check_gh_auth()

    def test_falla_con_instrucciones_si_no_lo_esta(self):
        with mock.patch.object(build.subprocess, "run", return_value=self._resultado(1)):
            with self.assertRaises(build.BuildError) as ctx:
                build.check_gh_auth()
        mensaje = str(ctx.exception)
        # El mensaje tiene que servir tanto en tu PC como en GitHub Actions.
        self.assertIn("gh auth login", mensaje)
        self.assertIn("GH_TOKEN", mensaje)

    def test_falla_claro_si_gh_no_esta_instalado(self):
        with mock.patch.object(build.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(build.BuildError) as ctx:
                build.check_gh_auth()
        self.assertIn("GitHub.cli", str(ctx.exception))


class FrescuraDelArtefacto(unittest.TestCase):
    """Nunca publicar algo compilado en una corrida anterior."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fresco-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "Transcriber.exe")
        with open(self.path, "wb") as f:
            f.write(b"x")

    def test_acepta_lo_recien_generado(self):
        build.assert_fresh(self.path, os.path.getmtime(self.path) - 1, "el ejecutable")

    def test_rechaza_lo_viejo(self):
        futuro = os.path.getmtime(self.path) + 3600
        with self.assertRaises(build.BuildError) as ctx:
            build.assert_fresh(self.path, futuro, "el ejecutable")
        self.assertIn("ANTERIOR", str(ctx.exception))

    def test_rechaza_lo_que_no_existe(self):
        with self.assertRaises(build.BuildError):
            build.assert_fresh(os.path.join(self.dir, "nada.exe"), 0, "el ejecutable")


if __name__ == "__main__":
    unittest.main()
