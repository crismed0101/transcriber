import os
import wave
import logging
import threading
import pyaudiowpatch as pyaudio

log = logging.getLogger(__name__)

# Fuentes soportadas
SOURCE_LOOPBACK = "loopback"  # Audio del sistema (lo que sale por parlantes)
SOURCE_MIC = "mic"            # Microfono

# WAV usa headers de 32-bit -> limite real ~4 GB. Cortamos antes para evitar corrupcion.
WAV_MAX_BYTES = int(3.8 * 1024 * 1024 * 1024)  # ~3.8 GB


class AudioCapture:
    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        self._lock = threading.Lock()
        self._wav_file = None
        self._wav_path = None
        self._device_channels = 1
        self._device_rate = 48000
        self._frames_count = 0
        self._paused = False
        self._disk_error = False
        self._device_name = ""

    @property
    def device_name(self):
        return self._device_name

    @property
    def available(self):
        return self.pa is not None

    def get_device(self, source=SOURCE_LOOPBACK):
        """Retorna el mejor dispositivo segun la fuente.

        - SOURCE_LOOPBACK: dispositivo loopback WASAPI (Speakers).
        - SOURCE_MIC: microfono default del sistema.
        """
        if source == SOURCE_MIC:
            try:
                return self.pa.get_default_input_device_info()
            except Exception:
                log.warning("No se pudo obtener microfono default", exc_info=True)
                return None

        # Default: loopback
        devices = []
        try:
            wasapi_info = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            for i in range(self.pa.get_device_count()):
                d = self.pa.get_device_info_by_index(i)
                if d["hostApi"] == wasapi_info["index"] and d.get("isLoopbackDevice", False):
                    devices.append(d)
        except Exception:
            log.warning("No se pudo enumerar dispositivos WASAPI", exc_info=True)

        if not devices:
            try:
                return self.pa.get_default_wasapi_loopback()
            except Exception:
                return None

        for d in devices:
            if "speaker" in d["name"].lower() or "realtek" in d["name"].lower():
                return d
        return devices[0]

    def list_input_devices(self):
        """Para debug: lista todos los devices de entrada disponibles."""
        out = []
        try:
            for i in range(self.pa.get_device_count()):
                d = self.pa.get_device_info_by_index(i)
                if d.get("maxInputChannels", 0) > 0:
                    out.append({
                        "index": d["index"],
                        "name": d["name"],
                        "loopback": bool(d.get("isLoopbackDevice", False)),
                        "rate": int(d["defaultSampleRate"]),
                        "channels": d["maxInputChannels"],
                    })
        except Exception:
            log.warning("No se pudo listar devices", exc_info=True)
        return out

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback llamado por PyAudio cuando hay datos disponibles."""
        if not self._paused:
            with self._lock:
                if self._wav_file:
                    # Cortar antes del limite WAV de 4 GB para evitar corrupcion
                    if self._bytes_written + len(in_data) >= WAV_MAX_BYTES:
                        log.error("WAV alcanzo limite de %d bytes (~3.8 GB), deteniendo", WAV_MAX_BYTES)
                        self._size_limit_hit = True
                        return (None, pyaudio.paAbort)
                    try:
                        self._wav_file.writeframes(in_data)
                        self._frames_count += 1
                        self._bytes_written += len(in_data)
                    except OSError as ex:
                        log.error("Error escribiendo audio (disco lleno?): %s", ex)
                        self._disk_error = True
                        return (None, pyaudio.paAbort)
        return (None, pyaudio.paContinue)

    def start(self, wav_path, source=SOURCE_LOOPBACK):
        """Inicia grabacion directo a disco.

        Args:
          wav_path: ruta donde escribir el WAV.
          source: SOURCE_LOOPBACK (audio del sistema) o SOURCE_MIC (microfono).
        """
        if self.is_recording:
            return

        device = self.get_device(source)
        if not device:
            raise RuntimeError(
                "No se encontro microfono" if source == SOURCE_MIC
                else "No se encontro dispositivo de audio loopback"
            )

        self.is_recording = True
        self._paused = False
        self._frames_count = 0
        self._bytes_written = 0
        self._device_channels = max(1, int(device.get("maxInputChannels", 1)))
        self._device_rate = int(device["defaultSampleRate"])
        self._device_name = device["name"]
        self._disk_error = False
        self._size_limit_hit = False

        log.info("Grabando (%s): %s (%d ch, %d Hz)",
                 source, device["name"], self._device_channels, self._device_rate)

        self._wav_path = wav_path
        self._wav_file = wave.open(wav_path, "wb")
        try:
            self._wav_file.setnchannels(self._device_channels)
            self._wav_file.setsampwidth(self.pa.get_sample_size(pyaudio.paInt16))
            self._wav_file.setframerate(self._device_rate)

            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self._device_channels,
                rate=self._device_rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=1024,
                stream_callback=self._audio_callback,
            )
            self.stream.start_stream()
        except Exception:
            try:
                if self.stream:
                    self.stream.close()
                self.stream = None
            except Exception:
                pass
            try:
                self._wav_file.close()
            except Exception:
                pass
            self._wav_file = None
            self.is_recording = False
            try:
                os.unlink(wav_path)
            except OSError:
                pass
            raise

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop_raw(self):
        """Detiene grabacion. Retorna el wav_path (sin convertir)."""
        if not self.is_recording:
            return None

        self.is_recording = False
        self._paused = False

        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                log.warning("Error cerrando stream", exc_info=True)
            self.stream = None

        with self._lock:
            if self._wav_file:
                self._wav_file.close()
                self._wav_file = None

        if self._frames_count == 0:
            try:
                os.unlink(self._wav_path)
            except Exception:
                pass
            return None

        log.info("Grabacion finalizada: %d frames", self._frames_count)
        return self._wav_path

    def cleanup(self):
        self.is_recording = False
        self._paused = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        with self._lock:
            if self._wav_file:
                self._wav_file.close()
                self._wav_file = None
        if self.pa:
            try:
                self.pa.terminate()
            except Exception:
                pass
