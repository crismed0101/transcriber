"""Build helper: empaqueta Transcriber portable con PyInstaller.

Pasos:
  1) Descarga FFmpeg estatico (gyan.dev release-essentials, LGPL) -> bin/ffmpeg.exe
  2) Corre PyInstaller con Transcriber.spec
  3) Verifica que el .exe + bin/ffmpeg.exe esten en dist/Transcriber/

Uso:
  python build.py            # build normal
  python build.py --clean    # limpia build/ y dist/ antes (con retry si Defender locked)
  python build.py --skip-ffmpeg  # no descargar ffmpeg (asume bin/ ya esta)
"""
import os
import sys
import io
import time
import shutil
import zipfile
import urllib.request
import subprocess

DIR = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(DIR, "Transcriber.spec")
ISS = os.path.join(DIR, "Transcriber.iss")
VENV_PY = os.path.join(DIR, "venv", "Scripts", "python.exe")
BIN_DIR = os.path.join(DIR, "bin")

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# Rutas tipicas donde queda ISCC.exe (compilador de Inno Setup) segun el tipo de install
ISCC_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
]


def log(msg):
    print(f"[build] {msg}", flush=True)


def ensure_ffmpeg():
    """Descarga FFmpeg static a bin/ si no existe."""
    ffmpeg_exe = os.path.join(BIN_DIR, "ffmpeg.exe")
    ffprobe_exe = os.path.join(BIN_DIR, "ffprobe.exe")
    if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
        log(f"FFmpeg ya esta en {BIN_DIR} (skip)")
        return

    os.makedirs(BIN_DIR, exist_ok=True)
    log(f"Descargando FFmpeg desde {FFMPEG_URL} ...")
    with urllib.request.urlopen(FFMPEG_URL, timeout=300) as resp:
        data = resp.read()
    log(f"  recibidos {len(data) / 1024 / 1024:.1f} MB")

    log("Extrayendo ffmpeg.exe / ffprobe.exe ...")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base in ("ffmpeg.exe", "ffprobe.exe"):
                target = os.path.join(BIN_DIR, base)
                with z.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                log(f"  {target}")
            elif base.upper() == "LICENSE":
                target = os.path.join(BIN_DIR, "FFMPEG-LICENSE.txt")
                if not os.path.exists(target):
                    with z.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    if not (os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe)):
        raise RuntimeError("Falto extraer ffmpeg.exe o ffprobe.exe del zip")


def ensure_pyinstaller(python):
    log("Verificando PyInstaller...")
    r = subprocess.run(
        [python, "-c", "import PyInstaller"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        log("Instalando pyinstaller ...")
        subprocess.run([python, "-m", "pip", "install", "--upgrade", "pyinstaller"], check=True)


def find_iscc():
    """Ubica ISCC.exe (compilador de Inno Setup). None si no esta instalado."""
    for c in ISCC_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def build_installer():
    """Compila installer/Transcriber-Setup.exe con Inno Setup a partir de dist/Transcriber/.

    Requiere Inno Setup instalado (winget install JRSoftware.InnoSetup).
    """
    if not os.path.exists(ISS):
        log(f"No existe {ISS}; salto el instalador")
        return
    iscc = find_iscc()
    if not iscc:
        log("Inno Setup (ISCC.exe) no encontrado. Instalalo con:")
        log("    winget install JRSoftware.InnoSetup")
        log("y volve a correr: python build.py --installer")
        return
    log(f"Compilando instalador con {iscc} ...")
    subprocess.run([iscc, ISS], check=True, cwd=DIR)
    out = os.path.join(DIR, "installer", "Transcriber-Setup.exe")
    if os.path.exists(out):
        size_mb = os.path.getsize(out) / 1024 / 1024
        log(f"OK instalador -> {out} ({size_mb:.0f} MB)")
    else:
        log("WARN: ISCC corrio pero no se encontro Transcriber-Setup.exe")


def main():
    args = sys.argv[1:]
    python = VENV_PY if os.path.exists(VENV_PY) else sys.executable

    if "--clean" in args:
        for d in ("build", "dist"):
            p = os.path.join(DIR, d)
            if not os.path.isdir(p):
                continue
            log(f"Limpiando {p}")
            # Retry con backoff: Defender / indexer pueden tener locks transitorios
            for attempt in range(5):
                try:
                    shutil.rmtree(p)
                    break
                except (PermissionError, OSError) as ex:
                    if attempt < 4:
                        log(f"  bloqueado ({ex}); reintento {attempt + 2}/5...")
                        time.sleep(3)
                    else:
                        log(f"  WARN: no se pudo limpiar {p} ({ex})")
                        log("  el build seguira y sobreescribira archivos individuales")

    if "--skip-ffmpeg" not in args:
        ensure_ffmpeg()

    ensure_pyinstaller(python)

    # Build SIEMPRE a un distpath unico timestampeado para evitar locks de Defender/indexer.
    # Al final intentamos rename a dist/Transcriber/. Si falla, dejamos en la ruta nueva.
    ts = time.strftime("%Y%m%d_%H%M%S")
    build_distpath = os.path.join(DIR, f"dist_{ts}")
    final_distpath = os.path.join(DIR, "dist")
    log(f"Build distpath: {build_distpath}")

    log("Corriendo PyInstaller...")
    subprocess.run(
        [python, "-m", "PyInstaller", "--noconfirm",
         "--distpath", build_distpath, SPEC],
        check=True,
        cwd=DIR,
    )

    # Tratar de promover el build a dist/Transcriber/ (mejor esfuerzo)
    promoted_to_default = False
    final_target = os.path.join(final_distpath, "Transcriber")
    src_dist = os.path.join(build_distpath, "Transcriber")
    if os.path.isdir(src_dist):
        # Si dist/Transcriber esta locked, lo dejamos en dist_<ts>/ y avisamos
        try:
            if os.path.isdir(final_target):
                shutil.rmtree(final_target)
            os.makedirs(final_distpath, exist_ok=True)
            shutil.move(src_dist, final_target)
            shutil.rmtree(build_distpath, ignore_errors=True)
            promoted_to_default = True
        except (PermissionError, OSError) as ex:
            log(f"No se pudo promover a dist/Transcriber/ (lock): {ex}")
            log(f"El build queda en: {src_dist}")

    dist_root = final_target if promoted_to_default else src_dist
    out_exe = os.path.join(dist_root, "Transcriber.exe")
    if not os.path.exists(out_exe):
        log(f"FALLO: no existe {out_exe}")
        sys.exit(1)

    # Copiar bin/ al root de dist/Transcriber/ (al lado del .exe), no dentro de _internal/.
    # Asi el usuario puede ver / reemplazar ffmpeg si quiere.
    out_bin = os.path.join(dist_root, "bin")
    if os.path.isdir(BIN_DIR):
        log(f"Copiando bin/ -> {out_bin}")
        if os.path.isdir(out_bin):
            shutil.rmtree(out_bin)
        shutil.copytree(BIN_DIR, out_bin)

    # Crear un README rapido para el usuario final
    readme_dst = os.path.join(dist_root, "LEEME.txt")
    src_readme = os.path.join(DIR, "USER_README.txt")
    if os.path.exists(src_readme):
        shutil.copy2(src_readme, readme_dst)

    # NOTA: ya NO se crea portable.txt. La app corre siempre en modo estandar
    # Windows en cualquier PC (decision de producto, ver paths.is_portable):
    #   Transcripciones/audios -> Documents\Transcriber\
    #   Modelos / logs         -> %LOCALAPPDATA%\Transcriber\
    # Si quedara un portable.txt de un build viejo junto al .exe, la app lo ignora.

    log(f"OK -> {out_exe}")

    # Instalador opcional (Inno Setup): python build.py --installer
    if "--installer" in args:
        build_installer()
        log("Para distribuir: comparti installer/Transcriber-Setup.exe (un solo archivo).")
        log("El usuario lo ejecuta y la app se instala sola (accesos directos + desinstalador).")
    else:
        log("Para distribuir la carpeta: zipea dist/Transcriber/ y compartila.")
        log("Para un instalador de un solo archivo: python build.py --installer")
    log("Transcripciones -> Documents\\Transcriber\\ ; modelos/logs -> %LOCALAPPDATA%\\Transcriber\\")


if __name__ == "__main__":
    main()
