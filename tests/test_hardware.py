import unittest
from unittest import mock

import hardware


class RecommendModel(unittest.TestCase):
    def test_gpu_grande_usa_el_modelo_mas_capaz(self):
        self.assertEqual(hardware.recommend_model(cuda=True, vram_gb=12), "large-v3")

    def test_gpu_baja_de_escalon_segun_vram(self):
        casos = [(5.0, "large-v3"), (4.0, "medium"), (3.0, "medium"),
                 (2.5, "small"), (2.0, "small"), (1.0, "base"), (0.5, "tiny")]
        for vram, esperado in casos:
            with self.subTest(vram=vram):
                self.assertEqual(hardware.recommend_model(cuda=True, vram_gb=vram), esperado)

    def test_cuda_sin_vram_medible_confia_en_la_gpu(self):
        # nvidia-smi ausente o mudo: no degradamos a ciegas.
        with mock.patch.object(hardware, "gpu_info",
                               return_value=hardware._NO_GPU._replace(present=True)):
            self.assertEqual(hardware.recommend_model(cuda=True), "large-v3")

    def test_cpu_nunca_elige_modelos_pesados(self):
        # medium y large en CPU tardarian horas: es una decision de producto.
        for ram in (8, 16, 32, 128):
            with self.subTest(ram=ram):
                self.assertIn(hardware.recommend_model(cuda=False, ram_gb=ram),
                              ("small", "base", "tiny"))

    def test_cpu_escala_con_la_ram(self):
        self.assertEqual(hardware.recommend_model(cuda=False, ram_gb=16), "small")
        self.assertEqual(hardware.recommend_model(cuda=False, ram_gb=8), "base")
        self.assertEqual(hardware.recommend_model(cuda=False, ram_gb=4), "tiny")


class ComputeType(unittest.TestCase):
    def test_gpu_usa_float16(self):
        # int8 esta deshabilitado en Blackwell desde ctranslate2 4.6.2.
        self.assertEqual(hardware.compute_type_for("cuda"), "float16")

    def test_cpu_usa_int8(self):
        self.assertEqual(hardware.compute_type_for("cpu"), "int8")


class EngineCandidates(unittest.TestCase):
    def _candidatos(self, cuda, preferido=None, vram=12.0, ram=16.0):
        info = hardware._NO_GPU._replace(present=cuda, vram_gb=vram)
        with mock.patch.object(hardware, "cuda_available", return_value=cuda), \
             mock.patch.object(hardware, "gpu_info", return_value=info), \
             mock.patch.object(hardware, "total_ram_gb", return_value=ram):
            return hardware.engine_candidates(preferido)

    def test_sin_cuda_solo_propone_cpu(self):
        cands = self._candidatos(cuda=False)
        self.assertTrue(all(device == "cpu" for _, device, _ in cands))

    def test_con_cuda_prueba_gpu_antes_que_cpu(self):
        cands = self._candidatos(cuda=True)
        devices = [d for _, d, _ in cands]
        self.assertEqual(devices[0], "cuda")
        self.assertIn("cpu", devices)
        # Toda la GPU se agota antes de pasar a CPU.
        self.assertEqual(devices, sorted(devices, key=lambda d: d != "cuda"))

    def test_la_red_de_contencion_en_cpu_no_arrastra_el_modelo_de_gpu(self):
        # Si la GPU falla, correr large-v3 en CPU seria una espera de horas.
        cands = self._candidatos(cuda=True, preferido="large-v3")
        cpu = [m for m, d, _ in cands if d == "cpu"]
        self.assertNotIn("large-v3", cpu)
        self.assertNotIn("medium", cpu)

    def test_degrada_bajando_por_la_escalera(self):
        modelos = [m for m, d, _ in self._candidatos(cuda=True, preferido="medium")
                   if d == "cuda"]
        self.assertEqual(modelos, ["medium", "small", "base", "tiny"])

    def test_respeta_el_modelo_elegido_a_mano_en_cpu(self):
        modelos = [m for m, _, _ in self._candidatos(cuda=False, preferido="base")]
        self.assertEqual(modelos[0], "base")

    def test_un_modelo_desconocido_se_prueba_primero(self):
        cands = self._candidatos(cuda=False, preferido="distil-large-v3")
        self.assertEqual(cands[0][0], "distil-large-v3")
        # Y despues quedan las opciones conocidas como respaldo.
        self.assertIn("tiny", [m for m, _, _ in cands])

    def test_no_hay_candidatos_repetidos(self):
        cands = self._candidatos(cuda=True)
        self.assertEqual(len(cands), len(set(cands)))

    def test_siempre_termina_en_la_opcion_mas_liviana(self):
        cands = self._candidatos(cuda=True)
        self.assertEqual(cands[-1], ("tiny", "cpu", "int8"))


class ShortGpuName(unittest.TestCase):
    def test_recorta_el_prefijo_del_fabricante(self):
        self.assertEqual(hardware.short_gpu_name("NVIDIA GeForce RTX 5070"), "RTX 5070")

    def test_no_parte_los_modelos_rtx_a(self):
        # 'RTX' matcheaba antes que 'RTX A' y cortaba mal el nombre.
        self.assertEqual(hardware.short_gpu_name("NVIDIA RTX A4000"), "RTX A4000")

    def test_deja_intacto_lo_que_no_reconoce(self):
        self.assertEqual(hardware.short_gpu_name("Radeon RX 7900"), "Radeon RX 7900")

    def test_nombre_vacio(self):
        self.assertEqual(hardware.short_gpu_name(""), "")


class DriverTooOld(unittest.TestCase):
    def _con_gpu(self, compute_cap, driver):
        return hardware._NO_GPU._replace(
            present=True, compute_cap=compute_cap, driver_version=driver
        )

    def test_blackwell_con_driver_viejo(self):
        with mock.patch.object(hardware, "gpu_info",
                               return_value=self._con_gpu("12.0", "552.22")):
            self.assertTrue(hardware.driver_too_old())

    def test_blackwell_con_driver_al_dia(self):
        with mock.patch.object(hardware, "gpu_info",
                               return_value=self._con_gpu("12.0", "610.74")):
            self.assertFalse(hardware.driver_too_old())

    def test_gpu_anterior_no_le_aplica_el_minimo(self):
        with mock.patch.object(hardware, "gpu_info",
                               return_value=self._con_gpu("8.9", "530.00")):
            self.assertFalse(hardware.driver_too_old())

    def test_sin_gpu(self):
        with mock.patch.object(hardware, "gpu_info", return_value=hardware._NO_GPU):
            self.assertFalse(hardware.driver_too_old())

    def test_datos_incompletos_no_bloquean(self):
        # Sin compute_cap no podemos afirmar que sea Blackwell: no degradamos.
        with mock.patch.object(hardware, "gpu_info",
                               return_value=self._con_gpu("", "400.00")):
            self.assertFalse(hardware.driver_too_old())


class Ladder(unittest.TestCase):
    def test_la_escalera_va_de_mayor_a_menor(self):
        vram = [v for _, v, _, _ in hardware.MODEL_LADDER]
        self.assertEqual(vram, sorted(vram, reverse=True))

    def test_hay_tamano_declarado_para_cada_modelo(self):
        self.assertEqual(set(hardware.MODEL_SIZES_MB), set(hardware.MODEL_NAMES))


if __name__ == "__main__":
    unittest.main()
