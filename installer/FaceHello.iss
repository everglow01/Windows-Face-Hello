; FaceHello 安装器(Inno Setup 6.3+)
; ------------------------------------------------------------------------
; 把 build_release.py 产出的便携包打成单文件 setup.exe:
;   1) uv run python scripts/build_release.py      生成便携包(默认 %LOCALAPPDATA%\FaceHello-build\FaceHello)
;   2) iscc installer\FaceHello.iss                编译出 installer\Output\FaceHello-Setup-x.y.z.exe
; 便携包路径可用 /DBuildDir=D:\path\FaceHello 覆盖。
;
; 装的内容:便携 CPython + 分发依赖 + face_hello/app 源码 + 模型 + CP DLL,装到
;   C:\Program Files\FaceHello。安装结束自动:注册并启动 LocalSystem 服务、注册
;   锁屏 Credential Provider、建 ProgramData 数据/头像目录。无需用户碰 uv / 命令行。
; 卸载:停服务 → 删服务 → 注销 CP → 清 LSA 登录密码 + 人脸库 → 删全部文件(完全干净)。
;
; 安全红线:本安装器会注册 Credential Provider。真机首次安装务必先打系统还原点 /
;   快照、保留一个备用管理员账户;绝不替换系统密码 / PIN 提供程序(CP 只新增磁贴)。
; ------------------------------------------------------------------------

#ifndef BuildDir
  #define BuildDir GetEnv("LOCALAPPDATA") + "\FaceHello-build\FaceHello"
#endif

#define MyAppName "FaceHello"
; 版本号可被编译命令 /DMyAppVersion=... 覆盖(release.yml 用 git tag 注入)
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "FaceHello"
#define PyExe "{app}\python\python.exe"
#define PyWExe "{app}\python\pythonw.exe"

[Setup]
; AppId 唯一标识本程序(升级 / 卸载靠它),一经发布不要改
AppId={{A4E1F0D2-7C3B-4E5A-9F18-2B6C0D5E3A77}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\FaceHello
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
; 自定义图标(app\assets\facehello.ico 随 app\ 打包);缺文件时 Windows 回退默认图标
UninstallDisplayIcon={app}\app\assets\facehello.ico
OutputDir=Output
OutputBaseFilename=FaceHello-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 仅 64 位;CP DLL 与便携 python 都是 x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 注册服务 / CP / 写 Program Files 都需要管理员
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
RestartIfNeededByRun=no

; 代码签名(可选):加 /DSign 编译并用 /Sfacehello=... 提供签名命令,即对 setup.exe
; 与卸载器签名。不传 /DSign 时是无签名构建(CI 默认),行为完全不变。命令见 SIGNING.md:
;   iscc /DSign "/Sfacehello=signtool sign /fd sha256 /f <pfx> /p <pwd> /tr <ts> /td sha256 $f" ...
#ifdef Sign
SignTool=facehello
SignedUninstaller=yes
#endif

[Languages]
; 简体中文为默认;ChineseSimplified.isl 随仓库附带(Inno 不自带中文),路径相对 .iss 所在目录
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Dirs]
; 数据 + 锁屏头像目录(SYSTEM 服务与提权 GUI 共享;CP 硬编码读 ProgramData\FaceHello)
Name: "{commonappdata}\FaceHello"; Permissions: admins-full system-full
Name: "{commonappdata}\FaceHello\data"; Permissions: admins-full system-full

[Files]
; 便携包整目录原样拷入安装根(含 python\、models\、face_hello\、app\、版本化 CP DLL)
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\FaceHello 管理台"; Filename: "{#PyWExe}"; Parameters: "-m app.main"; WorkingDir: "{app}"; IconFilename: "{app}\app\assets\facehello.ico"
Name: "{group}\卸载 FaceHello"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FaceHello 管理台"; Filename: "{#PyWExe}"; Parameters: "-m app.main"; WorkingDir: "{app}"; IconFilename: "{app}\app\assets\facehello.ico"; Tasks: desktopicon

[Run]
; configure 统一检查 ACL、服务、版本化 CP 与命名管道 readiness；非零退出码由 [Code] 阻止完成安装。
; 收尾页可选:立即打开管理台(管理台会按需请求 UAC 提权)
Filename: "{#PyWExe}"; Parameters: "-m app.main"; WorkingDir: "{app}"; Description: "立即打开 FaceHello 管理台"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
; 删文件前(此时 {app}\python 与脚本都还在):停服务 → 删服务 → 注销 CP → 清敏感数据。
; 每条独立 RunOnceId;失败不阻断卸载。
Filename: "{#PyExe}"; Parameters: "winservice_main.py stop"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "StopSvc"
Filename: "{#PyExe}"; Parameters: "winservice_main.py remove"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSvc"
Filename: "{#PyExe}"; Parameters: "install_maintenance.py uninstall"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "UnregCP"
; 完全干净:清 LSA 登录密码 + 删人脸库(此刻 .installed 还在,清理脚本走安装态路径)
Filename: "{#PyExe}"; Parameters: "uninstall_cleanup.py"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "WipeSecrets"

[UninstallDelete]
; 运行期生成的文件(.pyc、.installed、service.log、人脸库、头像)不在 [Files] 记录里,
; Inno 默认不删 → 显式清掉,做到完全干净卸载。
Type: filesandordirs; Name: "{commonappdata}\FaceHello"
Type: filesandordirs; Name: "{app}"

[Code]
function OpenProcess(dwDesiredAccess: Cardinal; bInheritHandle: Boolean;
  dwProcessId: Cardinal): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle: THandle; dwMilliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function OpenSCManager(lpMachineName: String; lpDatabaseName: String;
  dwDesiredAccess: Cardinal): THandle;
  external 'OpenSCManagerW@advapi32.dll stdcall';
function OpenService(hSCManager: THandle; lpServiceName: String;
  dwDesiredAccess: Cardinal): THandle;
  external 'OpenServiceW@advapi32.dll stdcall';

type
  TServiceStatus = record
    dwServiceType: Cardinal;
    dwCurrentState: Cardinal;
    dwControlsAccepted: Cardinal;
    dwWin32ExitCode: Cardinal;
    dwServiceSpecificExitCode: Cardinal;
    dwCheckPoint: Cardinal;
    dwWaitHint: Cardinal;
  end;

function QueryServiceStatus(hService: THandle; var lpServiceStatus: TServiceStatus): Boolean;
  external 'QueryServiceStatus@advapi32.dll stdcall';

var
  ServiceExisted: Boolean;
  ServiceWasRunning: Boolean;
  ParentPID: Cardinal;
  BackupDir: String;

function BackupExistingInstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if not DirExists(ExpandConstant('{app}')) then
    exit;
  BackupDir := ExpandConstant('{commonappdata}\FaceHello\update-backup');
  DelTree(BackupDir, True, True, True);
  ForceDirectories(BackupDir);
  Result := Exec(ExpandConstant('{cmd}'), '/c robocopy "' + ExpandConstant('{app}') +
    '" "' + BackupDir + '" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode <= 7);
end;

function RestoreExistingInstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if (BackupDir = '') or (not DirExists(BackupDir)) then
    exit;
  Result := Exec(ExpandConstant('{cmd}'), '/c robocopy "' + BackupDir + '" "' +
    ExpandConstant('{app}') + '" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode <= 7);
end;

function InitializeSetup(): Boolean;
var
  I: Integer;
  Param: String;
begin
  ParentPID := 0;
  for I := 1 to ParamCount do begin
    Param := ParamStr(I);
    if Pos('/FaceHelloParentPID=', Param) = 1 then
      ParentPID := StrToIntDef(Copy(Param, Length('/FaceHelloParentPID=') + 1, MaxInt), 0);
  end;
  Result := True;
end;

function ProcessExists(PID: Cardinal): Boolean;
var
  Handle: THandle;
begin
  if PID = 0 then begin
    Result := False;
    exit;
  end;
  Handle := OpenProcess($00100000, False, PID); { SYNCHRONIZE }
  if Handle = 0 then
    Result := False
  else begin
    Result := WaitForSingleObject(Handle, 0) = $00000102; { WAIT_TIMEOUT }
    CloseHandle(Handle);
  end;
end;

function WaitForParent(): Boolean;
var
  I: Integer;
begin
  Result := True;
  if ParentPID = 0 then
    exit;
  for I := 1 to 240 do begin
    if not ProcessExists(ParentPID) then
      exit;
    Sleep(500);
  end;
  Result := False;
end;

function ServiceExists(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query FaceHello', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function ServiceState(): Cardinal;
var
  Manager: THandle;
  Service: THandle;
  Status: TServiceStatus;
begin
  Result := 0;
  Manager := OpenSCManager('', '', $0001); { SC_MANAGER_CONNECT }
  if Manager = 0 then
    exit;
  Service := OpenService(Manager, 'FaceHello', $0004); { SERVICE_QUERY_STATUS }
  if Service <> 0 then begin
    if QueryServiceStatus(Service, Status) then
      Result := Status.dwCurrentState;
    CloseHandle(Service);
  end;
  CloseHandle(Manager);
end;

function ServiceRunning(): Boolean;
begin
  Result := ServiceState() = 4; { SERVICE_RUNNING }
end;

function ServiceStopped(): Boolean;
begin
  Result := ServiceState() = 1; { SERVICE_STOPPED }
end;

function StopServiceAndWait(): Boolean;
var
  ResultCode: Integer;
  I: Integer;
begin
  Result := True;
  if not ServiceExists() then
    exit;
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop FaceHello', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  for I := 1 to 120 do begin
    if ServiceStopped() or (not ServiceExists()) then
      exit;
    Sleep(1000);
  end;
  Result := False;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  if not WaitForParent() then begin
    Result := 'FaceHello 管理台仍在运行。请关闭后重试。';
    exit;
  end;
  ServiceExisted := ServiceExists();
  ServiceWasRunning := ServiceExisted and ServiceRunning();
  if ServiceExisted and not StopServiceAndWait() then
    Result := '无法停止 FaceHello 服务。安装尚未修改文件，请稍后重试。'
  else if ServiceExisted and not BackupExistingInstall() then begin
    if ServiceWasRunning then
      Exec(ExpandConstant('{sys}\sc.exe'), 'start FaceHello', '', SW_HIDE,
        ewWaitUntilTerminated, ResultCode);
    Result := '无法备份当前 FaceHello，安装尚未修改文件。请检查磁盘空间后重试。';
  end
  else
    Result := '';
end;

function ServiceInstallCommand(Param: String): String;
begin
  if ServiceExisted then
    Result := 'update'
  else
    Result := 'install';
end;

function ShouldStartService(): Boolean;
begin
  Result := (not ServiceExisted) or ServiceWasRunning;
end;

function RunPostInstall(): Boolean;
var
  ResultCode: Integer;
  StartValue: String;
begin
  if ShouldStartService() then
    StartValue := 'yes'
  else
    StartValue := 'no';
  Result := Exec(ExpandConstant('{#PyExe}'),
    'install_maintenance.py configure --service-command ' + ServiceInstallCommand('') +
    ' --start ' + StartValue, ExpandConstant('{app}'), SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and (not RunPostInstall()) then begin
    if ServiceExisted then begin
      Exec(ExpandConstant('{sys}\sc.exe'), 'stop FaceHello', '', SW_HIDE,
        ewWaitUntilTerminated, ResultCode);
      if RestoreExistingInstall() then begin
        if ServiceWasRunning then
          Exec(ExpandConstant('{sys}\sc.exe'), 'start FaceHello', '', SW_HIDE,
            ewWaitUntilTerminated, ResultCode);
      end;
    end;
    RaiseException('FaceHello 服务或锁屏组件配置失败。已尝试恢复上一版本；人脸数据和系统密码/PIN 未被删除，请查看安装日志。');
  end;
  if (CurStep = ssDone) and (BackupDir <> '') then
    DelTree(BackupDir, True, True, True);
end;
