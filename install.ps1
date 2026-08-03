<#
.SYNOPSIS
    Instala la ultima version de Transcriber desde GitHub Releases.

.DESCRIPTION
    Descarga el instalador mas reciente, verifica su integridad y lo ejecuta.
    Pensado para invocarse en una sola linea:

        irm https://raw.githubusercontent.com/crismed0101/transcriber/main/install.ps1 | iex

    Requiere que el repositorio y sus releases sean publicos. Si el repositorio es
    privado, hay que exportar un token antes de ejecutar:

        $env:GITHUB_TOKEN = "ghp_..."

.PARAMETER Silent
    Instala sin mostrar el asistente (util para instalar en varias PC).

.PARAMETER Version
    Instala una version concreta (por ejemplo "v1.1.0") en vez de la ultima.
#>
[CmdletBinding()]
param(
    [switch]$Silent,
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"
$Repo = "crismed0101/transcriber"
$AppName = "Transcriber"

function Write-Paso  { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "    $m" -ForegroundColor Green }
function Write-Aviso { param($m) Write-Host "    $m" -ForegroundColor Yellow }

# ── Requisitos ──
Write-Paso "Verificando el equipo"

if ([Environment]::OSVersion.Version.Major -lt 10) {
    throw "$AppName necesita Windows 10 o superior."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "$AppName solo funciona en Windows de 64 bits."
}
# TLS 1.2 explicito: Windows 10 sin actualizar puede negociar TLS 1.0 y GitHub lo rechaza.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Ok "Windows $([Environment]::OSVersion.Version.Major) de 64 bits"

# ── Buscar el release ──
Write-Paso "Buscando la ultima version publicada"

$headers = @{ "User-Agent" = "$AppName-installer"; "Accept" = "application/vnd.github+json" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }

$apiUrl = if ($Version -eq "latest") {
    "https://api.github.com/repos/$Repo/releases/latest"
} else {
    "https://api.github.com/repos/$Repo/releases/tags/$Version"
}

try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 404) {
        throw ("No se encontro el release. Si el repositorio es privado, " +
               'defini un token antes de ejecutar:  $env:GITHUB_TOKEN = "ghp_..."')
    }
    throw "No se pudo consultar GitHub: $($_.Exception.Message)"
}

$asset = $release.assets | Where-Object { $_.name -like "*Setup*.exe" } | Select-Object -First 1
if (-not $asset) {
    throw "El release $($release.tag_name) no incluye un instalador (*Setup*.exe)."
}

$sizeMb = [math]::Round($asset.size / 1MB, 0)
Write-Ok "$($release.tag_name) — $($asset.name) ($sizeMb MB)"

# ── Descargar ──
$dest = Join-Path $env:TEMP $asset.name
Write-Paso "Descargando ($sizeMb MB, puede tardar varios minutos)"

try {
    # ProgressPreference silenciado: la barra de Invoke-WebRequest hace la descarga
    # varias veces mas lenta en archivos grandes.
    $prevProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest -Headers $headers
} finally {
    $ProgressPreference = $prevProgress
}
Write-Ok "Descargado en $dest"

# ── Verificar integridad ──
$shaAsset = $release.assets | Where-Object { $_.name -eq "$($asset.name).sha256" } | Select-Object -First 1
if ($shaAsset) {
    Write-Paso "Verificando integridad"
    $esperado = ((Invoke-WebRequest -Uri $shaAsset.browser_download_url -Headers $headers).Content -split '\s+')[0]
    $real = (Get-FileHash $dest -Algorithm SHA256).Hash
    if ($real -ne $esperado.Trim().ToUpper() -and $real -ne $esperado.Trim()) {
        Remove-Item $dest -Force -ErrorAction SilentlyContinue
        throw "El archivo descargado no coincide con su firma SHA256. Se elimino por seguridad."
    }
    Write-Ok "SHA256 correcto"
} else {
    Write-Aviso "El release no publica SHA256; se omite la verificacion."
}

# ── Instalar ──
Write-Paso "Instalando"
Write-Aviso "Windows puede advertir que el editor es desconocido (la app no esta firmada)."

$args = if ($Silent) { @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") } else { @() }
$proc = Start-Process -FilePath $dest -ArgumentList $args -Wait -PassThru

# 0 = ok, 1602 = el usuario cancelo el asistente
if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 1602) {
    throw "El instalador termino con el codigo $($proc.ExitCode)."
}

Remove-Item $dest -Force -ErrorAction SilentlyContinue

if ($proc.ExitCode -eq 1602) {
    Write-Aviso "Instalacion cancelada por el usuario."
    return
}

Write-Host ""
Write-Ok "$AppName $($release.tag_name) instalado."
Write-Host "    Buscalo en el menu Inicio como '$AppName'." -ForegroundColor Green
Write-Host "    Tus transcripciones van a quedar en: $([Environment]::GetFolderPath('MyDocuments'))\$AppName" -ForegroundColor DarkGray
