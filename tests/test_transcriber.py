import sys
import types
import unittest

# transcriber importa faster_whisper a nivel de modulo, que arrastra ctranslate2 y
# no esta disponible fuera de Windows. Lo que se prueba aca es configuracion pura,
# asi que alcanza con un doble que satisfaga el import.
if "faster_whisper" not in sys.modules:
    _fake = types.ModuleType("faster_whisper")
    _fake.WhisperModel = object
    sys.modules["faster_whisper"] = _fake
    _utils = types.ModuleType("faster_whisper.utils")
    _utils._MODELS = {
        "tiny": "Systran/faster-whisper-tiny",
        "small": "Systran/faster-whisper-small",
        "large-v3": "Systran/faster-whisper-large-v3",
        "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    }
    sys.modules["faster_whisper.utils"] = _utils

import transcriber  # noqa: E402


class VadOptions(unittest.TestCase):
    """El VAD es lo unico que puede DESCARTAR audio antes de que el modelo lo vea."""

    def setUp(self):
        self.vad = transcriber.build_transcribe_options()["vad_parameters"]

    def test_no_descarta_fragmentos_cortos(self):
        # Con 250 ms se perdian palabras como "si", "no", "y" o "ya", que en español
        # duran menos que eso. El valor por defecto de faster-whisper es 0.
        self.assertEqual(self.vad["min_speech_duration_ms"], 0)

    def test_es_mas_sensible_que_el_default(self):
        # 0.5 es el default; bajarlo ayuda con voz baja o lejana.
        self.assertLess(self.vad["threshold"], 0.5)

    def test_no_parte_el_audio_en_fragmentos_diminutos(self):
        # Cuanto mas corto el silencio que corta, mas fragmentos y mas riesgo de
        # perder los bordes de cada uno.
        self.assertGreaterEqual(self.vad["min_silence_duration_ms"], 500)

    def test_conserva_margen_alrededor_de_la_voz(self):
        self.assertGreaterEqual(self.vad["speech_pad_ms"], 200)

    def test_el_vad_esta_activo(self):
        self.assertTrue(transcriber.build_transcribe_options()["vad_filter"])


class AntiRepeticion(unittest.TestCase):
    """Los bucles se cortan con los mecanismos de Whisper, no prohibiendo repetir."""

    def setUp(self):
        self.opciones = transcriber.build_transcribe_options()

    def test_no_se_prohiben_ngramas(self):
        # no_repeat_ngram_size=3 obligaba al modelo a escribir algo distinto de lo
        # dicho cuando alguien repetia una frase. Se deja en el default (0).
        self.assertNotIn("no_repeat_ngram_size", self.opciones)

    def test_no_se_penalizan_repeticiones(self):
        self.assertNotIn("repetition_penalty", self.opciones)

    def test_no_se_desactiva_el_contexto_entre_ventanas(self):
        # condition_on_previous_text=False dejaba al modelo sin memoria: peor
        # puntuacion y nombres propios inconsistentes. El default (True) es el bueno.
        self.assertNotEqual(self.opciones.get("condition_on_previous_text"), False)

    def test_el_filtro_de_alucinaciones_esta_habilitado_de_verdad(self):
        # hallucination_silence_threshold solo tiene efecto con word_timestamps=True.
        # Antes estaba puesto con word_timestamps en False, o sea que no hacia nada.
        self.assertTrue(self.opciones["word_timestamps"])
        self.assertIsNotNone(self.opciones["hallucination_silence_threshold"])


class InitialPrompt(unittest.TestCase):
    def test_por_defecto_orienta_el_estilo_en_español(self):
        prompt = transcriber.build_transcribe_options()["initial_prompt"]
        self.assertTrue(prompt)
        # El prompt tiene que llevar acentos: Whisper imita lo que ve.
        self.assertTrue(any(c in prompt for c in "áéíóúñ"))

    def test_se_puede_personalizar(self):
        opciones = transcriber.build_transcribe_options(initial_prompt="Cardiología, ECG.")
        self.assertEqual(opciones["initial_prompt"], "Cardiología, ECG.")

    def test_cadena_vacia_lo_desactiva(self):
        # Distinto de None, que significa "usa el de por defecto".
        self.assertIsNone(transcriber.build_transcribe_options(initial_prompt="")["initial_prompt"])


class Idioma(unittest.TestCase):
    def test_se_pasa_el_idioma(self):
        self.assertEqual(transcriber.build_transcribe_options("es")["language"], "es")

    def test_none_deja_autodetectar(self):
        self.assertIsNone(transcriber.build_transcribe_options(None)["language"])


class Calidad(unittest.TestCase):
    def test_explora_mas_que_el_default(self):
        opciones = transcriber.build_transcribe_options()
        self.assertGreater(opciones["beam_size"], 5)
        self.assertGreater(opciones["patience"], 1)


class RepositorioDelModelo(unittest.TestCase):
    """No todos los modelos viven bajo la misma organizacion de HuggingFace."""

    def test_los_clasicos_son_de_systran(self):
        self.assertEqual(transcriber.model_repo_id("large-v3"),
                         "Systran/faster-whisper-large-v3")

    def test_el_turbo_es_de_otra_organizacion(self):
        self.assertEqual(transcriber.model_repo_id("large-v3-turbo"),
                         "mobiuslabsgmbh/faster-whisper-large-v3-turbo")

    def test_un_nombre_desconocido_se_usa_tal_cual(self):
        self.assertEqual(transcriber.model_repo_id("mi-org/mi-modelo"), "mi-org/mi-modelo")

    def test_la_carpeta_de_cache_respeta_la_organizacion(self):
        # Armarla asumiendo Systran daba una ruta que no existia, y con eso la
        # limpieza de modelos borraba el turbo recien descargado.
        carpeta = transcriber.model_cache_dir("large-v3-turbo")
        self.assertTrue(carpeta.endswith("models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"),
                        carpeta)


if __name__ == "__main__":
    unittest.main()
