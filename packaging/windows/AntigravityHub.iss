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
Source: "..\..\config-templates\antigravity.json"; DestDir: "{code:OpenCodeConfigDir}"; Flags: onlyifdoesntexist uninsneveruninstall; Tasks: opencode

[Icons]
Name: "{group}\AI HUB"; Filename: "{app}\AntigravityHub.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AI HUB"; Filename: "{app}\AntigravityHub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AntigravityHub.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,AI HUB}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EdgeClients = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

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
  if WebViewInstalled then
    Exit;
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
              SW_HIDE, ewWaitUntilTerminated, ExitCode) or not WebViewInstalled then
    Result := CustomMessage('WebViewFailed');
end;

function OpenCodeConfigDir(Param: String): String;
begin
  Result := ExpandConstant('{userprofile}\.config\opencode');
end;

function MissingOpenCodeConfig: Boolean;
var D: String;
begin
  D := OpenCodeConfigDir('');
  Result := not FileExists(D + '\opencode.json') and not FileExists(D + '\opencode.jsonc');
end;
