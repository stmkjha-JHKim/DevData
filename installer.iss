; Inno Setup script for OraPulse -- wraps the folder distribution
; (dist\OraPulse_ver_<VERSION>\, produced by build-folder.ps1) in a normal
; Windows installer: Start Menu / optional Desktop shortcut, an uninstaller
; registered in "Add or Remove Programs", and upgrade-in-place on top of a
; previous install (same AppId across versions).
;
; MyAppVersion and SourceDir are passed in from build-installer.ps1 via
; /D command-line defines (ISCC.exe installer.iss /DMyAppVersion=1.0007
; /DSourceDir=...\dist\OraPulse_ver_1.0007) rather than hardcoded here, so
; this file never needs editing just because VERSION changed.
;
; Machine-wide install under Program Files (x86) (DefaultDirName below),
; which requires admin/UAC (PrivilegesRequired=admin). Note: data\ --
; created next to OraPulse.exe at first run, see paths.py's app_dir() --
; is NOT relocated to a per-user-writable folder for this install location,
; by explicit choice; a standard (non-admin) user will not be able to save
; favorites/report history unless the app is run elevated or the install
; folder's permissions are opened up separately.
;
; data\ is deliberately not part of {#SourceDir} (it doesn't exist in the
; build output -- created at first run) and is therefore never touched by
; install or uninstall: upgrading in place leaves existing favorites/
; report history alone, and uninstalling leaves them behind instead of
; silently deleting a user's saved connections.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\OraPulse"
#endif

[Setup]
AppId={{064E520D-2FDC-42AE-A8EE-21C9F954723E}
AppName=OraPulse
AppVersion={#MyAppVersion}
AppPublisher=OraPulse
DefaultDirName={commonpf32}\OraPulse_Windows_x86
DefaultGroupName=OraPulse
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=dist
OutputBaseFilename=OraPulse-Setup_ver_{#MyAppVersion}
SetupIconFile=favicon.ico
UninstallDisplayIcon={app}\OraPulse.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\OraPulse"; Filename: "{app}\OraPulse.exe"
Name: "{group}\{cm:UninstallProgram,OraPulse}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OraPulse"; Filename: "{app}\OraPulse.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OraPulse.exe"; Description: "{cm:LaunchProgram,OraPulse}"; Flags: nowait postinstall skipifsilent
