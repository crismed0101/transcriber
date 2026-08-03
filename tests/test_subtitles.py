import unittest

import subtitles


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class FormatSrtTimestamp(unittest.TestCase):
    def test_cero(self):
        self.assertEqual(subtitles.format_srt_timestamp(0), "00:00:00,000")

    def test_milisegundos(self):
        self.assertEqual(subtitles.format_srt_timestamp(1.234), "00:00:01,234")

    def test_horas_minutos_segundos(self):
        self.assertEqual(subtitles.format_srt_timestamp(3661.5), "01:01:01,500")

    def test_negativo_se_recorta_a_cero(self):
        # Whisper puede devolver un start levemente negativo con speech_pad_ms.
        self.assertEqual(subtitles.format_srt_timestamp(-2.5), "00:00:00,000")

    def test_redondeo_no_desborda_a_1000_ms(self):
        # 0.9999 redondea a 1000 ms, que no es representable en SRT.
        self.assertEqual(subtitles.format_srt_timestamp(0.9999), "00:00:00,999")

    def test_mas_de_diez_horas(self):
        self.assertEqual(subtitles.format_srt_timestamp(36000), "10:00:00,000")


class BuildSrt(unittest.TestCase):
    def test_numera_desde_uno_y_separa_con_linea_vacia(self):
        out = subtitles.build_srt([seg(0, 1.5, " Hola "), seg(1.5, 3, "Mundo")])
        self.assertEqual(out.split("\n"), [
            "1",
            "00:00:00,000 --> 00:00:01,500",
            "Hola",
            "",
            "2",
            "00:00:01,500 --> 00:00:03,000",
            "Mundo",
            "",
        ])

    def test_sin_segmentos_da_cadena_vacia(self):
        self.assertEqual(subtitles.build_srt([]), "")


class FormatSegmentsWithTimestamps(unittest.TestCase):
    def test_usa_mm_ss_en_audios_cortos(self):
        out = subtitles.format_segments_with_timestamps([seg(5, 8, "Hola")])
        self.assertEqual(out, "[00:05] Hola")

    def test_pasa_a_hh_mm_ss_si_supera_una_hora(self):
        out = subtitles.format_segments_with_timestamps([
            seg(5, 8, "Inicio"),
            seg(3600, 3605, "Final"),
        ])
        self.assertEqual(out.splitlines()[0], "[00:00:05] Inicio")
        self.assertEqual(out.splitlines()[1], "[01:00:00] Final")

    def test_el_umbral_de_una_hora_es_inclusivo(self):
        justo = subtitles.format_segments_with_timestamps([seg(0, 3600, "x")])
        antes = subtitles.format_segments_with_timestamps([seg(0, 3599, "x")])
        self.assertEqual(justo, "[00:00:00] x")
        self.assertEqual(antes, "[00:00] x")

    def test_descarta_segmentos_sin_texto(self):
        out = subtitles.format_segments_with_timestamps([
            seg(0, 1, "Hola"), seg(1, 2, "   "), seg(2, 3, "Chau"),
        ])
        self.assertEqual(out, "[00:00] Hola\n[00:02] Chau")

    def test_sin_segmentos_da_cadena_vacia(self):
        self.assertEqual(subtitles.format_segments_with_timestamps([]), "")

    def test_start_negativo_no_produce_marca_negativa(self):
        out = subtitles.format_segments_with_timestamps([seg(-1.2, 2, "Hola")])
        self.assertEqual(out, "[00:00] Hola")


if __name__ == "__main__":
    unittest.main()
