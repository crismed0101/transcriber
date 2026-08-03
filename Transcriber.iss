; ============================================================================
;  Instalador de Transcriber (Inno Setup)
;
;  Compilar:  python build.py --installer
;             (build.py le pasa SourceDistDir y AppVersion, asi que el instalador
;              NO puede empaquetar por error un build de una corrida anterior)
;
;  Instalacion POR USUARIO, sin permisos de administrador:
;   - Copia la app a  %LOCALAPPDATA%\Programs\Transcriber\
;   - Crea acceso directo en el Menu Inicio (y opcionalmente en el Escritorio)
;   - Registra el desinstalador en "Agregar o quitar programas"
;
;  Datos del usuario: el instalador NUNCA los toca, ni al instalar ni al desinstalar.
;   - Transcripciones y audios -> Documentos\Transcriber\      (los crea la app)
;   - Modelos, registro, ajustes -> %LOCALAPPDATA%\Transcriber\ (los crea la app)
; ============================================================================

#define AppName "Transcriber"
#define AppPublisher "CrisMed"
#define AppExe "Transcriber.exe"
#define AppUrl "https://github.com/crismed0101/transcriber"

; Estos dos los define build.py con /D. Los valores por defecto solo sirven para
; compilar el .iss a mano durante una prueba.
#ifndef SourceDistDir
  #define SourceDistDir "dist\Transcriber"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId fijo: identifica la app para actualizaciones y desinstalacion. NO cambiar.
AppId={{A7F3C2E1-9B4D-4E6A-8C1F-2D5B7E9A3C04}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases

; --- Instalacion por usuario, sin UAC ---
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto

; --- Salida ---
OutputDir=installer
OutputBaseFilename={#AppName}-Setup-v{#AppVersion}-windows-x64
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

; --- Metadata del propio instalador (el Explorador la muestra en Propiedades) ---
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

; --- Apariencia y compresion ---
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; Cierra la app si esta corriendo, en vez de pedir reiniciar Windows.
CloseApplications=yes
RestartApplications=no

; --- Requisitos: Windows 10+ de 64 bits ---
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Vaciar _internal y bin antes de copiar. Sin esto, al actualizar quedan DLL de la
; version anterior conviviendo con las nuevas, que es una fuente clasica de fallos
; imposibles de diagnosticar. No afecta los datos del usuario: viven fuera de {app}.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\bin"

[Files]
; Carpeta onedir completa (Transcriber.exe + _internal\ + bin\), recursiva.
Source: "{#SourceDistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
