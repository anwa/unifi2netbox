; Inno Setup script for the per-user unifi2netbox installer (Windows 11).
;
; Build with tools/build_windows.ps1, which runs PyInstaller first and passes
; the version from pyproject.toml:
;   ISCC.exe /DAppVersion=0.11.0 packaging\windows\unifi2netbox.iss
;
; Installs the PyInstaller one-folder build into
; %LOCALAPPDATA%\Programs\unifi2netbox without administrator rights. The
; configuration, snapshots and write history live in %LOCALAPPDATA%\unifi2netbox
; (platformdirs) and are never touched by setup or uninstall, so upgrades and
; reinstalls keep them. The AppId must never change: it ties upgrades together.

#ifndef AppVersion
  #error AppVersion is required (ISCC /DAppVersion=x.y.z).
#endif

#define AppName "unifi2netbox"
#define AppExe "unifi2netbox.exe"
#define RepoRoot "..\.."

[Setup]
AppId={{5935892F-657C-4B50-B3D5-DD538AE67361}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=unifi2netbox
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} setup
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#RepoRoot}\dist\installer
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile={#RepoRoot}\src\unifi2netbox\resources\unifi2netbox.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
LicenseFile={#RepoRoot}\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove files of the previous build so an upgrade never mixes versions.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#RepoRoot}\dist\unifi2netbox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "unifi2netbox.desktop"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; AppUserModelID: "unifi2netbox.desktop"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only the program folder. %LOCALAPPDATA%\unifi2netbox (settings, tokens,
; snapshots, write history) is user data and stays; see docs/DEPLOYMENT.md.
Type: filesandordirs; Name: "{app}"
