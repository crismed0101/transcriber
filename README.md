# Transcriber

App de escritorio Windows para transcribir audio a texto con Whisper, sin conexión.

- Graba el audio del sistema (loopback WASAPI) o un micrófono.
- Se adapta sola al equipo: elige el modelo que entra en la GPU o la CPU disponible
  y, si la configuración elegida no carga, degrada al siguiente escalón sin
  intervención del usuario.
- FFmpeg incluido, sin dependencias externas en la versión distribuida.

## Instalación

Un solo comando en PowerShell, en cualquier Windows 10/11 de 64 bits:

```powershell
irm https://raw.githubusercontent.com/crismed0101/transcriber/master/install.ps1 | iex
```

Descarga la última versión publicada, verifica su SHA256 y la instala por usuario, sin
pedir permisos de administrador. No hace falta tener Python ni nada instalado.

Alternativa sin comandos: descargar el `.exe` desde
[Releases](https://github.com/crismed0101/transcriber/releases/latest) y hacer doble clic.

Para instalar sin asistente (útil en varias PC) o una versión concreta:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/crismed0101/transcriber/master/install.ps1))) -Silent
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/crismed0101/transcriber/master/install.ps1))) -Version v1.1.0
```

> Windows advierte que el editor es desconocido porque el binario no está firmado:
> **Más información** → **Ejecutar de todas formas**.

Una vez instalada, la app avisa sola cuando hay versión nueva y se actualiza desde el
mismo lugar.

Guía de uso: `USER_README.txt` (se instala junto a la app como `LEEME.txt`).

### Publicar una versión

```cmd
venv\Scripts\python build.py --clean --publish --strict --lock
```

`--publish` compila el instalador, genera su SHA256 y crea el release en GitHub con `gh`.
Toma la descripción de `.github/release-notes-v<version>.md` si existe.

Antes de publicar conviene verificar el binario:

```cmd
dist\Transcriber\Transcriber.exe --selftest
```

Para liberar una versión: cambiar `__version__` en `version.py` (única fuente de verdad)
y correr el comando de arriba. Las copias ya instaladas detectan la versión nueva y se
actualizan solas.

El `.sha256` es lo que verifican tanto `install.ps1` como el actualizador de la app antes
de ejecutar nada: como el binario no está firmado, es la única garantía de integridad
disponible.

El repositorio es público, lo cual además cubre la obligación de la GPL que arrastra
PyQt6: quien recibe el binario tiene derecho al código, y GitHub adjunta el fuente de
cada tag automáticamente.

## Para desarrolladores

### Componentes

| Archivo | Propósito |
|---|---|
| `main.py` | Entry point: interfaz PyQt6, hilos de trabajo, ciclo de vida. |
| `version.py` | Única fuente de verdad de versión e identidad de la app. |
| `paths.py` | Rutas vía Known Folders de Windows (efecto de borde: fija `HF_HOME`). |
| `hardware.py` | Detección del equipo y elección del motor. Toda la lógica adaptativa vive acá. |
| `transcriber.py` | Motor Whisper con degradación automática. |
| `subtitles.py` | Formato de marcas de tiempo y SRT. Puro, sin dependencias. |
| `audio_capture.py` | Grabación loopback WASAPI y micrófono (pyaudiowpatch). |
| `state.py` | Migraciones de layout, numeración de sesiones, limpieza de modelos. |
| `config.py` | Idiomas, formatos de audio, FFmpeg, claves de ajustes. |
| `utils.py` | Helpers sin dependencias externas. |
| `selftest.py` | Autodiagnóstico del binario congelado (`--selftest`). |
| `build.py` | Empaquetado: FFmpeg + PyInstaller + Inno Setup. |
| `Transcriber.spec` | Spec de PyInstaller (onedir, sin UPX, con recurso de versión). |
| `Transcriber.iss` | Instalador Inno Setup, por usuario y sin UAC. |
| `tests/` | Pruebas de las funciones puras (no requieren el stack completo). |

### Setup local (Windows)

```cmd
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pythonw main.py
```

Necesitás FFmpeg en el PATH (`winget install Gyan.FFmpeg`) si no hacés el build.
`start.bat` automatiza todos esos pasos.

### Pruebas

```cmd
venv\Scripts\python -m unittest discover -s tests -t .
```

No requieren PyQt6 ni faster-whisper: cubren las funciones puras (formato SRT,
saneado de nombres, escalera de modelos, numeración de sesiones, limpieza de cache).

### Empaquetar

El build **debe correr en Windows**: PyInstaller no hace cross-compilation y
`pyaudiowpatch` es Windows-only. Si desarrollás desde WSL, copiá el árbol a una ruta
nativa (`C:\dev\transcriber`) antes de compilar; no compiles sobre `\\wsl$\`.

```cmd
winget install Python.Python.3.12
winget install JRSoftware.InnoSetup

python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python build.py --clean --installer --strict
```

Salida: `installer\Transcriber-Setup-vX.Y.Z-windows-x64.exe`.

`--strict` convierte en error cualquier degradación silenciosa del build (no se pudo
limpiar, no se pudo promover, falta un artefacto necesario). Usalo siempre que el
resultado se vaya a distribuir.

Antes de publicar, verificá el binario congelado:

```cmd
dist\Transcriber\Transcriber.exe --selftest
```

Comprueba lo que un build verde igual puede tener roto: `onnxruntime` y los assets
del VAD, las DLL de FFmpeg de PyAV, y la presencia de FFmpeg. Devuelve 0 si todo
está bien y deja el detalle en `%LOCALAPPDATA%\Transcriber\selftest.log`.

Para congelar el entorno del build: `python build.py --lock` genera
`requirements.lock.txt`.

### Configuración

Los ajustes del usuario (idioma, fuente, modelo, geometría) van a
`%LOCALAPPDATA%\Transcriber\settings.ini`. Las claves están centralizadas en
`config.py`.

`TRANSCRIBER_MODEL` fuerza un modelo concreto y salta la selección automática (útil
para depurar).

### Notas técnicas

- **PyInstaller onedir** (no onefile): arranca rápido y evita el extractor
  automático, que dispara falsos positivos de antivirus.
- **Rutas por Known Folder**: `SHGetKnownFolderPath(FOLDERID_Documents)` en vez de
  `%USERPROFILE%\Documents`. Con OneDrive Backup activo, la segunda apunta a una
  carpeta huérfana y el usuario no encuentra sus transcripciones.
- **`HF_HOME`** se fija antes de importar `faster_whisper`, para que los modelos
  queden bajo el control de la app.
- **Selección de motor**: `hardware.engine_candidates()` arma la escalera
  GPU → GPU más chica → CPU y `Transcriber.load_model()` la recorre hasta que una
  configuración carga de verdad. `get_cuda_device_count() > 0` solo consulta el
  driver, así que no alcanza como detección.
- **CUDA**: las DLL van dentro de la carpeta de `ctranslate2` (`destdir` en el spec)
  porque CTranslate2 solo hace `os.add_dll_directory()` sobre su propio directorio.
- **INT8 en GPU**: no usar. CTranslate2 4.6.2 lo deshabilitó en Blackwell (sm_120).
- **`AppUserModelID`** vía `ctypes` para que la barra de tareas muestre identidad
  propia y no agrupe bajo Python.
- **Instancia única** con `QLocalServer`, por usuario (sesiones de Escritorio Remoto).
- **Atajo global** con `RegisterHotKey` y un filtro de eventos nativo; `QShortcut`
  solo funciona con la ventana enfocada.
- **Bandeja**: cerrar la ventana minimiza; se sale de verdad desde el menú del icono.

### Limitaciones conocidas

- Solo Windows: `pyaudiowpatch` (loopback WASAPI) es Windows-only.
- Sin firma de código: SmartScreen advierte la primera vez.
- Sin actualización automática.
- El modelo se descarga de HuggingFace en la primera ejecución.

### Reportar problemas

Ver `SECURITY.md` para vulnerabilidades. Para bugs y features, el issue tracker del
repositorio. Adjuntá `%LOCALAPPDATA%\Transcriber\transcriber.log` y la salida de
`Transcriber.exe --selftest`.
