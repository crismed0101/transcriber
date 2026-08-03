<#
.SYNOPSIS
    Prepara el entorno y compila Transcriber, todo en un paso.

.DESCRIPTION
    Instala lo que falte (Git, Python, Inno Setup), clona o actualiza el codigo,
    arma el entorno virtual, corre las pruebas, compila el instalador y lo verifica.

    Pensado para invocarse en una sola linea:

        irm https://raw.githubusercontent.com/crismed0101/transcriber/master/build.ps1 | iex

    Con opciones:

        & ([scriptblock]::Create((irm https://raw.githubusercontent.com/crismed0101/transcriber/master/build.ps1))) -Publish

    Es idempotente: si ya esta todo instalado, solo actualiza el codigo y compila.
    Volver a ejecutarlo despues de cada cambio es lo esperado.

    Compatible con Windows PowerShell 5.1 (el que trae Windows) y con PowerShell 7.

.PARAMETER Run
    No compila: prepara el entorno y abre la app desde el codigo. Es lo mas rapido
    para probar un cambio.

.PARAMETER Publish
    Despues de compilar y verificar, publica el release en GitHub. Requiere `gh`
    autenticado; si no lo esta, el script abre el inicio de sesion.

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

function Invoke-Native {
    <#
        Ejecuta un programa externo y devuelve su codigo de salida.

        Existe por un comportamiento de Windows PowerShell 5.1: con
        $ErrorActionPreference = "Stop", CUALQUIER cosa que un programa escriba en
        la salida de error se vuelve un error fatal, aunque haya terminado bien. Y
        escriben ahi de forma rutinaria pip (avisos), git (progreso), unittest (los
        resultados) y PyInstaller.

        Aca se baja la preferencia mientras corre el programa y se decide por el
        codigo de salida, que es lo unico que de verdad indica si fallo.
    #>
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Arguments = @(),
        [switch]$IgnoreExitCode,
        [string]$ErrorMessage
    )
    $previo = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # La salida se manda a la consola con Write-Host y NO al flujo de la
        # funcion: si no, quien haga `$x = Invoke-Native ...` recibiria el texto
        # del programa mezclado con el codigo de salida.
        # El 2>&1 unifica ambos flujos para que los avisos normales de pip o git no
        # se vean como errores rojos.
        & $File @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        $codigo = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previo
    }
    if (-not $IgnoreExitCode -and $codigo -ne 0) {
        if ($ErrorMessage) { throw $ErrorMessage }
        throw "Fallo: $File $($Arguments -join ' ') (codigo $codigo)"
    }
    return $codigo
}

function Update-Path {
    # winget agrega los programas al PATH del registro, pero la sesion actual sigue
    # con el PATH viejo. Sin esto habria que cerrar y reabrir PowerShell entre paso
    # y paso, que es justo lo que este script viene a evitar.
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
    # winget devuelve codigos distintos de cero en situaciones que no son error
    # (por ejemplo, "ya estaba instalado"). Lo que decide es el Test de abajo.
    Invoke-Native -File "winget" -IgnoreExitCode -Arguments @(
        "install", "--id", $WingetId, "--silent",
        "--accept-source-agreements", "--accept-package-agreements"
    ) | Out-Null
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
    $auth = Invoke-Native -File "gh" -Arguments @("auth", "status") -IgnoreExitCode
    if ($auth -ne 0) {
        Write-Aviso "GitHub CLI no esta autenticado. Se abre el inicio de sesion."
        Invoke-Native -File "gh" -Arguments @("auth", "login") `
                      -ErrorMessage "No se pudo iniciar sesion en GitHub." | Out-Null
    }
    Write-Ok "GitHub CLI autenticado"
}

# ── Codigo ──
Write-Paso "Obteniendo el codigo"
if (Test-Path (Join-Path $Path ".git")) {
    Push-Location $Path
    Write-Ok "Ya existe en $Path; actualizando ..."
    try {
        Invoke-Native -File "git" -Arguments @("pull", "--ff-only") -ErrorMessage (
            "No se pudo actualizar el repositorio. Puede que tengas cambios locales " +
            "sin guardar en $Path.") | Out-Null
    } catch {
        Pop-Location
        throw
    }
} else {
    if (Test-Path $Path) {
        throw "$Path ya existe y no es un repositorio git. Borralo o elegi otra ruta con -Path."
    }
    Write-Ok "Clonando en $Path ..."
    Invoke-Native -File "git" -Arguments @("clone", "--quiet", $RepoUrl, $Path) `
                  -ErrorMessage "No se pudo clonar el repositorio." | Out-Null
    Push-Location $Path
}

try {
    # version.py no importa nada, asi que se puede leer antes de armar el entorno.
    # Aca hace falta la SALIDA del programa, no su codigo, asi que no se usa
    # Invoke-Native; se baja la preferencia a mano por el mismo motivo.
    $previo = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $version = (& python -c "import version; print(version.__version__)")
    $ErrorActionPreference = $previo
    if (-not $version) { throw "No se pudo leer la version desde version.py" }
    Write-Ok "Transcriber $version en $Path"

    # ── Entorno virtual ──
    Write-Paso "Preparando las dependencias"
    $venvPython = "venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Ok "Creando el entorno virtual ..."
        Invoke-Native -File "python" -Arguments @("-m", "venv", "venv") `
                      -ErrorMessage "No se pudo crear el entorno virtual." | Out-Null
    }

    # Comprobar antes de instalar: pip tarda minutos aunque no haya nada que hacer.
    # Que este import falle es lo NORMAL la primera vez, no un error del script.
    $tiene = Invoke-Native -File $venvPython -IgnoreExitCode `
                           -Arguments @("-c", "import PyQt6, faster_whisper, onnxruntime, av")
    if ($tiene -ne 0) {
        Write-Ok "Instalando dependencias (son ~2 GB, puede tardar varios minutos) ..."
        Invoke-Native -File $venvPython -IgnoreExitCode `
                      -Arguments @("-m", "pip", "install", "--quiet", "--upgrade", "pip") | Out-Null
        Invoke-Native -File "venv\Scripts\pip.exe" `
                      -Arguments @("install", "-r", "requirements.txt") `
                      -ErrorMessage "Fallo la instalacion de dependencias." | Out-Null
    }
    Write-Ok "Dependencias listas"

    # ── Pruebas ──
    Write-Paso "Corriendo las pruebas"
    Invoke-Native -File $venvPython `
                  -Arguments @("-m", "unittest", "discover", "-s", "tests", "-t", ".") `
                  -ErrorMessage "Hay pruebas que fallan; no se compila." | Out-Null

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
    Invoke-Native -File $venvPython `
                  -Arguments @("build.py", "--clean", "--installer", "--strict", "--lock") `
                  -ErrorMessage "Fallo la compilacion." | Out-Null

    # ── Verificacion ──
    Write-Paso "Verificando el ejecutable"
    $selftest = Invoke-Native -File "dist\Transcriber\Transcriber.exe" `
                              -Arguments @("--selftest") -IgnoreExitCode
    if ($selftest -ne 0) {
        Get-Content "$env:LOCALAPPDATA\Transcriber\selftest.log" -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        throw "El ejecutable no paso la verificacion. No se publica nada."
    }
    Write-Ok "El ejecutable funciona"

    # ── Publicacion ──
    if ($Publish) {
        Write-Paso "Publicando la version $version en GitHub"
        Invoke-Native -File $venvPython `
                      -Arguments @("build.py", "--publish", "--strict", "--skip-ffmpeg") `
                      -ErrorMessage "Fallo la publicacion." | Out-Null
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
        Write-Host "    Publicado: https://github.com/crismed0101/transcriber/releases/tag/v$version" -ForegroundColor Green
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
