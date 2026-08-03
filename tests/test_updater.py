import io
import os
import json
import hashlib
import tempfile
import unittest
from unittest import mock

import updater


class _FakeResponse(io.BytesIO):
    """Respuesta HTTP mínima, usable como context manager."""

    def __init__(self, payload, headers=None):
        super().__init__(payload if isinstance(payload, bytes) else payload.encode())
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _release(tag="v2.0.0", with_installer=True, with_sha=True, notes="Novedades"):
    assets = []
    if with_installer:
        assets.append({
            "name": "Transcriber-Setup-v2.0.0-windows-x64.exe",
            "browser_download_url": "https://example.test/setup.exe",
            "size": 1024,
        })
    if with_sha:
        assets.append({
            "name": "Transcriber-Setup-v2.0.0-windows-x64.exe.sha256",
            "browser_download_url": "https://example.test/setup.exe.sha256",
            "size": 80,
        })
    return json.dumps({"tag_name": tag, "body": notes, "assets": assets})


class ParseVersion(unittest.TestCase):
    def test_formato_normal(self):
        self.assertEqual(updater.parse_version("1.2.3"), (1, 2, 3))

    def test_prefijo_v(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("V1.2.3"), (1, 2, 3))

    def test_sufijos_no_numericos_se_cortan(self):
        self.assertEqual(updater.parse_version("1.2.3-beta1"), (1, 2, 3))

    def test_entradas_invalidas(self):
        for entrada in ("", None, "abc", "vv"):
            self.assertEqual(updater.parse_version(entrada), (), repr(entrada))


class IsNewer(unittest.TestCase):
    def test_version_posterior(self):
        self.assertTrue(updater.is_newer("1.2.0", "1.1.0"))

    def test_compara_numerico_no_alfabetico(self):
        # El bug clasico: como texto, "1.10.0" < "1.9.0".
        self.assertTrue(updater.is_newer("1.10.0", "1.9.0"))
        self.assertFalse(updater.is_newer("1.9.0", "1.10.0"))

    def test_misma_version_no_actualiza(self):
        self.assertFalse(updater.is_newer("1.1.0", "1.1.0"))
        self.assertFalse(updater.is_newer("v1.1.0", "1.1.0"))

    def test_no_actualiza_hacia_atras(self):
        self.assertFalse(updater.is_newer("1.0.0", "1.1.0"))

    def test_longitudes_distintas(self):
        self.assertFalse(updater.is_newer("1.1", "1.1.0"))
        self.assertTrue(updater.is_newer("1.1.1", "1.1"))

    def test_version_ilegible_nunca_dispara_actualizacion(self):
        self.assertFalse(updater.is_newer("", "1.0.0"))
        self.assertFalse(updater.is_newer("latest", "1.0.0"))


class CheckForUpdate(unittest.TestCase):
    def _check(self, payload, current="1.1.0"):
        with mock.patch.object(updater, "_get", return_value=_FakeResponse(payload)):
            return updater.check_for_update(current_version=current, repo="x/y")

    def test_detecta_version_nueva(self):
        info = self._check(_release("v2.0.0"))
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "2.0.0")
        self.assertEqual(info.tag, "v2.0.0")
        self.assertTrue(info.installer_url.endswith("setup.exe"))
        self.assertTrue(info.sha256_url.endswith(".sha256"))

    def test_no_avisa_si_esta_al_dia(self):
        self.assertIsNone(self._check(_release("v1.1.0")))

    def test_no_avisa_si_lo_publicado_es_mas_viejo(self):
        self.assertIsNone(self._check(_release("v1.0.0")))

    def test_ignora_releases_sin_instalador(self):
        self.assertIsNone(self._check(_release("v2.0.0", with_installer=False)))

    def test_sin_sha256_igual_informa_pero_sin_url(self):
        # La descarga fallara despues; lo que importa es no reventar aca.
        info = self._check(_release("v2.0.0", with_sha=False))
        self.assertIsNotNone(info)
        self.assertIsNone(info.sha256_url)

    def test_sin_internet_devuelve_none_sin_lanzar(self):
        with mock.patch.object(updater, "_get", side_effect=OSError("sin red")):
            self.assertIsNone(updater.check_for_update("1.1.0", repo="x/y"))

    def test_respuesta_corrupta_devuelve_none(self):
        with mock.patch.object(updater, "_get", return_value=_FakeResponse("{no es json")):
            self.assertIsNone(updater.check_for_update("1.1.0", repo="x/y"))


class VerifyChecksum(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="checksum-")
        self.path = os.path.join(self.dir, "instalador.exe")
        self.contenido = b"contenido del instalador"
        with open(self.path, "wb") as f:
            f.write(self.contenido)
        self.hash = hashlib.sha256(self.contenido).hexdigest()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_acepta_el_hash_correcto(self):
        self.assertTrue(updater.verify_checksum(self.path, self.hash))
        self.assertTrue(os.path.isfile(self.path))

    def test_acepta_el_formato_de_sha256sum(self):
        # build.py escribe "<hash>  <nombre>", como sha256sum.
        self.assertTrue(updater.verify_checksum(self.path, f"{self.hash}  instalador.exe\n"))

    def test_no_distingue_mayusculas(self):
        self.assertTrue(updater.verify_checksum(self.path, self.hash.upper()))

    def test_rechaza_un_archivo_alterado_y_LO_BORRA(self):
        # Es la garantia central: el instalador no esta firmado, asi que un
        # archivo que no verifica no puede quedar en disco listo para ejecutarse.
        with self.assertRaises(updater.UpdateError):
            updater.verify_checksum(self.path, "0" * 64)
        self.assertFalse(os.path.exists(self.path))

    def test_sin_hash_esperado_falla_y_conserva_el_archivo(self):
        with self.assertRaises(updater.UpdateError):
            updater.verify_checksum(self.path, "")
        # No se borra: el problema es del release, no del archivo descargado.
        self.assertTrue(os.path.isfile(self.path))


class DownloadInstaller(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="descarga-")
        self.contenido = b"x" * 4096
        self.hash = hashlib.sha256(self.contenido).hexdigest()
        self.info = updater.UpdateInfo(
            version="2.0.0", tag="v2.0.0", notes="",
            installer_url="https://example.test/setup.exe",
            installer_name="setup.exe", size=len(self.contenido),
            sha256_url="https://example.test/setup.exe.sha256",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _respuestas(self, hash_publicado):
        return [
            _FakeResponse(self.contenido, {"Content-Length": str(len(self.contenido))}),
            _FakeResponse(f"{hash_publicado}  setup.exe\n"),
        ]

    def test_descarga_verifica_y_reporta_progreso(self):
        vistos = []
        with mock.patch.object(updater, "_get", side_effect=self._respuestas(self.hash)):
            path = updater.download_installer(
                self.info, dest_dir=self.dir,
                on_progress=lambda d, t: vistos.append((d, t)),
            )
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(vistos[-1], (len(self.contenido), len(self.contenido)))

    def test_un_hash_que_no_coincide_aborta_y_borra(self):
        with mock.patch.object(updater, "_get", side_effect=self._respuestas("0" * 64)):
            with self.assertRaises(updater.UpdateError):
                updater.download_installer(self.info, dest_dir=self.dir)
        self.assertEqual(os.listdir(self.dir), [])

    def test_cancelar_borra_la_descarga_parcial(self):
        with mock.patch.object(updater, "_get", side_effect=self._respuestas(self.hash)):
            with self.assertRaises(updater.UpdateCancelled):
                updater.download_installer(
                    self.info, dest_dir=self.dir, should_cancel=lambda: True
                )
        self.assertEqual(os.listdir(self.dir), [])

    def test_error_de_red_no_deja_basura(self):
        with mock.patch.object(updater, "_get", side_effect=OSError("cortado")):
            with self.assertRaises(updater.UpdateError):
                updater.download_installer(self.info, dest_dir=self.dir)
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
