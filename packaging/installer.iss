; Inno Setup Script for FastMirror
; Creates a lightweight, modern per-user Windows Setup wizard without requiring Admin elevation.

#ifndef AppVersion
#define AppVersion "1.2.2"
#endif

#define AppName "FastMirror"
#define AppPublisher "Rafael Savi"
#define AppURL "https://github.com/rafaelsavi/fast-mirror"
#define AppExeName "FastMirror.exe"

[Setup]
AppId={{D37E88BC-3430-4C9D-A3D2-FC9D2F3C89E1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=FastMirror-v{#AppVersion}-Windows-Setup
SetupIconFile=..\src\gui\app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=Local\FastMirror_SingleInstance,FastMirror_SingleInstance
CloseApplications=yes
CloseApplicationsFilter=FastMirror.exe,*
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Purge previous Python runtime binaries and distribution metadata on update to prevent stale file conflicts
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\FastMirror\*"; DestDir: "{app}"; Excludes: "portable.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\src\gui\app_icon.ico"; DestDir: "{app}\gui"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

