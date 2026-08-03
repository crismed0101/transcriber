"""Empaqueta Transcriber para Windows con PyInstaller e Inno Setup.

Pasos:
  1) Descarga FFmpeg estatico (gyan.dev, LGPL) a bin/ si falta.
  2) Corre PyInstaller con Transcriber.spec sobre un distpath con timestamp.
  3) Verifica que el resultado tenga TODO lo que la app necesita en runtime.
  4) Promueve el resultado a dist/Transcriber/.
  5) Opcionalmente compila installer/Transcriber-Setup-vX.Y.Z.exe con Inno Setup.

Uso:
  python build.py                    build normal
  python build.py --clean            limpia build/ y dist/ antes
  python build.py --installer        ademas compila el instalador
  python build.py --strict           cualquier degradacion es un error (recomendado
                                     para builds que se van a distribuir)
  python build.py --skip-ffmpeg      no descarga FFmpeg (asume que bin/ ya esta)
  python build.py --lock             escribe requirements.lock.txt con lo instalado
"""
import io
import os
import sys
import time
import glob
import shutil
import hashlib
import zipfile
import argparse
import subprocess
import urllib.request

import version

DIR = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(DIR, "Transcriber.spec")
ISS = os.path.join(DIR, "Transcriber.iss")
BIN_DIR = os.path.join(DIR, "bin")
DIST_DIR = os.path.join(DIR, "dist")
INSTALLER_DIR = os.path.join(DIR, "installer")
VENV_PY = os.path.join(DIR, "venv", "Scripts", "python.exe")
LOCK_FILE = os.path.join(DIR, "requirements.lock.txt")

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# Rutas tipicas de ISCC.exe (compilador de Inno Setup) segun el tipo de instalacion.
ISCC_CANDIDATES = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
)

# Lo que el ejecutable necesita para funcionar. Que PyInstaller termine sin error no
# garantiza que esten: un import perezoso o un hook desactualizado pueden dejar
# huecos que solo se notan cuando el usuario intenta transcribir.
#   (subdirectorio, patron, cantidad minima, por que hace falta)
REQUIRED_ARTIFACTS = (
    ("_internal/faster_whisper/assets", "*.onnx", 1, "modelo Silero del VAD"),
    ("_internal/onnxruntime/capi", "*.pyd", 1, "runtime del VAD"),
    ("_internal/av", "*.pyd", 1, "decodificador de audio"),
    ("_internal/ctranslate2", "*.dll", 1, "motor de inferencia"),
    ("_internal/PyQt6/Qt6/bin", "Qt6Core.dll", 1, "interfaz grafica"),
)


class BuildError(RuntimeError):
    """Error que debe abortar el build."""


def log(msg):
    print(f"[build] {msg}", flush=True)


def warn(msg, strict):
    """Avisa; en modo estricto aborta.

    Sin --strict el build degrada como antes (util al iterar); con --strict nada
    pasa en silencio, que es lo que hace falta para un artefacto que se distribuye.
    """
    if strict:
        raise BuildError(msg)
    log(f"AVISO: {msg}")


# ── FFmpeg ──
def ensure_ffmpeg():
    """Descarga ffmpeg.exe a bin/ si no esta.

    Solo ffmpeg: ffprobe.exe pesa ~100 MB y la app no lo invoca nunca.
    """
    ffmpeg_exe = os.path.join(BIN_DIR, "ffmpeg.exe")
    if os.path.exists(ffmpeg_exe):
        log(f"FFmpeg ya esta en {BIN_DIR}")
        return

    os.makedirs(BIN_DIR, exist_ok=True)
    log(f"Descargando FFmpeg de {FFMPEG_URL} ...")
    with urllib.request.urlopen(FFMPEG_URL, timeout=300) as resp:
        data = resp.read()
    log(f"  recibidos {len(data) / 1024 / 1024:.1f} MB")

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base == "ffmpeg.exe":
                with z.open(member) as src, open(ffmpeg_exe, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                log(f"  {ffmpeg_exe}")
            elif base.upper() == "LICENSE":
                # La licencia LGPL debe viajar con el binario.
                target = os.path.join(BIN_DIR, "FFMPEG-LICENSE.txt")
                if not os.path.exists(target):
                    with z.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    if not os.path.exists(ffmpeg_exe):
        raise BuildError("El zip de FFmpeg no contenia ffmpeg.exe")


# ── Entorno ──
def ensure_pyinstaller(python):
    r = subprocess.run([python, "-c", "import PyInstaller"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        log("Instalando PyInstaller ...")
        subprocess.run([python, "-m", "pip", "install", "--upgrade", "pyinstaller"],
                       check=True)


def write_lock_file(python):
    """Congela el entorno actual para poder reproducir este build."""
    r = subprocess.run([python, "-m", "pip", "freeze"],
                       capture_output=True, text=True, check=True)
    header = (
        "# Entorno exacto con el que se compilo este build.\n"
        f"# Transcriber {version.__version__} — generado por: python build.py --lock\n"
        "# Para reproducirlo:  pip install -r requirements.lock.txt\n"
        "# No editar a mano; regenerar con --lock.\n"
    )
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(header + r.stdout)
    log(f"OK lock -> {LOCK_FILE}")


def clean(strict):
    for name in ("build", "dist"):
        path = os.path.join(DIR, name)
        if not os.path.isdir(path):
            continue
        log(f"Limpiando {path}")
        # Reintentos: Defender y el indexador toman locks transitorios.
        for attempt in range(5):
            try:
                shutil.rmtree(path)
                break
            except OSError as ex:
                if attempt < 4:
                    log(f"  bloqueado ({ex}); reintento {attempt + 2}/5 ...")
                    time.sleep(3)
                else:
                    warn(f"no se pudo limpiar {path}: {ex}", strict)


# ── Verificacion del resultado ──
def verify_artifacts(dist_root, strict):
    """Confirma que el build tiene lo necesario para correr."""
    log("Verificando el contenido del build ...")
    for subdir, pattern, minimum, why in REQUIRED_ARTIFACTS:
        found = glob.glob(os.path.join(dist_root, subdir.replace("/", os.sep), pattern))
        if len(found) < minimum:
            warn(f"falta {pattern} en {subdir} ({why}). "
                 "La app compilaria igual pero fallaria al usarse.", strict)
        else:
            log(f"  OK {subdir}/{pattern} ({len(found)})")

    # Las DLL de CUDA son opcionales: sin ellas la app corre en CPU.
    cuda = glob.glob(os.path.join(dist_root, "_internal", "ctranslate2", "cublas*.dll"))
    log("  CUDA: " + ("incluido (GPU disponible)" if cuda else
                      "no incluido (la app usara CPU)"))


def assert_fresh(path, started_at, what):
    """Falla si `path` no se genero en esta corrida.

    Es la red que evita el peor desenlace posible: distribuir un instalador
    construido a partir de un build anterior sin que nadie se entere.
    """
    if not os.path.exists(path):
        raise BuildError(f"No existe {path}: {what} no se genero")
    if os.path.getmtime(path) < started_at:
        raise BuildError(
            f"{path} es de una corrida ANTERIOR "
            f"(modificado {time.ctime(os.path.getmtime(path))}, "
            f"build iniciado {time.ctime(started_at)}). Abortando para no publicar "
            "un artefacto desactualizado."
        )


# ── Promocion del build ──
def promote(build_distpath, strict):
    """Mueve el build recien hecho a dist/Transcriber/ y devuelve la ruta final.

    Aparta el directorio anterior con un rename antes de tocar nada: si esta
    bloqueado, el rename falla de inmediato y no se destruye nada. La version vieja
    hacia rmtree primero, asi que un lock a mitad de camino dejaba dist/Transcriber/
    incompleto y el instalador lo empaquetaba igual.
    """
    src = os.path.join(build_distpath, version.APP_NAME)
    final = os.path.join(DIST_DIR, version.APP_NAME)
    if not os.path.isdir(src):
        raise BuildError(f"PyInstaller no genero {src}")

    retired = None
    try:
        os.makedirs(DIST_DIR, exist_ok=True)
        if os.path.isdir(final):
            retired = f"{final}.old_{time.strftime('%Y%m%d_%H%M%S')}"
            os.rename(final, retired)
        shutil.move(src, final)
    except OSError as ex:
        if retired and os.path.isdir(retired) and not os.path.isdir(final):
            os.rename(retired, final)   # dejar todo como estaba
        warn(f"no se pudo promover a {final}: {ex}. El build queda en {src}", strict)
        return src

    shutil.rmtree(build_distpath, ignore_errors=True)
    if retired:
        shutil.rmtree(retired, ignore_errors=True)
    return final


# ── Instalador ──
def find_iscc():
    """Ubica ISCC.exe. Respeta ISCC_PATH si esta definida."""
    env = os.environ.get("ISCC_PATH")
    if env and os.path.exists(env):
        return env
    for candidate in ISCC_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def build_installer(dist_root, started_at, strict):
    """Compila installer/Transcriber-Setup-vX.Y.Z.exe a partir de dist_root.

    dist_root se le pasa a ISCC de forma explicita. Antes el .iss tenia la ruta
    'dist\\Transcriber' fija, asi que si la promocion fallaba el instalador
    empaquetaba en silencio el build anterior.
    """
    if not os.path.exists(ISS):
        warn(f"no existe {ISS}; salto el instalador", strict)
        return

    iscc = find_iscc()
    if not iscc:
        warn("no se encontro ISCC.exe. Instalalo con:\n"
             "    winget install JRSoftware.InnoSetup\n"
             "  (o defini ISCC_PATH apuntando al ejecutable)", strict)
        return

    # Borrar salidas viejas para que la verificacion posterior no valide un archivo
    # de otra corrida.
    for old in glob.glob(os.path.join(INSTALLER_DIR, "*.exe")):
        try:
            os.unlink(old)
        except OSError:
            pass

    log(f"Compilando el instalador con {iscc} ...")
    subprocess.run(
        [iscc,
         f"/DSourceDistDir={os.path.abspath(dist_root)}",
         f"/DAppVersion={version.__version__}",
         ISS],
        check=True, cwd=DIR,
    )

    out = os.path.join(
        INSTALLER_DIR, f"{version.APP_NAME}-Setup-v{version.__version__}-windows-x64.exe"
    )
    assert_fresh(out, started_at, "el instalador")
    log(f"OK instalador -> {out} ({os.path.getsize(out) / 1024 / 1024:.0f} MB)")
    write_checksum(out)


def write_checksum(path):
    """Escribe <archivo>.sha256 junto al instalador.

    install.ps1 lo usa para verificar la descarga antes de ejecutarla; como el
    binario no esta firmado, esta es la unica garantia de integridad que podemos
    ofrecer.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_path = path + ".sha256"
    with open(checksum_path, "w", encoding="ascii") as f:
        f.write(f"{digest.hexdigest()}  {os.path.basename(path)}\n")
    log(f"OK checksum -> {checksum_path}")


# ── Entrada ──
def parse_args(argv):
    p = argparse.ArgumentParser(description="Empaqueta Transcriber para Windows.")
    p.add_argument("--clean", action="store_true", help="limpia build/ y dist/ antes")
    p.add_argument("--installer", action="store_true", help="ademas compila el instalador")
    p.add_argument("--strict", action="store_true",
                   help="cualquier degradacion aborta el build (usar al distribuir)")
    p.add_argument("--skip-ffmpeg", action="store_true", help="no descarga FFmpeg")
    p.add_argument("--lock", action="store_true",
                   help="escribe requirements.lock.txt con el entorno actual")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    started_at = time.time()
    python = VENV_PY if os.path.exists(VENV_PY) else sys.executable

    log(f"{version.APP_NAME} {version.__version__}  |  python: {python}")

    if args.clean:
        clean(args.strict)
    if not args.skip_ffmpeg:
        ensure_ffmpeg()
    ensure_pyinstaller(python)
    if args.lock:
        write_lock_file(python)

    # Se compila siempre a un distpath con timestamp: si dist/ quedo bloqueado por
    # Defender o el indexador, el build igual se completa.
    build_distpath = os.path.join(DIR, f"dist_{time.strftime('%Y%m%d_%H%M%S')}")
    log(f"Compilando en {build_distpath} ...")
    subprocess.run(
        [python, "-m", "PyInstaller", "--noconfirm", "--distpath", build_distpath, SPEC],
        check=True, cwd=DIR,
    )

    dist_root = promote(build_distpath, args.strict)
    exe = os.path.join(dist_root, f"{version.APP_NAME}.exe")
    assert_fresh(exe, started_at, "el ejecutable")

    # bin/ va junto al .exe y no dentro de _internal/, para que el usuario lo vea.
    if os.path.isdir(BIN_DIR):
        out_bin = os.path.join(dist_root, "bin")
        log(f"Copiando bin/ -> {out_bin}")
        shutil.rmtree(out_bin, ignore_errors=True)
        shutil.copytree(BIN_DIR, out_bin)

    for name in ("USER_README.txt", "LICENSE"):
        src = os.path.join(DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dist_root, "LEEME.txt" if "README" in name else name))

    verify_artifacts(dist_root, args.strict)
    log(f"OK -> {exe}")

    if args.installer:
        build_installer(dist_root, started_at, args.strict)
        log("Para distribuir: comparti installer/*.exe (un solo archivo).")
    else:
        log("Para un instalador de un solo archivo: python build.py --installer")

    log("Antes de distribuir, verifica el binario:")
    log(f"    {exe} --selftest")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as ex:
        log(f"ERROR: {ex}")
        sys.exit(1)
    except subprocess.CalledProcessError as ex:
        log(f"ERROR: fallo el comando {ex.cmd} (codigo {ex.returncode})")
        sys.exit(ex.returncode or 1)
