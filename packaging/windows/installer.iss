#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "SPLICR Studio"
#define MyAppExeName "SPLICR Studio.exe"

[Setup]
AppId={{D39B3DFC-EA2E-4BE8-96EC-14D11D67D63C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=SGB
DefaultDirName={localappdata}\Programs\SPLICR Studio
DefaultGroupName=SPLICR Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=SPLICR-Studio-{#MyAppVersion}-Windows-x64-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoDescription=SPLICR Studio local speech production workspace

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\SPLICR Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SPLICR Studio"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\SPLICR Studio"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch SPLICR Studio"; Flags: nowait postinstall skipifsilent
