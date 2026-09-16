# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

让普通 RGB 摄像头给 Windows 做人脸解锁。背景、技术路线选择(Credential Provider vs WBF 驱动)、安全权衡和阶段路线图详见 **DESIGN.md**;面向用户的使用说明见 **README.md**。本文件聚焦后续开发需要的命令与架构要点。

## 环境与命令(uv 管理,Python 3.11,虚拟环境 `.venv`,**非 base**)

```powershell
uv sync                                      # 创建 .venv 并装运行时依赖
uv sync --group test                         # 额外安装 pytest 测试依赖
uvx --from ruff==0.15.21 ruff check app face_hello scripts tests winservice_main.py uninstall_cleanup.py  # 与 CI 相同的 lint
uv run python -m compileall face_hello app scripts winservice_main.py  # 语法/字节编译检查
uv run python scripts/offline_check.py       # 离线自检(不需摄像头/显示器)——改完核心库先跑这个
uv run python scripts/doctor.py              # 实机自检(摄像头取帧+模型加载+服务管道 ping);管道项需管理员终端
uv run python scripts/doctor.py --capture-baseline <path>  # 安装/升级前安全基线(安装态、管理员)
uv run python scripts/doctor.py --installed-acceptance --baseline <path>  # 安装态完整验收
uv run --group test pytest -q                # 跑全部单测
uv run --group test pytest tests/test_auth_recognize.py::test_match_success -q  # 跑单个测试
uv run python -m app.main                     # 启动 PySide6 管理台 GUI
uv run python -m scripts.liveness_tune        # 标定活体阈值(实时显示 EAR/yaw,退出给建议值)
uv run python -m face_hello.service           # 启动命名管道认证服务(常驻)
uv run python -m scripts.auth_client ping|authenticate   # 测试客户端,模拟 Credential Provider 调服务
uv run python -m scripts.cred_vault_cli set|get|clear [用户名] [--show]   # LSA Secret 读写测试
uv run python scripts/build_release.py        # 构建 CP + 独立 Python 便携包并跑 release smoke
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

- pytest 覆盖匹配/锁定、认证与反欺骗门、多人保护、录入与多模板、刷脸范围镜像、诊断脱敏、摄像头重试/互斥、tracker 复用、SCM 恢复和安装态验收；改核心库后跑完整 pytest 与 `offline_check.py`。
- `doctor.py` 默认做实机健康检查；安装态支持安全基线与完整验收。安装器在改服务/CP 前保存仅含哈希/大小/计数的基线，之后验收版本、SCM 启动/ImagePath/有限恢复策略、管道、CP DLL、日志、人脸库和系统密码/PIN Provider；失败进入回滚。基线绝不能加入用户名、人脸特征、密码或 LSA Secret。
- 首次运行自动下载模型到 `models/`:InsightFace `buffalo_l`(~191MB,已剪枝)、MediaPipe `face_landmarker.task`(~3.7MB)。`data/`(加密人脸库)和 `models/` 均 gitignored。
- `cred_vault` 的写/删需**管理员**终端;读需 **SYSTEM**(`psexec -s` 模拟,见 `cred_vault_cli.py` 顶部注释)。服务跑起来后排错看 `data/service.log`(服务无控制台,stdout/stderr 都落这)。
- PowerShell 里 `sc` 是 `Set-Content` 的别名,查/控服务务必用 `sc.exe`。

## 架构

两层设计(路线 A)。阶段 1~4(Python 核心与管理台)完成;阶段 5(C++ Credential Provider 锁屏集成)主体打通——CP 磁贴 → 命名管道 → LocalSystem 服务 → InsightFace 识别 → 读 LSA → 打包 KERB 真解锁,本地账户与微软账户(MSA-backed 本地登录)均已在 VM 与真机端到端验证。5-4 加固与 C 档分发均已落地。当前还包括刷脸总开关与登录/工作站范围、管理台日志查看及脱敏诊断导出、默认关闭的多人保护、SCM 有限异常恢复；短时和长时睡眠恢复已通过真机验收，其余场景见 `SLEEP_RESUME_ACCEPTANCE.md`，无稳定复现前不改摄像头或 tracker 生命周期。正式 Release 使用固定个人自签名证书，PFX 只在本机和 GitHub Secrets；不计划申请官方证书，详见 `SIGNING.md`。

**`face_hello/` 核心库**(无 Qt 依赖,可被 GUI、服务、脚本共用):
- `config.py` — 集中路径/模型/阈值。`.installed` 标记或 `FACEHELLO_HOME` 决定安装态：安装态可写数据固定在 `C:\ProgramData\FaceHello\data`，开发态使用仓库内 `data/`；SCM 会缓存环境变量，所以安装器用标记文件保证刚安装的服务无需重启即可识别安装态。`DEFAULTS` 被 store settings 覆盖，不要在业务代码硬编码阈值。也定义 CP 可读的语言/热键/刷脸范围镜像路径；`auth_scope.txt` 是单字节位掩码，缺失或无效默认两种场景都启用。
- `platform_backend.py` — 阶段 6 跨平台抽象层:把 OS 耦合三件事(静态加密 `protect`/`unprotect`、摄像头后端 `open_capture`、用户名 `current_user`)收敛到一处。Windows 行为与重构前逐字节一致(DPAPI 机器范围 / DSHOW / GetUserName);非 Windows 给默认实现,静态加密留 `NotImplementedError`。store/camera/cred_vault 都委托它。
- `camera.py` — OpenCV 采集,后端经 `platform_backend.open_capture`(Windows=`CAP_DSHOW`)。
- `detector.py` — InsightFace `FaceAnalysis`(CPU),输出 512 维 `normed_embedding`。惰性加载 + `load()` 显式预热。
- `matcher.py` — 余弦相似度;embedding 已 L2 归一化,余弦即点积。
- `liveness.py` — MediaPipe Tasks `FaceLandmarker` 取 468 点 → EAR 判眨眼 + solvePnP 估 yaw 判转头。`LivenessSession` 是随机挑战(眨眼/左转/右转)+ 双重超时的逐帧状态机。
- `enroll.py` — `Enroller` 累积合格帧(过滤低分/太小的脸),取平均特征后重新归一化作模板。
- `store.py` — `FaceStore`:经 `platform_backend`(Windows=DPAPI 机器范围)加密的 pickle 落盘到 `data/faces.dat`,存特征(非照片)+ 元数据 + settings。同名 profile 默认覆盖(重新录入/换脸);`replace=False` 时同名追加多模板(补录角度),按 `max_templates_per_name` FIFO 封顶。
- `auth.py` — `AuthSession` 编排 `liveness → recognize → done`;可选多人保护在反欺骗与身份比对前统计人脸，检测到两张或更多时按生物特征失败拒绝，默认关闭。之后经过多帧 `_antispoof_gate` 与 matcher；`authenticate_blocking()` 是服务使用的无 Qt 阻塞路径。
- `cred_vault.py` — 阶段 5 用:把登录密码存进 LSA Secret(键 `L$FaceHello_<user>`,UTF-16LE)。密码**永不经过 IPC**,由 CP 自己在 SYSTEM 上下文读。`current_user()` 从 `platform_backend` re-export(Windows=`GetUserName()`)。
- `service.py` — 命名管道(`\\.\pipe\FaceHello`)服务端,**单实例串行**(`nMaxInstances=1`),JSON 消息模式。同步命令 `ping`/`authenticate`(`authenticate` 绕过失败锁定,故**仅开发态可用、安装态禁用**);里程碑 d 加的异步对:`auth_start`(后台线程跑一次认证,立即返回)+ `auth_poll`(取实时活体提示与最终结果),让锁屏能边识别边刷提示。响应只回 `{ok, user, similarity}`,不回密码。
- `win_service.py` + 仓库根 `winservice_main.py` — LocalSystem 服务封装与 SCM 配置。安装/更新写入 60s、120s、之后 `SC_ACTION_NONE` 的有限异常恢复，24h 重置；正常管理员 stop 不拉起。服务 ImagePath 用便携 Python 直接跑根入口，不用默认 `PythonService.exe`。
- `probes.py` — SCM / 管道 / 模型 / 摄像头探针。`service_health()` 是安装维护、GUI 诊断和 doctor 共用的服务健康契约；`query_service()` 还读取 SCM 恢复动作，installed acceptance 必须精确匹配。
- `diagnostics.py` — 最近 200 行服务日志、修改时间和 WARNING/ERROR 计数，以及固定白名单诊断 ZIP。导出会遮蔽用户名和疑似凭据赋值，不得扩成扫描整个 data 目录。
- `updater.py` — 应用内更新检查、manifest 和下载校验。错误类型由 UI 映射成具体提示(已是最新、本地网络、GitHub 远端 / 限流、manifest、磁盘、响应、哈希 / 签名、暂停下载)，不要重新合并成泛化的「当前无法安装」。

**`cp/` C++ Credential Provider**(COM in-proc DLL,锁屏「Face Unlock」磁贴;CLSID `{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}`):
- `CFaceProvider.{h,cpp}` — 读取 `auth_scope.txt` 决定是否枚举磁贴。Windows 10+ 常把登录与 `Win+L` 都报为 `CPUS_LOGON`，故用 WTS 当前会话用户名区分；查询失败且只开一个场景时默认隐藏。识别成功后 `SignalAutoLogon()` → `CredentialsChanged` → 自动提交。
- `CFaceCredential.{h,cpp}` — `ICredentialProviderCredential`。`SetSelected` 只显示「按 → 开始刷脸」提示并启动可选热键监听;用户按「→」或配置热键后才调 `auth_start`,随后每 ~400ms `auth_poll`,用 `SetFieldString` 把活体提示刷到磁贴;成功缓存用户名并触发自动登录。**失败可按磁贴「→」或热键重试,共 `kMaxFaceAttempts`(=3)次(任何失败都计数),用尽则停刷脸、提示改用密码**(密码磁贴始终在)。`GetSerialization` 成功时消费缓存结果 → 读 LSA 密码 → 打包 `KERB_INTERACTIVE_UNLOCK_LOGON` 解锁;未成功时把「→」当重试入口(`_StartAuthThread`)。
- `PipeClient.{h,cpp}` — 命名管道客户端(对应 `scripts/auth_client.py`)。`Call` 在 `ERROR_PIPE_BUSY` 与 `ERROR_FILE_NOT_FOUND`(单实例管道重建的空窗)上都重试,约 30 次/3s;连接后用 `GetNamedPipeServerProcessId` 读取服务端进程并要求 TokenUser 为 LocalSystem(`S-1-5-18`),验证失败则在发送请求前关闭管道。
- 绝不替换/过滤系统密码/PIN 提供程序;只在打了快照的 VM 里 `regsvr32` 注册测试。详见 `cp/README.md`。

**`app/` PySide6 管理台**(页面:录入 / 测试解锁 / 服务、凭据与诊断 / 设置):
- `main.py` — UI；共享 `FaceDetector` / `FaceStore`。设置页包含刷脸总开关、Windows 登录/工作站解锁范围、默认关闭的多人保护、活体/反欺骗与热键；服务页管理 LSA 凭据、服务和诊断，可查看最近日志、打开目录及导出脱敏 ZIP。
- `workers.py` — 所有摄像头 + 推理放 `QThread`(`WarmupWorker`/`EnrollWorker`/`AuthWorker`),Signal 回主线程更新 UI,避免卡死。

数据流(锁屏解锁):CP 磁贴选中 → 用户按「→」或配置热键 → 服务 `auth_start` 起后台线程 → `AuthSession.feed()` 逐帧先跑 `liveness`(活体关则跳过),通过后 `detector` 提特征 → `matcher.best_match` 比对 gallery → `AuthResult` → CP `auth_poll` 拿到 user → 读 LSA → KERB 解锁。

## 本仓库特有的坑(改代码前必读)

- **工作目录含中文路径**。两个 C++ 后端库读不了非 ASCII 路径:
  - MediaPipe → 不能传模型路径,必须用 `model_asset_buffer=` 传字节(见 `liveness.py`)。
  - OpenCV → 不能用 `cv2.imread`,一律 `cv2.imdecode(np.fromfile(path), ...)`。
  - InsightFace/onnxruntime 加载 `.onnx` 支持 Unicode 路径,正常。
- **性能/预热**:首次推理有冷启动代价(onnxruntime + TFLite ~0.7s),已在启动期预热挪走。`detector.load()` 会真跑一次带人脸的样例图;`FaceMeshTracker` 也要预热一个实例。改启动路径时别破坏这个。`DET_SIZE=(320,320)` 且 `allowed_modules=["detection","recognition"]`(关掉 genderage/2d106/3d68)是有意的提速取舍。
- **MediaPipe 0.10.x 已移除 legacy `solutions`**,只能用 Tasks API,别退回旧写法。`FaceLandmarker` 用 `RunningMode.VIDEO` + 严格递增时间戳(`detect_for_video`,每帧 `_ts_ms += 33`),IMAGE 模式偶发单帧卡死数十秒。
- **`FaceLandmarker.close()` 会阻塞约 40s**(等内部图/线程退出)。绝不能在主流程同步调——`AuthSession._finish` 把它丢到 daemon 线程关。曾因此让解锁卡 ~42s、服务启动/建管道前白等 ~40s。服务侧已改为**复用一个长寿命 tracker**:`_warm_liveness()` 建好预热后返回,由 `_AuthRunner.tracker` 持有、跨多次异步解锁复用(服务路径单实例串行,安全),不再每会话建/弃;故 `_finish` 仅关**自己建的** tracker(`_owns_tracker`,即 GUI/CLI/同步开发路径),注入的(服务共享)不关。
- **冷启动慢的两个来源**:① 摄像头未就绪——`Camera.open()` 带退避重试且确认能 `read()` 到一帧(冷启动/睡眠唤醒后 USB 摄像头要几秒枚举);② 模型磁盘 I/O——InsightFace 会先给 `buffalo_l` **每个** `.onnx` 建 session 再按 `allowed_modules` 丢弃,故已**删掉用不到的** `1k3d68.onnx`(144MB)/`2d106det.onnx`/`genderage.onnx`,只留 `det_10g.onnx`+`w600k_r50.onnx`,冷读 341MB→191MB。别让它们被重新下载(整个 `buffalo_l` 目录在才不会重下;删单个文件不触发重下)。识别精度无损。再进一步:`w600k_r50` 走 **FP16 量化**(`scripts/quantize_model.py`,174MB→87MB,识别实测无损),release CI 在下载+剪枝后就地量化(见 `release.yml`);量化会留 `w600k_r50.fp32.bak`(本地回退用,CI 跳过),**`build_release.py` 忽略 `*.bak`、绝不入包**。若仍太慢,最后一条路是换 `buffalo_s`(识别模型~13MB,需重录入 + 重标定、精度略降)。
- **SYSTEM 服务专属的坑**:① 人脸库 DPAPI 必须用机器范围 `CRYPTPROTECT_LOCAL_MACHINE`(`platform_backend.py` 的 `_DPAPI_LOCAL_MACHINE=0x4`),否则 SYSTEM 服务解不开用户录入的库;② matplotlib(insightface 的传递依赖)在 SYSTEM 上下文首次建字体缓存会卡死/崩服务——`win_service.py` 在导入前设 `MPLBACKEND=Agg` + `MPLCONFIGDIR` 到 `data/`;③ **EcoQoS 降频**:后台/session-0 服务进程会被 Windows「执行速度节流」压低主频,纯 CPU 推理(InsightFace)实测慢约 4 倍(同一推理前台 ~700ms、服务里 ~2450ms),解锁体感拖慢约 1s。`service.py` 的 `_boost_cpu_scheduling()`(serve() 启动即调)用 `SetProcessInformation(ProcessPowerThrottling, StateMask=0)` 退出节流 + `SetPriorityClass(ABOVE_NORMAL)` 修复;注意这只发生在**真后台进程**,前台控制台测不出来(前台不被真节流)。识别耗时另有逐帧明细日志(`auth.py` 的 `t_detect`/`t_match`/`n_faces` → 「解锁明细」行)便于排查。
- **身份契约**:profile 名 == `GetUserName()`(本地 SAM 名)== LSA 键 `L$FaceHello_<user>` == KERB 账户名,四者必须一致,解锁才成立(MSA-backed 本地登录也走这条)。LSA 键名不能含反斜杠。
- **安全红线**:绝不移除系统的密码/PIN 提供程序(始终保留兜底登录);服务端管道 ACL 已限 SYSTEM+Administrators(`service.py` 的 `_pipe_security`),CP 端也会拒绝非 LocalSystem 服务端;CP 注册/真机测试先打快照、留个备用管理员账户与系统还原点。RGB 单目天然抗不住照片/视频攻击,活体检测是底线。
