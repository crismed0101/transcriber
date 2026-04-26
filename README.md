# Transcriber

Aplicación de escritorio (Python, Windows) para captura y transcripción de audio en tiempo real.

## Componentes

| Archivo | Propósito |
|---|---|
| `main.py` | Punto de entrada de la aplicación. |
| `audio_capture.py` | Captura el audio del sistema o micrófono. |
| `transcriber.py` | Procesa el audio capturado y produce transcripción de texto. |
| `config.py` | Configuración (rutas, modelo, parámetros). |
| `start.bat` | Script de inicio para Windows. |
| `requirements.txt` | Dependencias de Python. |

## Setup local (Windows)

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecutar

```cmd
start.bat
```

O directamente:

```cmd
python main.py
```

## Configuración

La configuración va en `config.py`. Ver el archivo para los parámetros disponibles. **No commitear secretos** — usar variables de entorno o un `.env` (ya está en `.gitignore`).

## Reportar bugs / solicitar features

Ver `SECURITY.md` para reportes de vulnerabilidades. Para bugs y features usar el issue tracker del repo.
