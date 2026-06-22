# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

让普通 RGB 摄像头给 Windows 做人脸解锁。背景、技术路线选择(Credential Provider vs WBF 驱动)、安全权衡和阶段路线图详见 **DESIGN.md**;面向用户的使用说明见 **README.md**。本文件聚焦后续开发需要的命令与架构要点。

## 环境与命令(uv 管理,Python 3.11,虚拟环境 `.venv`,**非 base**)

```powershell
uv sync                                      # 创建 .venv 并装依赖
uv run python scripts/offline_check.py       # 离线自检(不需摄像头/显示器)——改完核心库先跑这个
uv run python -m app.main                     # 启动 PySide6 管理台 GUI
uv run python -m scripts.liveness_tune        # 标定活体阈值(实时显示 EAR/yaw,退出给建议值)
uv run python -m face_hello.service           # 启动命名管道认证服务(常驻)
uv run python -m scripts.auth_client ping|authenticate   # 测试客户端,模拟 Credential Provider 调服务
uv run python -m scripts.cred_vault_cli set|get|clear [用户名] [--show]   # LSA Secret 读写测试
```

Windows 服务(LocalSystem,开机自启;**需管理员**;`<venv>` = `.venv\Scripts\python.exe`):

```powershell
<venv> winservice_main.py install --startup auto   # 注册并设开机自启(选项必须在 install 之前)
<venv> winservice_main.py start | stop | remove     # 起/停/删;或用 sc.exe start|stop FaceHello
```

C++ Credential Provider(VS2022 + “使用 C++ 的桌面开发”;**用 PowerShell 跑,别用 Bash**——MSYS 会损坏 `/p:` 参数):

```powershell
& "F:\VS2022\MSBuild\Current\Bin\MSBuild.exe" cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
# 产物 cp\x64\Release\FaceHelloCP.dll;改 Python 不必重编 DLL,二者只靠命名管道协议耦合。
```

- 没有测试框架(pytest 等)。`scripts/offline_check.py` 是断言式自检,等价于冒烟测试:验证 matcher、DPAPI 加密往返、FaceMesh、InsightFace 加载。改完核心库先跑它。
- 首次运行自动下载模型到 `models/`:InsightFace `buffalo_l`(~281MB)、MediaPipe `face_landmarker.task`(~3.7MB)。`data/`(加密人脸库)和 `models/` 均 gitignored。
- `cred_vault` 的写/删需**管理员**终端;读需 **SYSTEM**(`psexec -s` 模拟,见 `cred_vault_cli.py` 顶部注释)。服务跑起来后排错看 `data/service.log`(服务无控制台,stdout/stderr 都落这)。
- PowerShell 里 `sc` 是 `Set-Content` 的别名,查/控服务务必用 `sc.exe`。

## 架构

两层设计(路线 A)。阶段 1~4(Python 原型)完成;阶段 5(C++ Credential Provider 锁屏集成)主体打通——CP 磁贴 → 命名管道 → LocalSystem 服务 → InsightFace 识别 → 读 LSA → 打包 KERB 真解锁,本地账户与微软账户(MSA-backed 本地登录)均已在 VM 与真机端到端验证(里程碑 d)。剩 5-4 加固(管道 ACL 限 SYSTEM、失败兜底/锁定、日志)与 C 档分发(Inno 安装器、`/MT` 静态 CRT 编 DLL、代码签名、GitHub Release 放 ~285MB 模型)。

**`face_hello/` 核心库**(无 Qt 依赖,可被 GUI、服务、脚本共用):
- `config.py` — 集中路径/模型/阈值。`DEFAULTS` 是阈值默认值,被 store 里持久化的 `settings` 覆盖。
- `platform_backend.py` — 阶段 6 跨平台抽象层:把 OS 耦合三件事(静态加密 `protect`/`unprotect`、摄像头后端 `open_capture`、用户名 `current_user`)收敛到一处。Windows 行为与重构前逐字节一致(DPAPI 机器范围 / DSHOW / GetUserName);非 Windows 给默认实现,静态加密留 `NotImplementedError`。store/camera/cred_vault 都委托它。
- `camera.py` — OpenCV 采集,后端经 `platform_backend.open_capture`(Windows=`CAP_DSHOW`)。
- `detector.py` — InsightFace `FaceAnalysis`(CPU),输出 512 维 `normed_embedding`。惰性加载 + `load()` 显式预热。
- `matcher.py` — 余弦相似度;embedding 已 L2 归一化,余弦即点积。
- `liveness.py` — MediaPipe Tasks `FaceLandmarker` 取 468 点 → EAR 判眨眼 + solvePnP 估 yaw 判转头。`LivenessSession` 是随机挑战(眨眼/左转/右转)+ 双重超时的逐帧状态机。
- `enroll.py` — `Enroller` 累积合格帧(过滤低分/太小的脸),取平均特征后重新归一化作模板。
- `store.py` — `FaceStore`:经 `platform_backend`(Windows=DPAPI 机器范围)加密的 pickle 落盘到 `data/faces.dat`,存特征(非照片)+ 元数据 + settings。同名 profile 覆盖。
- `auth.py` — `AuthSession` 编排状态机:`liveness → recognize → done`,逐帧 `feed()` 驱动。`authenticate_blocking()` 是无 Qt 的阻塞版(开摄像头跑完整流程),供服务调用。
- `cred_vault.py` — 阶段 5 用:把登录密码存进 LSA Secret(键 `L$FaceHello_<user>`,UTF-16LE)。密码**永不经过 IPC**,由 CP 自己在 SYSTEM 上下文读。`current_user()` 从 `platform_backend` re-export(Windows=`GetUserName()`)。
- `service.py` — 命名管道(`\\.\pipe\FaceHello`)服务端,**单实例串行**(`nMaxInstances=1`),JSON 消息模式。同步命令 `ping`/`authenticate`;里程碑 d 加的异步对:`auth_start`(后台线程跑一次认证,立即返回)+ `auth_poll`(取实时活体提示与最终结果),让锁屏能边识别边刷提示。响应只回 `{ok, user, similarity}`,不回密码。
- `win_service.py` + 仓库根 `winservice_main.py` — 把 `serve()` 封成 LocalSystem Windows 服务(开机自启,锁定/睡眠唤醒都常驻)。服务 ImagePath 用 venv 的 python 直接跑 `winservice_main.py` 引导脚本(把根目录加进 `sys.path`),**不用**默认 `PythonService.exe`——后者在 SCM 上下文 import 不到 `face_hello`(`package=false`,没装进 venv)。

**`cp/` C++ Credential Provider**(COM in-proc DLL,锁屏「Face Unlock」磁贴;CLSID `{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}`):
- `CFaceProvider.{h,cpp}` — `ICredentialProvider`,枚举出 1 个磁贴。`SignalAutoLogon()` 由扫描线程在识别通过后调用 → 置标志 + `CredentialsChanged` → `GetCredentialCount` 回 `pbAutoLogonWithDefault=TRUE` 让 LogonUI 自动提交。
- `CFaceCredential.{h,cpp}` — `ICredentialProviderCredential`。`SetSelected` 启动后台扫描线程:调 `auth_start` 后每 ~400ms `auth_poll`,用 `SetFieldString` 把活体提示刷到磁贴;成功缓存用户名并触发自动登录。`GetSerialization` 消费缓存结果 → 读 LSA 密码 → 打包 `KERB_INTERACTIVE_UNLOCK_LOGON` 解锁。
- `PipeClient.{h,cpp}` — 命名管道客户端(对应 `scripts/auth_client.py`)。`Call` 在 `ERROR_PIPE_BUSY` 与 `ERROR_FILE_NOT_FOUND`(单实例管道重建的空窗)上都重试,约 30 次/3s。
- 绝不替换/过滤系统密码/PIN 提供程序;只在打了快照的 VM 里 `regsvr32` 注册测试。详见 `cp/README.md`。

**`app/` PySide6 管理台**(标签页:录入 / 测试解锁 / 设置 / 服务与凭据):
- `main.py` — UI;`FaceDetector` 和 `FaceStore` 在 `MainWindow` 创建一次后注入各 Tab 共享。录入页用户名预填 `cred_vault.current_user()`;「服务与凭据」页设 LSA 密码 + 一键装/起/停/删服务(均经 `winservice_main.py`),按 `IsUserAnAdmin()` 灰显;设置页有「启用活体检测」开关(`liveness_enabled`)。
- `workers.py` — 所有摄像头 + 推理放 `QThread`(`WarmupWorker`/`EnrollWorker`/`AuthWorker`),Signal 回主线程更新 UI,避免卡死。

数据流(锁屏解锁):CP 磁贴选中 → 服务 `auth_start` 起后台线程 → `AuthSession.feed()` 逐帧先跑 `liveness`(活体关则跳过),通过后 `detector` 提特征 → `matcher.best_match` 比对 gallery → `AuthResult` → CP `auth_poll` 拿到 user → 读 LSA → KERB 解锁。

## 本仓库特有的坑(改代码前必读)

- **工作目录含中文路径**。两个 C++ 后端库读不了非 ASCII 路径:
  - MediaPipe → 不能传模型路径,必须用 `model_asset_buffer=` 传字节(见 `liveness.py`)。
  - OpenCV → 不能用 `cv2.imread`,一律 `cv2.imdecode(np.fromfile(path), ...)`。
  - InsightFace/onnxruntime 加载 `.onnx` 支持 Unicode 路径,正常。
- **性能/预热**:首次推理有冷启动代价(onnxruntime + TFLite ~0.7s),已在启动期预热挪走。`detector.load()` 会真跑一次带人脸的样例图;`FaceMeshTracker` 也要预热一个实例。改启动路径时别破坏这个。`DET_SIZE=(320,320)` 且 `allowed_modules=["detection","recognition"]`(关掉 genderage/2d106/3d68)是有意的提速取舍。
- **MediaPipe 0.10.x 已移除 legacy `solutions`**,只能用 Tasks API,别退回旧写法。`FaceLandmarker` 用 `RunningMode.VIDEO` + 严格递增时间戳(`detect_for_video`,每帧 `_ts_ms += 33`),IMAGE 模式偶发单帧卡死数十秒。
- **`FaceLandmarker.close()` 会阻塞约 40s**(等内部图/线程退出)。绝不能在主流程同步调——`AuthSession._finish` 和 `service._warm_liveness` 都把它丢到 daemon 线程关。曾因此让解锁卡 ~42s、服务启动/建管道前白等 ~40s。
- **冷启动慢的两个来源**:① 摄像头未就绪——`Camera.open()` 带退避重试且确认能 `read()` 到一帧(冷启动/睡眠唤醒后 USB 摄像头要几秒枚举);② 模型磁盘 I/O——InsightFace 会先给 `buffalo_l` **每个** `.onnx` 建 session 再按 `allowed_modules` 丢弃,故已**删掉用不到的** `1k3d68.onnx`(144MB)/`2d106det.onnx`/`genderage.onnx`,只留 `det_10g.onnx`+`w600k_r50.onnx`,冷读 341MB→191MB。别让它们被重新下载(整个 `buffalo_l` 目录在才不会重下;删单个文件不触发重下)。识别精度无损。再进一步:`w600k_r50` 走 **FP16 量化**(`scripts/quantize_model.py`,174MB→87MB,识别实测无损),release CI 在下载+剪枝后就地量化(见 `release.yml`);量化会留 `w600k_r50.fp32.bak`(本地回退用,CI 跳过),**`build_release.py` 忽略 `*.bak`、绝不入包**。若仍太慢,最后一条路是换 `buffalo_s`(识别模型~13MB,需重录入 + 重标定、精度略降)。
- **SYSTEM 服务专属的坑**:① 人脸库 DPAPI 必须用机器范围 `CRYPTPROTECT_LOCAL_MACHINE`(`platform_backend.py` 的 `_DPAPI_LOCAL_MACHINE=0x4`),否则 SYSTEM 服务解不开用户录入的库;② matplotlib(insightface 的传递依赖)在 SYSTEM 上下文首次建字体缓存会卡死/崩服务——`win_service.py` 在导入前设 `MPLBACKEND=Agg` + `MPLCONFIGDIR` 到 `data/`。
- **身份契约**:profile 名 == `GetUserName()`(本地 SAM 名)== LSA 键 `L$FaceHello_<user>` == KERB 账户名,四者必须一致,解锁才成立(MSA-backed 本地登录也走这条)。LSA 键名不能含反斜杠。
- **安全红线**:绝不移除系统的密码/PIN 提供程序(始终保留兜底登录);管道 ACL 留待 5-4 限 SYSTEM;CP 注册/真机测试先打快照、留个备用管理员账户与系统还原点。RGB 单目天然抗不住照片/视频攻击,活体检测是底线。
