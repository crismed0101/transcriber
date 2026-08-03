"""Motor de transcripcion: wrapper de faster-whisper con degradacion automatica.

La idea central es que la app funcione en cualquier PC sin configuracion. En vez
de elegir un motor y fallar si no sirve, `load_model` recorre la escalera de
candidatos que arma `hardware.engine_candidates()` (GPU -> GPU mas chica -> CPU) y
se queda con la primera que carga de verdad.

Eso importa porque `ctranslate2.get_cuda_device_count() > 0` solo consulta el
driver: puede dar True y despues no existir ningun kernel para esa arquitectura
(caso tipico en GPUs nuevas con CTranslate2 viejo). La unica deteccion honesta es
intentar cargar.
"""
import os
import wave
import logging
import threading

import paths  # noqa: F401  importar primero fija HF_HOME antes que faster_whisper

from faster_whisper import WhisperModel

import hardware
from subtitles import format_segments_with_timestamps

log = logging.getLogger(__name__)


class EngineCancelled(Exception):
    """El usuario cancelo mientras se cargaba o descargaba el modelo."""


class EngineLoadError(Exception):
    """Ninguna configuracion de la escalera pudo cargarse."""


def model_repo_id(model_name):
    """Repositorio de HuggingFace del que sale un modelo.

    No todos viven bajo la misma organizacion: los large/medium/small son de
    Systran, pero large-v3-turbo es de mobiuslabsgmbh. Asumir una sola daba una
    ruta de cache equivocada, y con eso la limpieza de modelos borraba el turbo
    recien descargado.
    """
    try:
        from faster_whisper.utils import _MODELS

        return _MODELS.get(model_name, model_name)
    except ImportError:
        # Nombre de repositorio explicito, o el mismo nombre si no se puede resolver.
        return model_name


def model_cache_dir(model_name):
    """Carpeta local donde queda un modelo concreto."""
    return paths.hf_cache_dir(model_repo_id(model_name))


def is_model_downloaded(model_name, min_bytes=50 * 1024 * 1024):
    """True si el modelo ya esta en el cache local.

    Heuristica por tamano: huggingface_hub deja archivos `.incomplete` mientras
    baja, asi que la sola existencia del directorio no alcanza.
    """
    model_dir = model_cache_dir(model_name)
    if not os.path.isdir(model_dir):
        return False
    total = 0
    try:
        for root, _, files in os.walk(model_dir):
            for f in files:
                if f.endswith(".incomplete"):
                    continue
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
                if total >= min_bytes:
                    return True
    except OSError:
        pass
    return False


# ── Opciones de decodificacion ──
#
# Solo se declara lo que se aparta del valor por defecto de faster-whisper. Lo que
# no aparece aca se deja como viene, y eso es deliberado: los defaults son el
# mecanismo con el que Whisper detecta y corta sus propios bucles de repeticion.
#
#   compression_ratio_threshold (2.4)  si el texto sale sospechosamente repetitivo,
#                                      lo da por fallido y reintenta con otra
#                                      temperatura.
#   prompt_reset_on_temperature (0.5)  al reintentar descarta el contexto que llevo
#                                      al bucle. Solo funciona con
#                                      condition_on_previous_text=True.
#   temperature (escalera 0.0 a 1.0)   los reintentos progresivos.
#   condition_on_previous_text (True)  da contexto entre ventanas: puntuacion y
#                                      nombres propios consistentes.
#
# NO usar repetition_penalty ni no_repeat_ngram_size para frenar los bucles: no
# distinguen una repeticion patologica de una legitima, y en habla natural las
# repeticiones son normales. Prohibirlas obliga al modelo a escribir algo distinto
# de lo que se dijo, que es exactamente lo contrario de transcribir.
DECODE_OPTIONS = dict(
    # Mas exploracion que el default (5 y 1): mejor calidad a cambio de tiempo.
    beam_size=10,
    patience=2.0,
    # Habilita hallucination_silence_threshold, que sin esto no hace nada.
    word_timestamps=True,
    # Descarta texto inventado en silencios de mas de 2 s.
    hallucination_silence_threshold=2.0,
)

# ── Deteccion de voz (VAD Silero) ──
#
# Recorta los silencios antes de transcribir. Hay que tener cuidado: es la unica
# parte del proceso que puede DESCARTAR audio antes de que el modelo lo vea.
VAD_OPTIONS = dict(
    # Mas sensible que el default (0.5) para no perder voz baja o lejana.
    threshold=0.35,
    # min_speech_duration_ms se deja en 0 (el default) A PROPOSITO: cualquier valor
    # mayor descarta por completo los fragmentos mas cortos, y en español "si",
    # "no", "y" o "ya" duran menos de un cuarto de segundo.
    min_speech_duration_ms=0,
    # Entre el default (2000) y un valor agresivo: fragmentos naturales sin retrasar
    # de mas la aparicion del texto en pantalla.
    min_silence_duration_ms=800,
    speech_pad_ms=400,
)

# Texto que orienta el estilo de salida. Whisper imita lo que ve aca, asi que un
# ejemplo con acentos y puntuacion correctos mejora ambas cosas de forma notable.
DEFAULT_INITIAL_PROMPT = (
    "Transcripción en español, con puntuación, acentos y mayúsculas correctas."
)


def build_transcribe_options(language=None, initial_prompt=None):
    """Arma las opciones para WhisperModel.transcribe().

    Separado de la llamada para poder verificarlo sin cargar un modelo.
    """
    options = dict(DECODE_OPTIONS)
    options["language"] = language
    options["initial_prompt"] = (
        initial_prompt if initial_prompt is not None else DEFAULT_INITIAL_PROMPT
    ) or None
    # El VAD requiere onnxruntime, que faster_whisper importa de forma perezosa:
    # por eso el empaquetado lo incluye de forma explicita (ver Transcriber.spec).
    options["vad_filter"] = True
    options["vad_parameters"] = dict(VAD_OPTIONS)
    return options


def _audio_duration(path):
    """Duracion en segundos de un WAV. 0.0 si no se puede leer."""
    try:
        with wave.open(path, "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except (wave.Error, OSError, ZeroDivisionError):
        return 0.0


class Transcriber:
    """Motor Whisper con seleccion de configuracion adaptada al equipo."""

    def __init__(self, preferred_model=None):
        self._preferred_model = preferred_model
        self._model = None
        self._active = None   # (model_name, device, compute_type) ya cargada
        self._stale = False   # el modelo cargado ya no corresponde a lo pedido
        self._load_lock = threading.Lock()

    # ── Estado ──
    @property
    def is_loaded(self):
        return self._model is not None and not self._stale

    @property
    def preferred_model(self):
        return self._preferred_model

    @property
    def active(self):
        """(model_name, device, compute_type) en uso, o None si no cargo aun."""
        return self._active

    @property
    def model_name(self):
        return self._active[0] if self._active else (
            self._preferred_model or hardware.recommend_model()
        )

    @property
    def device(self):
        return self._active[1] if self._active else (
            "cuda" if hardware.cuda_available() else "cpu"
        )

    def describe(self):
        """Texto corto para la UI: 'large-v3 en GPU (float16)'."""
        name, device, compute = self._active or (
            self.model_name, self.device, hardware.compute_type_for(self.device)
        )
        where = "GPU" if device == "cuda" else "CPU"
        return f"{name} en {where} ({compute})"

    def set_preferred_model(self, model_name):
        """Cambia el modelo deseado. Devuelve True si hay que recargar el motor.

        No toma `_load_lock` a proposito: si hubiera una carga en curso (que puede
        estar descargando varios GB), pedir el lock aca congelaria la interfaz hasta
        que terminara. En su lugar marca el motor como obsoleto y `load_model`, que
        si tiene el lock, lo descarta cuando le toca.
        """
        if model_name == self._preferred_model:
            return False
        self._preferred_model = model_name
        self._stale = True
        log.info("Modelo preferido cambiado a %s", model_name or "automatico")
        return True

    # ── Carga ──
    def _acquire(self, should_cancel):
        """Toma el lock de carga sin bloquear la cancelacion.

        Sin esto, cancelar durante la descarga inicial de 3 GB no hacia nada: el
        hilo quedaba dormido en un `with lock` hasta que la descarga terminara.
        """
        while not self._load_lock.acquire(timeout=0.2):
            if should_cancel and should_cancel():
                raise EngineCancelled()

    def load_model(self, should_cancel=None, on_attempt=None):
        """Carga el mejor motor que este equipo soporte de verdad.

        Recorre `hardware.engine_candidates()` y se queda con el primero que
        instancia sin error. Los modelos se descargan solos la primera vez.

        Args:
            should_cancel: callable que devuelve True para abortar.
            on_attempt: callback(model_name, device) antes de cada intento, para
                que la UI pueda contar lo que esta pasando.

        Raises:
            EngineCancelled: si should_cancel() dio True.
            EngineLoadError: si ninguna configuracion cargo.
        """
        self._acquire(should_cancel)
        try:
            if self._model is not None and not self._stale:
                return self._active
            # Descartar el motor anterior antes de rearmar la escalera.
            self._model = None
            self._active = None
            self._stale = False

            candidates = hardware.engine_candidates(self._preferred_model)
            log.info("Candidatos de motor: %s", candidates)
            last_error = None

            for name, device, compute in candidates:
                if should_cancel and should_cancel():
                    raise EngineCancelled()
                if on_attempt:
                    on_attempt(name, device)
                log.info("Cargando modelo %s en %s (%s)...", name, device, compute)
                try:
                    self._model = WhisperModel(name, device=device, compute_type=compute)
                except Exception as ex:
                    last_error = ex
                    log.warning(
                        "No se pudo cargar %s en %s (%s): %s", name, device, compute, ex
                    )
                    continue
                self._active = (name, device, compute)
                log.info("Motor activo: %s", self.describe())
                return self._active

            raise EngineLoadError(
                f"Ninguna configuracion pudo cargarse. Ultimo error: {last_error}"
            )
        finally:
            self._load_lock.release()

    # ── Transcripcion ──
    def transcribe(self, audio_path, language="es", on_progress=None,
                   should_cancel=None, initial_prompt=None):
        """Transcribe un WAV mono de 16 kHz.

        Args:
            audio_path: ruta al WAV ya normalizado.
            language: codigo ISO, o None para auto-detectar.
            on_progress: callback(pct, texto_parcial) por segmento.
            should_cancel: callable que devuelve True para abortar.
            initial_prompt: texto que orienta el estilo y el vocabulario. None usa
                el de por defecto; cadena vacia lo desactiva.

        Returns:
            dict con text, segments, language, language_probability, cancelled.
        """
        self.load_model(should_cancel=should_cancel)

        duration = _audio_duration(audio_path)

        segments_iter, info = self._model.transcribe(
            audio_path,
            **build_transcribe_options(language, initial_prompt),
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
                on_progress(pct, format_segments_with_timestamps(segments_data))

        result_text = " ".join(text_parts)
        if on_progress and not cancelled:
            on_progress(100, format_segments_with_timestamps(segments_data))

        log.info(
            "Transcripcion: %d caracteres, idioma=%s prob=%.2f, cancelada=%s",
            len(result_text), info.language, info.language_probability, cancelled,
        )
        return {
            "text": result_text,
            "segments": segments_data,
            "language": info.language,
            "language_probability": float(info.language_probability),
            "cancelled": cancelled,
        }
