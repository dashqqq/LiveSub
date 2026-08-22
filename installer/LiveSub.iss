#define AppName "LiveSub"
#define AppVersion "0.1.0"
#ifndef PayloadDir
  #define PayloadDir "..\dist\payload"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{4AA50A15-79BE-4557-AED4-A96DC7C056BB}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=LiveSub
DefaultDirName={localappdata}\Programs\LiveSub
DefaultGroupName=LiveSub
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=LiveSub-Setup
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
SetupIconFile=..\assets\branding\livesub.ico
UninstallDisplayIcon={app}\livesub.exe
UninstallDisplayName=LiveSub
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=LiveSub Windows Installer
VersionInfoCompany=
VersionInfoOriginalFileName=LiveSub-Setup.exe
VersionInfoProductName=LiveSub
VersionInfoProductVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LiveSub"; Filename: "{app}\livesub.exe"; Parameters: "desktop --start"; WorkingDir: "{app}"
Name: "{autodesktop}\LiveSub"; Filename: "{app}\livesub.exe"; Parameters: "desktop --start"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\livesub.exe"; Parameters: "desktop --start"; WorkingDir: "{app}"; Description: "Launch LiveSub"; Flags: nowait postinstall skipifsilent
