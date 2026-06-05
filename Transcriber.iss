; ============================================================================
;  Instalador de Transcriber  (Inno Setup)
;  Genera:  installer\Transcriber-Setup.exe
;  Tipo:    instalacion POR-USUARIO, sin permisos de administrador (UAC).
;
;  Compilar:
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" Transcriber.iss
;  o, mas comodo:
;     python build.py --installer      (compila el .exe y luego el instalador)
;
;  Que hace al instalar:
;   - Copia la app a  %LOCALAPPDATA%\Programs\Transcriber\
;   - Crea acceso directo en Menu Inicio (y opcionalmente Escritorio)
;   - Registra desinstalador en "Agregar o quitar programas"
;   - Ofrece iniciar la app al terminar
;
;  Datos del usuario (NO los toca el instalador ni el desinstalador):
;   - Transcripciones / audios -> Documents\Transcriber\   (los crea la app)
;   - Modelos / logs / settings -> %LOCALAPPDATA%\Transcriber\ (los crea la app)
;  Al desinstalar se conservan; nunca se borran las transcripciones del usuario.
; ============================================================================

#define AppName "Transcriber"
#define AppVersion "1.0.0"
#define AppPublisher "CrisMed"
#define AppExe "Transcriber.exe"

[Setup]
; AppId fijo: identifica la app para upgrades y desinstalacion. NO cambiar.
AppId={{A7F3C2E1-9B4D-4E6A-8C1F-2D5B7E9A3C04}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}

; --- Instalacion por-usuario, sin admin ---
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto

; --- Salida ---
OutputDir=installer
OutputBaseFilename=Transcriber-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

; --- Apariencia / compresion ---
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; --- Requisitos de plataforma (x64 + Windows 10+) ---
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Toda la carpeta onedir (Transcriber.exe + _internal\ + bin\), recursivo.
Source: "dist\Transcriber\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
