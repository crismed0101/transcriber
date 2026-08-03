"""Actualizacion automatica desde GitHub Releases.

Modulo puro: no importa Qt ni nada pesado, para poder probarlo sin el entorno
completo. La interfaz vive en main.py (UpdateCheckThread).

Consulta el repositorio PUBLICO de instaladores (version.RELEASES_REPO), no el del
codigo. Esa separacion es lo que permite buscar actualizaciones sin llevar un token
de GitHub dentro del ejecutable.

Todo falla en silencio: sin internet, detras de un proxy o con GitHub caido, la app
arranca normal y no molesta al usuario.
"""
import os
import json
import hashlib
import logging
import tempfile
import collections
import subprocess
import urllib.error
import urllib.request

import version

log = logging.getLogger(__name__)

UpdateInfo = collections.namedtuple(
    "UpdateInfo", "version tag notes installer_url installer_name size sha256_url"
)

API_TIMEOUT = 10          # el chequeo no debe demorar el arranque
DOWNLOAD_TIMEOUT = 60     # por bloque, no total: el instalador pesa mas de 1 GB
CHUNK = 256 * 1024

_USER_AGENT = f"{version.APP_NAME}/{version.__version__}"


class UpdateError(Exception):
    """Fallo al descargar o verificar una actualizacion."""


class UpdateCancelled(Exception):
    """El usuario cancelo la descarga."""


# ── Comparacion de versiones ──
def parse_version(text):
    """'v1.10.0' -> (1, 10, 0). Tupla vacia si no se puede interpretar."""
    if not text:
        return ()
    parts = []
    for chunk in str(text).strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(candidate, current):
    """True si `candidate` es una version posterior a `current`.

    Compara numericamente, no como texto: 1.10.0 es posterior a 1.9.0.
    """
    a = parse_version(candidate)
    b = parse_version(current)
    if not a:
        return False
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a > b


# ── Consulta a GitHub ──
def _get(url, timeout):
    request = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def check_for_update(current_version=None, repo=None):
    """Devuelve un UpdateInfo si hay version nueva publicada, o None.

    Nunca lanza: cualquier problema de red se registra y se devuelve None.
    """
    current_version = current_version or version.__version__
    repo = repo or version.RELEASES_REPO
    url = f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        with _get(url, API_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as ex:
        log.info("No se pudo consultar actualizaciones: %s", ex)
        return None

    tag = data.get("tag_name") or ""
    if not is_newer(tag, current_version):
        log.info("La version instalada (%s) esta al dia; publicada: %s",
                 current_version, tag or "ninguna")
        return None

    assets = data.get("assets") or []
    installer = next(
        (a for a in assets
         if a.get("name", "").lower().endswith(".exe") and "setup" in a["name"].lower()),
        None,
    )
    if not installer:
        log.warning("El release %s no incluye instalador; se ignora", tag)
        return None

    sha_asset = next(
        (a for a in assets if a.get("name") == installer["name"] + ".sha256"), None
    )

    log.info("Hay una version nueva: %s", tag)
    return UpdateInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        notes=(data.get("body") or "").strip(),
        installer_url=installer.get("browser_download_url"),
        installer_name=installer.get("name"),
        size=installer.get("size") or 0,
        sha256_url=sha_asset.get("browser_download_url") if sha_asset else None,
    )


# ── Descarga y verificacion ──
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checksum(path, expected):
    """Compara el SHA256 del archivo. Si no coincide, LO BORRA y lanza.

    El instalador no esta firmado, asi que esta es la unica garantia de que lo
    descargado es lo que se publico. Un archivo que no verifica no se conserva:
    dejarlo en disco invita a ejecutarlo a mano.
    """
    expected = (expected or "").strip().split()[0].lower() if expected else ""
    real = _sha256(path).lower()
    if not expected:
        raise UpdateError("El release no publica el SHA256; no se puede verificar.")
    if real != expected:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise UpdateError(
            "El archivo descargado no coincide con su firma SHA256. Se elimino."
        )
    return True


def download_installer(info, dest_dir=None, on_progress=None, should_cancel=None):
    """Descarga el instalador y verifica su integridad. Devuelve la ruta.

    Args:
        info: el UpdateInfo devuelto por check_for_update.
        dest_dir: donde dejarlo (por defecto, el temporal del sistema).
        on_progress: callback(bytes_descargados, bytes_totales).
        should_cancel: callable que devuelve True para abortar.

    Raises:
        UpdateCancelled, UpdateError.
    """
    dest_dir = dest_dir or tempfile.gettempdir()
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, info.installer_name)

    try:
        with _get(info.installer_url, DOWNLOAD_TIMEOUT) as response, open(path, "wb") as out:
            total = int(response.headers.get("Content-Length") or info.size or 0)
            downloaded = 0
            while True:
                if should_cancel and should_cancel():
                    raise UpdateCancelled()
                block = response.read(CHUNK)
                if not block:
                    break
                out.write(block)
                downloaded += len(block)
                if on_progress:
                    on_progress(downloaded, total)
    except UpdateCancelled:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as ex:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise UpdateError(f"No se pudo descargar la actualizacion: {ex}") from ex

    if not info.sha256_url:
        raise UpdateError("El release no publica el SHA256; no se puede verificar.")
    try:
        with _get(info.sha256_url, API_TIMEOUT) as response:
            expected = response.read().decode("ascii", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as ex:
        raise UpdateError(f"No se pudo obtener el SHA256: {ex}") from ex

    verify_checksum(path, expected)
    log.info("Actualizacion descargada y verificada: %s", path)
    return path


def launch_installer(path):
    """Ejecuta el instalador descargado y devuelve el control.

    La app debe cerrarse a continuacion: Inno Setup reemplaza los archivos en uso.
    """
    log.info("Lanzando el instalador: %s", path)
    subprocess.Popen([path], close_fds=True)
