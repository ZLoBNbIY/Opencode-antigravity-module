#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif

[Setup]
AppId={{D8A77D35-0449-4719-AC3D-D2B42CE9DFBD}
AppName=AI HUB
AppVersion={#AppVersion}
AppPublisher=AI HUB
AppPublisherURL=https://github.com/ZLoBNbIY/Opencode-antigravity-module
AppUpdatesURL=https://github.com/ZLoBNbIY/Opencode-antigravity-module/releases
DefaultDirName={localappdata}\Programs\AntigravityHub
DefaultGroupName=AI HUB
UninstallDisplayIcon={app}\AntigravityHub.exe
OutputDir={#OutputRoot}
OutputBaseFilename=AntigravityHub-Setup-x64
SetupIconFile=..\..\gui-manager\icon.ico
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
Compression=lzma2/normal
SolidCompression=yes
AppMutex=Local\AntigravityHub.SingleInstance
CloseApplications=no
SetupLogging=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "opencode"; Description: "{cm:OpenCodeTask}"; Flags: unchecked

[CustomMessages]
english.OpenCodeTask=Create starter settings for OpenCode if missing (OpenCode itself is not included)
russian.OpenCodeTask=Создать отсутствующие настройки OpenCode (сам OpenCode не входит в установщик)
english.WebViewFailed=Microsoft Edge WebView2 Runtime could not be installed. Check your internet connection and try again.
russian.WebViewFailed=Не удалось установить Microsoft Edge WebView2 Runtime. Проверьте подключение к интернету и повторите установку.

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebViewBootstrap}"; Flags: dontcopy
Source: "..\..\config-templates\opencode.json"; DestDir: "{code:OpenCodeConfigDir}"; Flags: onlyifdoesntexist uninsneveruninstall; Tasks: opencode; Check: MissingOpenCodeConfig
Source: "..\..\config-templates\antigravity.json"; DestDir: "{code:OpenCodeConfigDir}"; Flags: onlyifdoesntexist uninsneveruninstall; Tasks: opencode; Check: OpenCodeProfileAvailable

[Icons]
Name: "{group}\AI HUB"; Filename: "{app}\AntigravityHub.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\icon.ico"; Flags: uninsneveruninstall; Check: CanWritePackageShortcut('{group}\AI HUB.lnk')
Name: "{autodesktop}\AI HUB"; Filename: "{app}\AntigravityHub.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\icon.ico"; Flags: uninsneveruninstall; Tasks: desktopicon; Check: CanWritePackageShortcut('{autodesktop}\AI HUB.lnk')

[Run]
Filename: "{app}\AntigravityHub.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,AI HUB}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EdgeClients = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  HubExe = '{app}\AntigravityHub.exe';

function GetFileAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function IsPackageShortcut(Path: String): Boolean;
var Shell, Link: Variant;
    Attr: LongWord;
begin
  Result := False;
  Attr := GetFileAttributes(Path);
  if (Attr = $FFFFFFFF) or ((Attr and $410) <> 0) then
    Exit; { missing, directory, or reparse point }
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(Path);
    Result := (CompareText(Link.TargetPath, ExpandConstant(HubExe)) = 0) and
      (Link.Arguments = '');
  except
    Log('Cannot read shortcut; leaving it untouched: ' + Path);
  end;
end;

function CanWritePackageShortcut(Name: String): Boolean;
var Path: String;
begin
  Path := ExpandConstant(Name);
  Result := (GetFileAttributes(Path) = $FFFFFFFF) or IsPackageShortcut(Path);
  if not Result then
    Log('Preserving existing shortcut: ' + Path);
end;

procedure RemovePackageShortcut(Name: String);
var Path: String;
begin
  Path := ExpandConstant(Name);
  if IsPackageShortcut(Path) then begin
    if not DeleteFile(Path) then
      Log('Could not remove package shortcut: ' + Path);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Command: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  { Settings writes the fully quoted frozen executable path with no arguments. }
  if RegQueryStringValue(HKCU, RunKey, 'AI HUB', Command) and
    (CompareText(Command, '"' + ExpandConstant(HubExe) + '"') = 0) then
    RegDeleteValue(HKCU, RunKey, 'AI HUB');
  RemovePackageShortcut('{autodesktop}\AI HUB.lnk');
  RemovePackageShortcut('{group}\AI HUB.lnk');
end;

function HasVersion(Root: Integer): Boolean;
var V: String;
begin
  Result := RegQueryStringValue(Root, EdgeClients, 'pv', V) and
    (Trim(V) <> '') and (V <> '0.0.0.0');
end;

function WebViewInstalled: Boolean;
begin
  Result := HasVersion(HKLM32) or HasVersion(HKLM64) or HasVersion(HKCU32) or HasVersion(HKCU64);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if WebViewInstalled then begin
    Log('WebView2 Runtime already present.');
    Exit;
  end;
  Log('WebView2 Runtime missing; starting bundled Microsoft bootstrapper.');
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
          SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Log('WebView2 bootstrapper exit code: ' + IntToStr(ExitCode))
  else
    Log('Could not start the WebView2 bootstrapper. Windows error: ' + IntToStr(ExitCode));
  if WebViewInstalled then
    Log('WebView2 Runtime detected after bootstrapper.')
  else
    Result := CustomMessage('WebViewFailed') + ' (WebView2: ' + IntToStr(ExitCode) + ')';
end;

function IsAbsoluteDrivePath(P: String): Boolean;
var Drive: String;
begin
  Result := False;
  if Length(P) < 3 then
    Exit;
  Drive := Uppercase(Copy(P, 1, 1));
  Result := (Pos(Drive, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') > 0) and (Copy(P, 2, 2) = ':\');
end;

function OpenCodeConfigDir(Param: String): String;
var OverrideDir, XdgDir, Profile: String;
begin
  Result := '';
  OverrideDir := Trim(GetEnv('OPENCODE_CONFIG_DIR'));
  if IsAbsoluteDrivePath(OverrideDir) then begin
    Result := RemoveBackslashUnlessRoot(OverrideDir);
    Exit;
  end;
  XdgDir := Trim(GetEnv('XDG_CONFIG_HOME'));
  if IsAbsoluteDrivePath(XdgDir) then begin
    Result := AddBackslash(XdgDir) + 'opencode';
    Exit;
  end;
  Profile := Trim(GetEnv('USERPROFILE'));
  if IsAbsoluteDrivePath(Profile) and DirExists(Profile) then
    Result := AddBackslash(Profile) + '.config\opencode';
end;

function OpenCodeProfileAvailable: Boolean;
begin
  Result := OpenCodeConfigDir('') <> '';
  if not Result then
    Log('Skipping optional OpenCode settings: no valid OpenCode config directory found.');
end;

function MissingOpenCodeConfig: Boolean;
var D: String;
begin
  D := OpenCodeConfigDir('');
  Result := OpenCodeProfileAvailable and
    not FileExists(AddBackslash(D) + 'opencode.json') and not FileExists(AddBackslash(D) + 'opencode.jsonc');
end;
