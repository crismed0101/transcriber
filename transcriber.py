import wave
import logging
from faster_whisper import WhisperModel

from config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE

log = logging.getLogger(__name__)


def _get_audio_duration(path):
    """Retorna la duracion del audio en segundos."""
    try:
        with wave.open(path, "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


class Transcriber:
    def __init__(self):
        self.model = None

    def load_model(self):
        """Carga el modelo Whisper. Se descarga automaticamente la primera vez (~3GB)."""
        if self.model is None:
            log.info("Cargando modelo %s en %s (%s)", WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE)
            self.model = WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
            log.info("Modelo cargado")

    def transcribe(self, audio_path, language="es", on_progress=None):
        """Transcribe un archivo de audio. on_progress(percent, partial_text) se llama por segmento."""
        self.load_model()

        duration = _get_audio_duration(audio_path)

        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=10,
            best_of=5,
            patience=2.0,
            repetition_penalty=1.1,
            no_repeat_ngram_size=3,
            condition_on_previous_text=True,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.35,
                min_silence_duration_ms=300,
                speech_pad_ms=400,
                min_speech_duration_ms=250,
            ),
        )

        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
            if on_progress and duration > 0:
                pct = min(int(segment.end / duration * 100), 99)
                on_progress(pct, " ".join(text_parts))

        result = " ".join(text_parts)
        if on_progress:
            on_progress(100, result)

        log.info("Transcripcion: %d caracteres, idioma: %s (prob %.2f)",
                 len(result), info.language, info.language_probability)
        return result
