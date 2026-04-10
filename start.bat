@echo off
title Transcriber
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado.
    echo Descargalo de https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [1/3] Creando entorno virtual...
    python -m venv venv
) else (
    echo [1/3] Entorno virtual OK
)

venv\Scripts\python.exe -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo [2/3] Instalando dependencias, espera...
    venv\Scripts\pip.exe install -r requirements.txt
) else (
    echo [2/3] Dependencias OK
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [3/3] Instalando FFmpeg...
    winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    echo.
    echo FFmpeg instalado. Cierra esta ventana y ejecuta start.bat de nuevo.
    pause
    exit /b 0
) else (
    echo [3/3] FFmpeg OK
)

echo.
echo Iniciando Transcriber...
start "" venv\Scripts\pythonw.exe main.py
