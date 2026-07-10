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
; 便携包整目录原样拷入安装根(含 python\、models\、face_hello\、app\、DLL、引导脚本)
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\FaceHello 管理台"; Filename: "{#PyWExe}"; Parameters: "-m app.main"; WorkingDir: "{app}"; IconFilename: "{app}\app\assets\facehello.ico"
Name: "{group}\卸载 FaceHello"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FaceHello 管理台"; Filename: "{#PyWExe}"; Parameters: "-m app.main"; WorkingDir: "{app}"; IconFilename: "{app}\app\assets\facehello.ico"; Tasks: desktopicon

[Run]
; 顺序很重要,逐条 waituntilterminated:
; 1) 先落 .installed 标记 —— config.py 见到它即走安装态(数据落 ProgramData)。必须在
;    启动服务之前写好,否则服务以开发态启动、数据落 Program Files 与 GUI 不一致。
Filename: "{cmd}"; Parameters: "/c type nul > ""{app}\.installed"""; Flags: runhidden waituntilterminated; StatusMsg: "写入安装标记..."
; 2) 运行数据只允许 SYSTEM 与管理员读写;同时修复升级前已继承 Users:Write 的目录与文件
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\FaceHello"" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F /T /C"; Flags: runhidden waituntilterminated; StatusMsg: "保护 FaceHello 数据目录..."
; 3) 注册并设开机自启服务(便携 python 即服务 ImagePath,登录 / 锁屏 / 睡眠唤醒常驻)
Filename: "{#PyExe}"; Parameters: "winservice_main.py install --startup auto"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "注册 FaceHello 服务..."
; 4) 立即启动服务(.installed 已在 → 安装态 → 数据落 ProgramData,无需重启)
Filename: "{#PyExe}"; Parameters: "winservice_main.py start"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "启动 FaceHello 服务..."
; 5) 注册锁屏 Credential Provider DLL
Filename: "{sys}\regsvr32.exe"; Parameters: "/s ""{app}\FaceHelloCP.dll"""; Flags: runhidden waituntilterminated; StatusMsg: "注册锁屏凭据提供程序..."
; 6) 收尾页可选:立即打开管理台(管理台会按需请求 UAC 提权)
Filename: "{#PyWExe}"; Parameters: "-m app.main"; WorkingDir: "{app}"; Description: "立即打开 FaceHello 管理台"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
; 删文件前(此时 {app}\python 与脚本都还在):停服务 → 删服务 → 注销 CP → 清敏感数据。
; 每条独立 RunOnceId;失败不阻断卸载。
Filename: "{#PyExe}"; Parameters: "winservice_main.py stop"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "StopSvc"
Filename: "{#PyExe}"; Parameters: "winservice_main.py remove"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSvc"
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\FaceHelloCP.dll"""; Flags: runhidden waituntilterminated; RunOnceId: "UnregCP"
; 完全干净:清 LSA 登录密码 + 删人脸库(此刻 .installed 还在,清理脚本走安装态路径)
Filename: "{#PyExe}"; Parameters: "uninstall_cleanup.py"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "WipeSecrets"

[UninstallDelete]
; 运行期生成的文件(.pyc、.installed、service.log、人脸库、头像)不在 [Files] 记录里,
; Inno 默认不删 → 显式清掉,做到完全干净卸载。
Type: filesandordirs; Name: "{commonappdata}\FaceHello"
Type: filesandordirs; Name: "{app}"
