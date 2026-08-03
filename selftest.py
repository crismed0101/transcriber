"""Autodiagnostico del ejecutable congelado (`Transcriber.exe --selftest`).

Existe porque los fallos de PyInstaller no aparecen al compilar sino en runtime, y
tres de ellos son especialmente traicioneros en esta app:

  - `onnxruntime` no empaquetado: faster_whisper lo importa PEREZOSAMENTE dentro de
    SileroVADModel.__init__, envuelto en try/except ImportError. Como la app usa
    siempre vad_filter=True, el build sale verde y la app muere recien cuando el
    usuario aprieta Transcribir.
  - `av` (PyAV) sin sus DLL de FFmpeg en av.libs/: no se puede decodificar nada.
  - los assets .onnx del VAD ausentes de faster_whisper/assets/.

Este modulo ejercita esos tres caminos sin descargar ningun modelo, y comunica el
resultado por codigo de salida (la app se compila con console=False, no hay stdout).
"""
import os
import sys
import glob
import wave
import struct
import tempfile
import traceback

import paths

CHECK_OK = "OK  "
CHECK_FAIL = "FALLA "


def _make_silence_wav(path, seconds=1, rate=16000):
    """WAV mono de 16 kHz con silencio, para ejercitar el decodificador."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack("<h", 0) * (rate * seconds))


def _checks(report):
    """Corre las verificaciones. Devuelve True si todas pasan."""
    ok = True

    def record(name, passed, detail=""):
        nonlocal ok
        ok = ok and passed
        report.append(f"{CHECK_OK if passed else CHECK_FAIL}{name}"
                      + (f" — {detail}" if detail else ""))

    report.append(f"frozen={paths.is_frozen()}  app_dir={paths.app_dir()}")
    report.append(f"python={sys.version.split()[0]}")

    # 1) FFmpeg bundled
    ffmpeg = paths.ffmpeg_path()
    record("ffmpeg", bool(ffmpeg), ffmpeg or "no esta en bin/")

    # 2) Imports nativos pesados
    mods = {}
    for name in ("ctranslate2", "faster_whisper", "onnxruntime", "av", "numpy"):
        try:
            mods[name] = __import__(name)
            record(f"import {name}", True, getattr(mods[name], "__version__", "?"))
        except Exception as ex:
            record(f"import {name}", False, str(ex))

    # 3) CUDA visible (informativo: la app degrada sola a CPU)
    if "ctranslate2" in mods:
        try:
            n = mods["ctranslate2"].get_cuda_device_count()
            report.append(f"info  cuda_device_count={n}")
        except Exception as ex:
            report.append(f"info  cuda_device_count fallo: {ex}")

    # 4) Assets del VAD + onnxruntime realmente utilizables
    if "faster_whisper" in mods and "onnxruntime" in mods:
        try:
            from faster_whisper.utils import get_assets_path

            assets = get_assets_path()
            onnx_files = sorted(glob.glob(os.path.join(assets, "*.onnx")))
            if not onnx_files:
                record("assets del VAD", False, f"no hay .onnx en {assets}")
            else:
                sess = mods["onnxruntime"].InferenceSession(
                    onnx_files[0], providers=["CPUExecutionProvider"]
                )
                record("VAD Silero", bool(sess.get_inputs()),
                       os.path.basename(onnx_files[0]))
        except Exception as ex:
            record("VAD Silero", False, str(ex))

    # 5) Decodificacion de audio con av
    if "faster_whisper" in mods:
        tmp = os.path.join(tempfile.gettempdir(), "transcriber_selftest.wav")
        try:
            _make_silence_wav(tmp)
            from faster_whisper.audio import decode_audio

            samples = decode_audio(tmp)
            record("decodificar audio (av)", len(samples) > 0, f"{len(samples)} muestras")
        except Exception as ex:
            record("decodificar audio (av)", False, str(ex))
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    return ok


def run():
    """Ejecuta el autodiagnostico. Devuelve 0 si todo pasa, 1 si algo falla."""
    report = []
    try:
        ok = _checks(report)
    except Exception:
        report.append("EXCEPCION no controlada:\n" + traceback.format_exc())
        ok = False

    report.append("RESULTADO: " + ("OK" if ok else "HAY FALLAS"))
    text = "\n".join(report)

    # console=False significa que no hay stdout util en el .exe: el informe va a
    # un archivo y el resultado se comunica por codigo de salida.
    try:
        log_file = paths.selftest_log_path()
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        log_file = "(no se pudo escribir el informe)"

    if sys.stdout is not None:
        print(text)
        print(f"\nInforme: {log_file}")

    return 0 if ok else 1
