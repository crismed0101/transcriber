<#
.SYNOPSIS
    Prepara el entorno y compila Transcriber, todo en un paso.

.DESCRIPTION
    Instala lo que falte (Git, Python, Inno Setup), clona o actualiza el codigo,
    arma el entorno virtual, compila el instalador y lo verifica.

    Pensado para invocarse en una sola linea:

        irm https://raw.githubusercontent.com/crismed0101/transcriber/master/build.ps1 | iex

    Con opciones:

        & ([scriptblock]::Create((irm https://raw.githubusercontent.com/crismed0101/transcriber/master/build.ps1))) -Publish

    Es idempotente: si ya esta todo instalado, solo actualiza el codigo y compila.
    Volver a ejecutarlo despues de cada cambio es lo esperado.

.PARAMETER Run
    No compila: prepara el entorno y abre la app desde el codigo. Es lo mas rapido
    para probar un cambio.

.PARAMETER Publish
    Despues de compilar y verificar, publica el release en GitHub. Requiere `gh`
    autenticado.

.PARAMETER Path
    Donde dejar el codigo. Por defecto C:\dev\transcriber.
#>
[CmdletBinding()]
param(
    [switch]$Run,
    [switch]$Publish,
    [string]$Path = "C:\dev\transcriber"
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/crismed0101/transcriber.git"

function Write-Paso  { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "    $m" -ForegroundColor Green }
function Write-Aviso { param($m) Write-Host "    $m" -ForegroundColor Yellow }

function Update-Path {
    # winget agrega los programas al PATH del registro, pero la sesion actual
    # sigue con el PATH viejo. Sin esto habria que cerrar y reabrir PowerShell
    # entre paso y paso, que es justo lo que este script viene a evitar.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Test-Tool { param($Name) [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Test-InnoSetup {
    # Inno Setup NO agrega ISCC.exe al PATH, asi que hay que buscarlo donde queda
    # segun el tipo de instalacion. build.py usa exactamente las mismas rutas.
    $rutas = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    return [bool]($rutas | Where-Object { $_ -and (Test-Path $_) })
}

function Install-Tool {
    param($Name, $WingetId, [scriptblock]$Test)
    if (& $Test) {
        Write-Ok "$Name ya esta instalado"
        return
    }
    Write-Ok "Instalando $Name ..."
    winget install --id $WingetId --silent --accept-source-agreements --accept-package-agreements | Out-Null
    Update-Path
    if (-not (& $Test)) {
        throw "$Name se instalo pero no se lo encuentra. Cerra y volve a abrir PowerShell, y ejecuta el script de nuevo."
    }
    Write-Ok "$Name listo"
}

# ── Requisitos del equipo ──
Write-Paso "Verificando el equipo"

if ([Environment]::OSVersion.Version.Major -lt 10) {
    throw "Hace falta Windows 10 o superior."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Hace falta un Windows de 64 bits."
}
if (-not (Test-Tool "winget")) {
    throw ("No se encontro winget (el instalador de aplicaciones de Windows). " +
           "Actualiza 'Instalador de aplicacion' desde la Microsoft Store y volve a intentar.")
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Ok "Windows de 64 bits con winget disponible"

# ── Herramientas ──
Write-Paso "Preparando las herramientas"
Update-Path
Install-Tool "Git"         "Git.Git"             { Test-Tool "git" }
Install-Tool "Python 3.12" "Python.Python.3.12"  { Test-Tool "python" }
if (-not $Run) {
    Install-Tool "Inno Setup" "JRSoftware.InnoSetup" { Test-InnoSetup }
}
if ($Publish) {
    Install-Tool "GitHub CLI" "GitHub.cli" { Test-Tool "gh" }
    gh auth status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Aviso "GitHub CLI no esta autenticado. Se va a abrir el inicio de sesion."
        gh auth login
        if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar sesion en GitHub." }
    }
    Write-Ok "GitHub CLI autenticado"
}

# ── Codigo ──
Write-Paso "Obteniendo el codigo"
if (Test-Path (Join-Path $Path ".git")) {
    Push-Location $Path
    Write-Ok "Ya existe en $Path; actualizando ..."
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw "No se pudo actualizar el repositorio. Revisa si tenes cambios locales sin guardar."
    }
} else {
    if (Test-Path $Path) {
        throw "$Path ya existe y no es un repositorio git. Borralo o elegi otra ruta con -Path."
    }
    Write-Ok "Clonando en $Path ..."
    git clone --quiet $RepoUrl $Path
    if ($LASTEXITCODE -ne 0) { throw "No se pudo clonar el repositorio." }
    Push-Location $Path
}

try {
    # version.py no importa nada, asi que se puede leer antes de armar el entorno.
    $version = (python -c "import version; print(version.__version__)")
    Write-Ok "Transcriber $version en $Path"

    # ── Entorno virtual ──
    Write-Paso "Preparando las dependencias"
    if (-not (Test-Path "venv\Scripts\python.exe")) {
        Write-Ok "Creando el entorno virtual ..."
        python -m venv venv
        if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual." }
    }

    # Comprobar antes de instalar: pip tarda minutos aunque no haya nada que hacer.
    & "venv\Scripts\python.exe" -c "import PyQt6, faster_whisper, onnxruntime, av" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Ok "Instalando dependencias (son ~2 GB, puede tardar varios minutos) ..."
        & "venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
        & "venv\Scripts\pip.exe" install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de dependencias." }
    }
    Write-Ok "Dependencias listas"

    # ── Pruebas ──
    Write-Paso "Corriendo las pruebas"
    & "venv\Scripts\python.exe" -m unittest discover -s tests -t . 2>&1 | Select-Object -Last 3
    if ($LASTEXITCODE -ne 0) { throw "Hay pruebas que fallan; no se compila." }

    # ── Modo prueba rapida ──
    if ($Run) {
        Write-Paso "Abriendo Transcriber"
        Write-Aviso "La primera vez descarga el modelo de voz; puede tardar."
        # Ruta absoluta: Start-Process resuelve contra el directorio del proceso,
        # que Push-Location no cambia.
        Start-Process -FilePath (Resolve-Path "venv\Scripts\pythonw.exe") `
                      -ArgumentList "main.py" -WorkingDirectory $PWD
        Write-Ok "Listo. La app se esta abriendo."
        return
    }

    # ── Compilacion ──
    Write-Paso "Compilando el instalador"
    Write-Aviso "Esto tarda varios minutos y ocupa unos 3 GB temporales."
    & "venv\Scripts\python.exe" build.py --clean --installer --strict --lock
    if ($LASTEXITCODE -ne 0) { throw "Fallo la compilacion." }

    # ── Verificacion ──
    Write-Paso "Verificando el ejecutable"
    & "dist\Transcriber\Transcriber.exe" --selftest
    if ($LASTEXITCODE -ne 0) {
        Write-Host (Get-Content "$env:LOCALAPPDATA\Transcriber\selftest.log" -ErrorAction SilentlyContinue)
        throw "El ejecutable no paso la verificacion. No se publica nada."
    }
    Write-Ok "El ejecutable funciona"

    # ── Publicacion ──
    if ($Publish) {
        Write-Paso "Publicando la version $version en GitHub"
        & "venv\Scripts\python.exe" build.py --publish --strict --skip-ffmpeg
        if ($LASTEXITCODE -ne 0) { throw "Fallo la publicacion." }
    }

    # ── Resumen ──
    $instalador = Get-ChildItem "installer\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    Write-Host ""
    Write-Ok "TODO LISTO"
    if ($instalador) {
        $mb = [math]::Round($instalador.Length / 1MB, 0)
        Write-Host "    Instalador: $($instalador.FullName) ($mb MB)" -ForegroundColor Green
    }
    if ($Publish) {
        Write-Host "    Publicado en: https://github.com/crismed0101/transcriber/releases/tag/v$version" -ForegroundColor Green
        Write-Host ""
        Write-Host "    Tus colegas ya pueden instalarlo con:" -ForegroundColor DarkGray
        Write-Host "    irm https://raw.githubusercontent.com/crismed0101/transcriber/master/install.ps1 | iex" -ForegroundColor White
    } else {
        Write-Host ""
        Write-Host "    Para publicarlo en GitHub, volve a ejecutar con -Publish" -ForegroundColor DarkGray
    }
}
finally {
    Pop-Location
}
