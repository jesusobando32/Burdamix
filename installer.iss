; Inno Setup recipe for the Burdamix installer. Build it with build_installer.bat (after build_exe.bat).
#define AppName "Burdamix"
#ifndef AppVersion
  #define AppVersion "0.2.0-pre"
#endif

[Setup]
; Never change this id: it is how Windows recognises an older Burdamix when updating or uninstalling.
AppId={{B7D3F2A1-5C4E-4A9B-9E21-6D8F0A3C7E15}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Jesus Obando
AppPublisherURL=https://github.com/jesusobando32/Burdamix
AppSupportURL=https://github.com/jesusobando32/Burdamix/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Installs for the current user only: no administrator password, nothing outside the user's folders.
PrivilegesRequired=lowest
OutputDir=build_out
OutputBaseFilename=Burdamix-Setup
SetupIconFile=assets\burdamix.ico
UninstallDisplayIcon={app}\Burdamix.exe
LicenseFile=LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; portable.txt is left out on purpose: its presence switches the program to portable mode.
Source: "build_out\dist\Burdamix\*"; DestDir: "{app}"; Excludes: "portable.txt"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Burdamix.exe"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Burdamix.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Burdamix.exe"; Description: "Abrir {#AppName} ahora"; Flags: nowait postinstall skipifsilent

; Uninstalling removes the program only. The user's songs (Música\Burdamix) and the Spotify setup
; (%LOCALAPPDATA%\Burdamix) are theirs and stay.
