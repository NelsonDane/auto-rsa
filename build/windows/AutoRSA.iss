; AutoRSA.iss — Inno Setup script for the one-click Windows installer.
;
; Build the Nuitka standalone first (build.ps1), then compile this with
; Inno Setup (iscc.exe):
;     iscc build\windows\AutoRSA.iss
; Produces build\out\AutoRSA-Setup.exe.
;
; PER-USER, NO ADMIN, UNSIGNED:
; - PrivilegesRequired=lowest -> installs to %LOCALAPPDATA%, never prompts
;   for an administrator password (matches docs/TESTING_UNSIGNED_WINDOWS.md).
; - No [Setup] SignTool -> unsigned. A friend clicks through SmartScreen
;   with "More info -> Run anyway" (or Unblocks the download first).
; - User data (creds\) lives under the install dir and is preserved on
;   uninstall so a reinstall/update never wipes a friend's vault/license.

#define AppName "AutoRSA"
#define AppVersion "0.1.0"
#define AppExeName "AutoRSA.exe"
; The Nuitka --standalone output folder (from build.ps1).
#define DistDir "..\out\launcher.dist"

[Setup]
AppId={{7C6C4E2A-AUTORSA-4F1B-9C22-000000000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AutoRSA
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\out
OutputBaseFilename={#AppName}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Uninstall icon uses the app exe.
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Ship the whole Nuitka standalone folder.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch after install (no elevation).
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

; Preserve the user's encrypted vault, license token, ledger, and logs
; across uninstall/reinstall: creds\ is intentionally NOT listed in any
; [UninstallDelete], so Inno leaves it in place. (Nuitka --standalone has
; no PyInstaller-style _internal\ folder, so nothing to special-case here.)
