"""Captura de audio: loopback WASAPI (lo que suena) o microfono.

Invariante central: si `start()` falla por cualquier motivo, el objeto queda en el
mismo estado que antes de llamarlo. Antes no era asi y un fallo de disco dejaba
`is_recording` en True para siempre, con lo que el siguiente intento de grabar
mostraba la UI en modo grabacion sin capturar nada.
"""
import os
import wave
import logging
import threading

import pyaudiowpatch as pyaudio

log = logging.getLogger(__name__)

# Fuentes soportadas
SOURCE_LOOPBACK = "loopback"  # Audio del sistema (lo que sale por los parlantes)
SOURCE_MIC = "mic"            # Microfono

# El header WAV usa offsets de 32 bits -> limite real ~4 GB. Cortamos antes para
# no producir un archivo corrupto.
WAV_MAX_BYTES = int(3.8 * 1024 * 1024 * 1024)


class AudioCapture:
    def __init__(self):
        self.pa = None
        self.stream = None
        self.is_recording = False
        self.init_error = None
        self._lock = threading.Lock()
        self._wav_file = None
        self._wav_path = None
        self._device_channels = 1
        self._device_rate = 48000
        self._device_name = ""
        self._frames_count = 0
        self._bytes_written = 0
        self._paused = False
        self._disk_error = False
        self._size_limit_hit = False

        # PortAudio puede fallar al inicializarse: PC sin dispositivos de audio,
        # servicio "Windows Audio" detenido, o sesion de Escritorio Remoto sin
        # redireccion. No es fatal: la app sigue sirviendo para transcribir
        # archivos, solo se deshabilita la grabacion.
        try:
            self.pa = pyaudio.PyAudio()
        except Exception as ex:
            self.init_error = str(ex)
            log.error("No se pudo inicializar el audio del sistema: %s", ex, exc_info=True)

    # ── Estado publico ──
    @property
    def available(self):
        """True si se puede grabar en este equipo."""
        return self.pa is not None

    @property
    def device_name(self):
        return self._device_name

    @property
    def disk_error(self):
        """True si la escritura del WAV fallo (tipicamente, disco lleno)."""
        return self._disk_error

    @property
    def size_limit_hit(self):
        """True si la grabacion alcanzo el limite del formato WAV."""
        return self._size_limit_hit

    # ── Dispositivos ──
    def get_device(self, source=SOURCE_LOOPBACK):
        """Mejor dispositivo para la fuente pedida, o None si no hay."""
        if not self.available:
            return None

        if source == SOURCE_MIC:
            try:
                return self.pa.get_default_input_device_info()
            except Exception:
                log.warning("No se pudo obtener el microfono por defecto", exc_info=True)
                self._log_input_devices()
                return None

        devices = []
        try:
            wasapi_info = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            for i in range(self.pa.get_device_count()):
                d = self.pa.get_device_info_by_index(i)
                if d["hostApi"] == wasapi_info["index"] and d.get("isLoopbackDevice", False):
                    devices.append(d)
        except Exception:
            log.warning("No se pudieron enumerar los dispositivos WASAPI", exc_info=True)

        if not devices:
            try:
                return self.pa.get_default_wasapi_loopback()
            except Exception:
                log.warning("No hay dispositivo de loopback WASAPI", exc_info=True)
                self._log_input_devices()
                return None

        for d in devices:
            name = d["name"].lower()
            if "speaker" in name or "realtek" in name:
                return d
        return devices[0]

    def _log_input_devices(self):
        """Vuelca los dispositivos de entrada al log.

        Se llama solo cuando no encontramos dispositivo: es la informacion que hace
        falta para diagnosticar un reporte de "no me graba".
        """
        if not self.available:
            return
        try:
            for i in range(self.pa.get_device_count()):
                d = self.pa.get_device_info_by_index(i)
                if d.get("maxInputChannels", 0) > 0:
                    log.info(
                        "  device[%d] %s | loopback=%s | %d ch | %d Hz",
                        d["index"], d["name"], bool(d.get("isLoopbackDevice", False)),
                        d["maxInputChannels"], int(d["defaultSampleRate"]),
                    )
        except Exception:
            log.warning("No se pudieron listar los dispositivos", exc_info=True)

    # ── Grabacion ──
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Lo llama PortAudio desde su propio hilo cuando hay datos."""
        if self._paused:
            return (None, pyaudio.paContinue)
        with self._lock:
            if not self._wav_file:
                return (None, pyaudio.paContinue)
            if self._bytes_written + len(in_data) >= WAV_MAX_BYTES:
                log.error("El WAV alcanzo el limite de %d bytes; deteniendo", WAV_MAX_BYTES)
                self._size_limit_hit = True
                return (None, pyaudio.paAbort)
            try:
                self._wav_file.writeframes(in_data)
            except OSError as ex:
                log.error("Error escribiendo audio (disco lleno?): %s", ex)
                self._disk_error = True
                return (None, pyaudio.paAbort)
            self._frames_count += 1
            self._bytes_written += len(in_data)
        return (None, pyaudio.paContinue)

    def start(self, wav_path, source=SOURCE_LOOPBACK):
        """Inicia la grabacion escribiendo directo a disco.

        Si algo falla, deja el objeto como estaba y borra el WAV a medias.

        Raises:
            RuntimeError: si no hay dispositivo o el audio no esta disponible.
            OSError: si no se puede crear el archivo.
        """
        if self.is_recording:
            return
        if not self.available:
            raise RuntimeError(
                "El audio del sistema no esta disponible en este equipo"
                + (f": {self.init_error}" if self.init_error else "")
            )

        device = self.get_device(source)
        if not device:
            raise RuntimeError(
                "No se encontro microfono" if source == SOURCE_MIC
                else "No se encontro dispositivo de audio del sistema (loopback)"
            )

        channels = max(1, int(device.get("maxInputChannels", 1)))
        rate = int(device["defaultSampleRate"])

        # Todo lo que puede fallar va dentro del try, incluido abrir el WAV. Si
        # algo revienta, el rollback deja el objeto reutilizable.
        wav_file = None
        stream = None
        try:
            wav_file = wave.open(wav_path, "wb")
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(self.pa.get_sample_size(pyaudio.paInt16))
            wav_file.setframerate(rate)

            # El estado se publica recien cuando ya no queda nada que pueda fallar,
            # porque el callback empieza a correr apenas arranca el stream.
            self._wav_path = wav_path
            self._wav_file = wav_file
            self._device_channels = channels
            self._device_rate = rate
            self._device_name = device["name"]
            self._frames_count = 0
            self._bytes_written = 0
            self._paused = False
            self._disk_error = False
            self._size_limit_hit = False
            self.is_recording = True

            stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=1024,
                stream_callback=self._audio_callback,
            )
            self.stream = stream
            stream.start_stream()
        except Exception:
            self.is_recording = False
            self._wav_file = None
            self._wav_path = None
            self.stream = None
            self._close_stream(stream)
            if wav_file is not None:
                try:
                    wav_file.close()
                except Exception:
                    pass
            self._unlink(wav_path)
            raise

        log.info("Grabando (%s): %s (%d ch, %d Hz)", source, device["name"], channels, rate)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop_raw(self):
        """Detiene la grabacion y devuelve la ruta del WAV, o None si quedo vacio.

        La propiedad del archivo pasa al que llama: a partir de aca `discard()` y
        `cleanup()` ya no lo tocan. Sin eso, cerrar la app mientras se procesa una
        grabacion borraria el WAV que FFmpeg esta leyendo.
        """
        if not self.is_recording:
            return None

        self.is_recording = False
        self._paused = False
        self._close_stream(self.stream)
        self.stream = None
        self._close_wav()

        path = self._wav_path
        self._wav_path = None

        if self._frames_count == 0:
            self._unlink(path)
            log.warning("La grabacion no capturo ningun frame")
            return None

        log.info("Grabacion finalizada: %d frames, %.1f MB",
                 self._frames_count, self._bytes_written / 1024 / 1024)
        return path

    def discard(self):
        """Detiene la grabacion y borra el WAV sin procesarlo.

        Lo usa el cierre de la app cuando el usuario decide descartar lo grabado:
        sin esto quedaban cientos de MB huerfanos en la carpeta de la sesion.
        """
        was_recording = self.is_recording
        self.is_recording = False
        self._paused = False
        self._close_stream(self.stream)
        self.stream = None
        self._close_wav()
        path = self._wav_path
        self._wav_path = None
        if path:
            self._unlink(path)
            if was_recording:
                log.info("Grabacion descartada: %s", path)
        return path

    def cleanup(self):
        """Libera todos los recursos. Idempotente."""
        self.discard()
        if self.pa is not None:
            try:
                self.pa.terminate()
            except Exception:
                log.warning("Error terminando PortAudio", exc_info=True)
            self.pa = None

    # ── Helpers internos ──
    @staticmethod
    def _close_stream(stream):
        """Cierra un stream de PortAudio pase lo que pase.

        `stop_stream()` lanza si el stream ya fue abortado desde el callback
        (paAbort). Si stop y close comparten un try, el close se saltea y el
        dispositivo WASAPI queda tomado hasta reiniciar la app.
        """
        if stream is None:
            return
        try:
            stream.stop_stream()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            log.warning("No se pudo cerrar el stream de audio", exc_info=True)

    def _close_wav(self):
        with self._lock:
            if self._wav_file:
                try:
                    self._wav_file.close()
                except Exception:
                    log.warning("Error cerrando el WAV", exc_info=True)
                self._wav_file = None

    @staticmethod
    def _unlink(path):
        if not path:
            return
        try:
            os.unlink(path)
        except OSError:
            pass
