import os
import wave
import logging
import threading
import pyaudiowpatch as pyaudio

log = logging.getLogger(__name__)


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

    @property
    def available(self):
        return self.pa is not None

    def get_default_loopback(self):
        """Retorna el mejor dispositivo loopback (Speakers)."""
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

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback llamado por PyAudio cuando hay datos disponibles."""
        if not self._paused:
            with self._lock:
                if self._wav_file:
                    self._wav_file.writeframes(in_data)
                    self._frames_count += 1
        return (None, pyaudio.paContinue)

    def start(self, wav_path):
        """Inicia grabacion directo a disco."""
        if self.is_recording:
            return

        device = self.get_default_loopback()
        if not device:
            raise RuntimeError("No se encontro dispositivo de audio loopback")

        self.is_recording = True
        self._paused = False
        self._frames_count = 0
        self._device_channels = device["maxInputChannels"]
        self._device_rate = int(device["defaultSampleRate"])

        log.info("Grabando: %s (%d ch, %d Hz)", device["name"], self._device_channels, self._device_rate)

        self._wav_path = wav_path
        self._wav_file = wave.open(wav_path, "wb")
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

    def pause(self):
        """Pausa la grabacion (deja de escribir a disco)."""
        self._paused = True

    def resume(self):
        """Reanuda la grabacion."""
        self._paused = False

    def stop_raw(self):
        """Detiene grabacion. Retorna solo el wav_path (sin convertir)."""
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
