import wave
import threading
import logging

import paths  # noqa: F401  importa primero para setear HF_HOME

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


def _format_srt_ts(seconds):
    """00:00:00,000 -> formato SRT."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments):
    """Construye un string SRT a partir de segmentos {start, end, text}."""
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_format_srt_ts(seg['start'])} --> {_format_srt_ts(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


class Transcriber:
    def __init__(self, model_name=None, device=None, compute_type=None):
        self.model_name = model_name or WHISPER_MODEL
        self.device = device or WHISPER_DEVICE
        self.compute_type = compute_type or WHISPER_COMPUTE_TYPE
        self.model = None
        self._load_lock = threading.Lock()

    def needs_reload(self, model_name):
        return model_name != self.model_name or self.model is None

    def reset(self, model_name):
        """Cambia el modelo a cargar la proxima vez (libera el actual)."""
        with self._load_lock:
            self.model_name = model_name
            self.model = None

    def load_model(self):
        """Carga el modelo Whisper. Se descarga automaticamente la primera vez."""
        with self._load_lock:
            if self.model is None:
                log.info("Cargando modelo %s en %s (%s)", self.model_name, self.device, self.compute_type)
                self.model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                log.info("Modelo cargado")

    def transcribe(self, audio_path, language="es", on_progress=None, should_cancel=None):
        """Transcribe un archivo de audio.

        Args:
          audio_path: WAV mono 16k.
          language: codigo ISO o None para auto-detect.
          on_progress(pct, partial_text): callback opcional por segmento.
          should_cancel(): callable que devuelve True para abortar.

        Returns:
          dict con keys: text, segments[{start,end,text}], language, language_probability, cancelled.
        """
        self.load_model()

        duration = _get_audio_duration(audio_path)

        segments_iter, info = self.model.transcribe(
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
        segments_data = []
        cancelled = False

        for segment in segments_iter:
            if should_cancel and should_cancel():
                cancelled = True
                break
            text_parts.append(segment.text.strip())
            segments_data.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text,
            })
            if on_progress and duration > 0:
                pct = min(int(segment.end / duration * 100), 99)
                on_progress(pct, " ".join(text_parts))

        result_text = " ".join(text_parts)
        if on_progress and not cancelled:
            on_progress(100, result_text)

        log.info(
            "Transcripcion: %d caracteres, idioma=%s prob=%.2f, cancelled=%s",
            len(result_text), info.language, info.language_probability, cancelled,
        )
        return {
            "text": result_text,
            "segments": segments_data,
            "language": info.language,
            "language_probability": float(info.language_probability),
            "cancelled": cancelled,
        }
