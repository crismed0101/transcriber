@echo off
rem Arranque para desarrollo: prepara el entorno y lanza la app desde el codigo.
rem Para generar el ejecutable distribuible, usar:  python build.py --installer
title Transcriber (desarrollo)
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado.
    echo Instalalo con:  winget install Python.Python.3.12
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [1/3] Creando entorno virtual...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Entorno virtual OK
)

venv\Scripts\python.exe -c "import PyQt6, faster_whisper" >nul 2>&1
if errorlevel 1 (
    echo [2/3] Instalando dependencias, esto tarda unos minutos...
    venv\Scripts\pip.exe install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Dependencias OK
)

rem La app usa bin\ffmpeg.exe si existe; si no, el del PATH del sistema.
if exist "bin\ffmpeg.exe" (
    echo [3/3] FFmpeg OK ^(bin\ffmpeg.exe^)
) else (
    where ffmpeg >nul 2>&1
    if errorlevel 1 (
        echo [3/3] Instalando FFmpeg...
        winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
        echo.
        echo FFmpeg instalado. Cerra esta ventana y volve a ejecutar start.bat.
        pause
        exit /b 0
    ) else (
        echo [3/3] FFmpeg OK ^(PATH del sistema^)
    )
)

echo.
echo Iniciando Transcriber...
start "" venv\Scripts\pythonw.exe main.py
