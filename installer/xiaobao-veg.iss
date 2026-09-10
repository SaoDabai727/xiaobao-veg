; 蔬菜汇总 — Inno Setup 安装脚本
; 默认安装到 %LOCALAPPDATA%\蔬菜汇总（用户可写，账本也在该目录下 data/）
; 升级时不删除用户 data/（见 [InstallDelete] 未包含 data）

#define MyAppName "蔬菜汇总"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "xiaobao-veg"
#define MyAppExeName "蔬菜汇总.exe"
#define MyAppId "{{A7C3E9B1-5D2F-4A8E-9C1B-6F0E8D4A2B31}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 允许用户改路径，但仍建议 LocalAppData
AllowNoIcons=yes
OutputDir=..
OutputBaseFilename=xiaobao-veg-setup-v{#MyAppVersion}
SetupIconFile=..\assets\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; 覆盖安装时保留已有文件（含 data/）
DirExistsWarning=no
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=
LicenseFile=

[Languages]
; CI 自带的 Inno 非商业版不含简体语言包；向导用英文，自定义文案仍为中文
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
; 程序目录（onedir）；flags 确保升级覆盖程序文件，但不会主动清空 data/
Source: "..\dist\蔬菜汇总\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
begin
  Result := MsgBox(
    '卸载将删除程序文件。' + #13#10 +
    '账本仍保留在 %LOCALAPPDATA%\蔬菜汇总\data\ ，可手动备份。' + #13#10 +
    '是否继续卸载？',
    mbConfirmation, MB_YESNO) = IDYES;
end;
