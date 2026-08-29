#define MyAppName "SysDeck"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SysDeck"
#define MyAppExeName "SysDeck.exe"

[Setup]
AppId={{6A75DE9D-7F0A-4BBE-97AC-C58F5C8C1477}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=SysDeck-Setup-{#MyAppVersion}
SetupIconFile=..\assets\sysdeck_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupArchitecture=x64
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=SysDeck Windows system monitoring and file utility
VersionInfoCopyright=Copyright (C) 2026 SysDeck

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\SysDeck\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SysDeck"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\SysDeck"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch SysDeck"; Flags: nowait postinstall skipifsilent
