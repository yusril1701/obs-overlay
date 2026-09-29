; Inno Setup script for OBS Overlay.
;
; Builds a normal Windows installer around the PyInstaller one-dir output in
; packaging\dist\ObsOverlay. Run it after PyInstaller, never instead of it:
;
;   iscc /DAppVersion=1.1.0 packaging\installer.iss
;
; Notes on the choices made here
; ------------------------------
; per-user by default
;     PrivilegesRequired=lowest, with PrivilegesRequiredOverridesAllowed=dialog.
;     An overlay is a personal tool and needs nothing that requires admin, so
;     installing it should not require an administrator either. The dialog
;     still lets someone install for all users when they want to.
;
; no portable.txt
;     The application switches to portable mode when a file of that name sits
;     next to the executable. An installed copy must NOT have one, or it would
;     try to write profiles into Program Files.
;
; user data survives uninstall
;     Profiles and logs live in %APPDATA%\obs-overlay, which the installer
;     never creates and the uninstaller therefore never removes. Reinstalling
;     keeps every profile. The uninstaller offers to delete them explicitly.

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

#define AppName       "OBS Overlay"
#define AppPublisher  "obs-overlay contributors"
#define AppURL        "https://github.com/yusril1701/obs-overlay"
#define AppExeName    "ObsOverlay.exe"
#define SourceDir     "dist\ObsOverlay"

[Setup]
; Never change AppId: it is what lets an upgrade replace the previous install
; instead of sitting next to it.
AppId={{8D3F2A17-6C4B-4E59-9A0D-1B7E5C82F4A6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} installer

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=.\installer
OutputBaseFilename=ObsOverlay-{#AppVersion}-setup
SetupIconFile=obs-overlay.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}

; 64-bit only: SpoutGL, pywin32 and the PyInstaller bundle are all x64.
; Spelled "x64" rather than "x64compatible" on purpose — the newer name needs
; Inno Setup 6.3, and this has to compile on whatever the CI image ships.
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto

[Languages]
; English only. Inno Setup 6 does not ship an Indonesian translation — the one
; that exists is an unofficial download — and the application's own interface
; is in English anyway, so the two match. The documentation is in Indonesian
; and is installed alongside the program.
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
CreateDesktopIcon=Create a &desktop shortcut
StartWithWindows=Start {#AppName} when I sign in to Windows
StartupGroup=Startup:
LaunchApp=Launch {#AppName}
RemoveUserData=Also delete profiles, settings and logs?%n%nThey live in %1 and are kept by default, so a reinstall finds them again.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "{cm:StartWithWindows}"; GroupDescription: "{cm:StartupGroup}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable.txt"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md";           DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\CHANGELOG.md";        DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md";  DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\docs\OBS_SETUP.md";   DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\docs\TROUBLESHOOTING.md"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\docs\HOTKEYS.md";     DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}";                 Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} (test pattern)";  Filename: "{app}\{#AppExeName}"; Parameters: "--demo"; \
    Comment: "Start with the built-in test pattern, without OBS"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Autostart is always per-user: an overlay belongs to whoever is signed in,
; not to the machine. HKCU keeps it that way even in an all-users install.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller's one-dir layout gains __pycache__ directories the first time the
; app runs. They are not in [Files], so say so explicitly or {app} lingers.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: dirifempty;     Name: "{app}\docs"
Type: dirifempty;     Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;

  DataDir := ExpandConstant('{userappdata}\obs-overlay');
  if not DirExists(DataDir) then
    Exit;

  // Asked, never assumed: profiles are the user's own work, and a reinstall
  // is far more common than a permanent removal.
  if SuppressibleMsgBox(FmtMessage(CustomMessage('RemoveUserData'), [DataDir]),
                        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    DelTree(DataDir, True, True, True);
end;
