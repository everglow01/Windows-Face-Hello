# 开发者文档 / 贡献指南

> [English](./contribute.md)

这份文档是写给开发者用户，以及各类AI Agent。面向用户的安装与使用说明在 [README_zh.md](./README_zh.md);背景、技术路线选择(Credential Provider vs WBF 驱动)、安全权衡和阶段路线图见 [DESIGN_zh.md](./DESIGN_zh.md)。

---

## 架构简述

让一个常驻的 Windows 系统服务在 SYSTEM 上下文做人脸识别,锁屏的 C++ 凭据提供程序只管 UI 和提交凭据,两边靠一条本地命名管道通信。

```
锁屏「Face Unlock」磁贴(C++ CP, 跑在 LogonUI/SYSTEM)
        │  命名管道 \\.\pipe\FaceHello (JSON 消息)
        ▼
LocalSystem 系统服务(Python, 常驻)
        │  调核心库
        ▼
face_hello/ 核心库:摄像头 → 活体 → 识别 → 比对 → 读 LSA 密码 → 打包 KERB 解锁
```

设计两层是有意为之:Python 那套识别算法不可能硬塞进 LogonUI 进程,所以拆成「DLL 负责 UI / 服务负责算法」,两者**只靠命名管道协议耦合**——改 Python 不必重编 DLL,反之亦然。

---

## 开发环境搭建

- **Python 3.11**(项目锁 `>=3.10,<3.12`)
- [**uv**](https://docs.astral.sh/uv/) 管包和虚拟环境
- 改 / 编 C++ CP 才需要:**VS2022** + 「使用 C++ 的桌面开发」

```powershell
git clone https://github.com/everglow01/Windows-Face-Hello.git
cd Windows-Face-Hello

uv sync                                   # 创建 .venv 并装依赖(独立虚拟环境,非 base)
uv run python scripts/offline_check.py    # 改完核心库先跑这个,全 [ok] 才算没坏
uv run python -m app.main                 # 启管理台 GUI
```

> 首次运行自动下模型到 `models/`:InsightFace `buffalo_l`(~191MB)、MediaPipe `face_landmarker.task`(~3.7MB)。`models/` 和 `data/`(加密人脸库)都 gitignored,别入库。

**没有 pytest 之类的测试框架。** `scripts/offline_check.py` 是断言式自检,等价于冒烟测试——它不需要摄像头 / 显示器,验证 matcher、DPAPI 加密往返、FaceMesh、InsightFace 加载这四条核心链路。**改完 `face_hello/` 里的东西,提交前务必先跑断言式自检**   

有计划加入pytest和其他的测试用例，但当前项目体量较小，作者精力有限，有想法的开发者欢迎提交issue讨论pytest事宜。   

---

## Code Map

### `face_hello/` —— 核心库(无 Qt 依赖,GUI / 服务 / 脚本共用)

| 文件 | 职责 |
|------|------|
| `config.py` | 集中路径 / 模型 / 阈值。`DEFAULTS` 是阈值默认值,被 store 里持久化的 `settings` 覆盖。也是**安装态 / 开发态分流**的地方(见下) |
| `camera.py` | OpenCV 采集,Windows 用 `CAP_DSHOW` 后端,带冷启动 / 唤醒退避重试 |
| `detector.py` | InsightFace `FaceAnalysis`(CPU),输出 512 维 `normed_embedding`。惰性加载 + `load()` 显式预热 |
| `matcher.py` | 余弦相似度;embedding 已 L2 归一化,余弦即点积 |
| `liveness.py` | MediaPipe Tasks `FaceLandmarker` 取 468 点 → EAR 判眨眼 + solvePnP 估 yaw 判转头。`LivenessSession` 是随机挑战(眨眼 / 左转 / 右转)+ 双重超时的逐帧状态机 |
| `enroll.py` | `Enroller` 累积合格帧(过滤低分 / 太小的脸),取平均特征后重新归一化作模板 |
| `store.py` | `FaceStore`:DPAPI 加密的 pickle 落盘到 `data/faces.dat`,存特征(**非照片**)+ 元数据 + settings。同名 profile 覆盖 |
| `auth.py` | `AuthSession` 编排 `liveness → recognize → done` 状态机,逐帧 `feed()` 驱动。`authenticate_blocking()` 是无 Qt 的阻塞版,供服务调用 |
| `cred_vault.py` | 把登录密码存进 LSA Secret(键 `L$FaceHello_<user>`)。密码**永不经过 IPC**,由 CP 自己在 SYSTEM 读 |
| `service.py` | 命名管道服务端,**单实例串行**,JSON 消息。同步 `ping`/`authenticate`;异步对 `auth_start`(后台跑一次认证)+ `auth_poll`(取实时活体提示与结果),让锁屏边识别边刷提示 |
| `win_service.py` | 把 `serve()` 封成 LocalSystem Windows 服务 |

### 其它目录

- `app/` —— PySide6 管理台。`main.py` 是 UI;`workers.py` 把所有摄像头 + 推理塞进 `QThread`,Signal 回主线程更新,避免卡死。
- `cp/` —— C++ Credential Provider(COM in-proc DLL)。`CFaceProvider`(枚举磁贴)、`CFaceCredential`(扫描线程 + 提交凭据)、`PipeClient`(管道客户端)。详见 [cp/README.md](./cp/README.md)。
- `scripts/` —— `offline_check.py`(自检)、`liveness_tune.py`(标定活体阈值)、`auth_client.py`(模拟 CP 调服务)、`cred_vault_cli.py`(LSA 读写测试)、`build_release.py`(打便携包)。
- `winservice_main.py` / `uninstall_cleanup.py` —— 仓库根的引导脚本(服务宿主、卸载清理)。
- `installer/` —— Inno Setup 脚本 + 中文语言文件,打 setup.exe。
- `.github/workflows/` —— `ci.yml`(每次 push 的构建安全验证)、`release.yml`(git推送release)。

---

## 常用命令速查

```powershell
uv sync                                                   # 装依赖
uv run python scripts/offline_check.py                    # 离线自检(改核心库先跑)
uv run python -m app.main                                 # 管理台 GUI
uv run python -m scripts.liveness_tune                    # 标定活体阈值(实时 EAR/yaw,退出给建议值)
uv run python -m face_hello.service                       # 前台跑命名管道服务(调试用)
uv run python -m scripts.auth_client ping|authenticate    # 测试客户端,模拟 CP 调服务
uv run python -m scripts.cred_vault_cli set|get|clear [用户名] [--show]   # LSA 读写测试
```

Windows 服务(LocalSystem,开机自启;**需管理员**;`<venv>` = `.venv\Scripts\python.exe`):

```powershell
<venv> winservice_main.py install --startup auto   # 注册并设开机自启(选项必须在 install 之前)
<venv> winservice_main.py start | stop | remove     # 起 / 停 / 删;或 sc.exe start|stop FaceHello
```

> ⚠️ PowerShell 里 `sc` 是 `Set-Content` 的别名,查 / 控服务一律用 `sc.exe`。

编 C++ CP(**用 PowerShell,别用 Bash**——MSYS 会损坏 `/p:` 参数):

```powershell
MSBuild.exe cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
# 产物 cp\x64\Release\FaceHelloCP.dll;改 Python 不必重编它,二者只靠命名管道协议耦合
```

`cred_vault` 的写 / 删需**管理员**终端,读需 **SYSTEM**(`psexec -s` 模拟,见 `cred_vault_cli.py` 顶部注释)。服务跑起来排错看 `data/service.log`(服务无控制台,stdout/stderr 都写入`service.log`文件)。

---

## 数据流(锁屏解锁)

```
CP 磁贴选中 → 服务 auth_start 起后台线程 → AuthSession.feed() 逐帧
  → 先跑 liveness(活体关则跳过)→ 通过后 detector 提 512 维特征
  → matcher.best_match 比对 gallery → AuthResult
  → CP auth_poll 拿到 user → 读 LSA 密码 → 打包 KERB_INTERACTIVE_UNLOCK_LOGON 解锁
```

**身份契约**(四者必须一致,解锁才成立):profile 名 == `GetUserName()`(本地 SAM 名)== LSA 键 `L$FaceHello_<user>` == KERB 账户名。微软账户走 MSA-backed 本地登录,也是这条链。LSA 键名不能含反斜杠。

---

## 安装态 vs 开发态(`config.py`)

`config.py` 按**安装根的 `.installed` 标记文件**(或环境变量 `FACEHELLO_HOME`)分流:

- **开发态**(uv run,没有标记):一切走仓库相对路径,数据存放在工作空间中 `data/`,CP DLL 在 `cp/x64/Release/`。
- **安装态**(setup.exe 装的):程序文件在只读安装目录,可写数据固定存放 `C:\ProgramData\FaceHello\data`(SYSTEM 服务 + 提权 GUI 共享)。

> 为什么用标记文件而不是只靠环境变量?因为 SCM 把系统环境变量块缓存到下次重启,服务刚装好当下读不到新设的 `FACEHELLO_HOME`;标记文件随安装写入存储,服务 / GUI 直接同步,无需重启。改启动 / 路径相关的逻辑时,两套状态都应考虑到。

阈值默认值都在 `config.py` 的 `DEFAULTS` 里(`match_threshold`、`ear_threshold`、`yaw_threshold_deg`、`required_blinks` 等),运行期被 store 持久化的 `settings` 覆盖。**禁止在代码里写死阈值**,强制走这套覆盖机制。

---

## 项目在开发时踩过的坑(改代码前必读)

这些都是踩过的雷,不是理论风险:   
如果你是AI Agent，请将下面的内容写入你的项目记忆，确保不要犯错。

### 中文 / 非 ASCII 路径
工作目录常含中文,两个 C++ 后端库读不了非 ASCII 路径:
- **MediaPipe** → 不能传模型路径,必须用 `model_asset_buffer=` 传字节(见 `liveness.py`)。
- **OpenCV** → 不能用 `cv2.imread` / `cv2.imwrite`,一律 `cv2.imdecode(np.fromfile(path), ...)`。
- InsightFace / onnxruntime 加载 `.onnx` 支持 Unicode 路径,正常。

### MediaPipe Tasks API
- MediaPipe 0.10.x **已移除 legacy `solutions`**,只能用 Tasks API,别退回旧写法。
- `FaceLandmarker` 用 `RunningMode.VIDEO` + 严格递增时间戳(`detect_for_video`,每帧 `_ts_ms += 33`)。IMAGE 模式偶发单帧卡死数十秒。
- **`FaceLandmarker.close()` 会阻塞约 40s**(等内部图 / 线程退出)。**绝不能在主流程同步调**——`AuthSession._finish` 和 `service._warm_liveness` 都把它丢到 daemon 线程关，否则容易出现解锁程序在锁屏界面卡死的问题，在测试中曾经卡死延迟超过40秒

### 性能 / 预热
- 首次推理有冷启动代价(onnxruntime + TFLite ~0.7s),已在启动期预热挪走。`detector.load()` 真跑一次带人脸的样例图;`FaceMeshTracker` 也要预热一个实例。**改启动路径别破坏这个。**
- `DET_SIZE=(320,320)` + `allowed_modules=["detection","recognition"]`(关掉 genderage/2d106/3d68)是**有意的提速取舍**。
- 模型磁盘 I/O 是冷启动慢的大头:已**删掉 `buffalo_l` 里用不到的** `1k3d68.onnx`(144MB)/`2d106det.onnx`/`genderage.onnx`,只留 `det_10g.onnx` + `w600k_r50.onnx`,冷读 341MB→191MB,识别精度无损。**别让它们被重新下载**(整个 `buffalo_l` 目录在才不会重下;删单个文件不触发重下)。

### SYSTEM 服务专属
- 人脸库 DPAPI 必须用**机器范围** `CRYPTPROTECT_LOCAL_MACHINE`(`store.py` 的 `_LOCAL_MACHINE=0x4`),否则 SYSTEM 服务解不开用户录入的库。
- matplotlib(insightface 传递依赖)在 SYSTEM 首次建字体缓存会卡死 / 崩服务——`win_service.py` 在导入前设 `MPLBACKEND=Agg` + `MPLCONFIGDIR` 到 `data/`。
- 服务 ImagePath 用 venv 的 python 直接跑 `winservice_main.py` 引导脚本(把根目录加进 `sys.path`),**不用**默认 `PythonService.exe`——后者在 SCM 上下文 import 不到 `face_hello`(`package=false`,没装进 venv)。

---

## 构建与发布

### 便携包(`scripts/build_release.py`)
非 PyInstaller 冻结,而是带一份 standalone CPython + 分发依赖(`dist` 依赖组,PySide6 换瘦身的 `-Essentials`)+ 源码原样拷贝。产物默认在 `%LOCALAPPDATA%\FaceHello-build\FaceHello`,可 `pythonw.exe -m app.main` 直接验证脱离 uv 启动。

### 安装包(`installer/FaceHello.iss`)
Inno Setup 把便携包打成单文件 `setup.exe`:中文向导、自动注册 / 启动服务 + 注册 CP、一键干净卸载(停删服务、注销 CP、清 LSA 密码 + 人脸库)。`.iss` / `.isl` 是 **UTF-8 with BOM**,否则在中文 Windows 上被当 ANSI/GBK 读 → 乱码。

### CI / CD
- `ci.yml` —— 每次 push 的“守门员”。
- `release.yml` —— 打 `v*` tag 触发:加载模型 → 编 DLL + 便携包 → Inno 打 setup.exe → 传 GitHub Release。也能手动 `workflow_dispatch` 只产 artifact 试打。
- runner 默认编码会让 print 中文 `UnicodeEncodeError`,CI 里统一开 `PYTHONUTF8=1`;`package=false` 要把仓库根加进 `PYTHONPATH`。

发版打 tag(版本号从 tag 注入,`installer` 和 `pyproject` 不必手改):

```powershell
git tag v0.1.x
git push origin v0.1.x
```    

release notes需要自己手动重写。

---

## 调试技巧

- **服务没有GUI控制台**,stdout/stderr/异常写在 `data/service.log`(开发态在仓库 `data/`,安装态在 `C:\ProgramData\FaceHello\data`)。排查服务问题先看它。
- 不想装服务也能调:`uv run python -m face_hello.service` 前台起,再用 `scripts/auth_client.py` pin它。
- 锁屏 / CP 相关的改动调试**必须先在打了快照的 VM 或留了系统还原点 + 备用管理员账户的真机上测**——坏掉的 CP 能让登录界面进不去，这点对于开发来说非常重要。
- 活体阈值不准就 `uv run python -m scripts.liveness_tune` 实时看 EAR/yaw,退出会给建议值,填回设置页。

---

## 安全红线

- **绝不移除 / 替换系统的密码 / PIN 提供程序**，此乃开发安全底线，CP 只新增磁贴,不当 filter。     
- 人脸库只存特征向量,不存照片;DPAPI 加密落盘,不上云，隐私安全。    
- 登录密码只进 LSA Secret,**永不经过 IPC**;服务响应只回 `{ok, user, similarity}`,不回密码，防止木马软件或植入程序监听密码。   

---

## 提 PR 的一些约定

- 改 `face_hello/`内部的Py代码 先让 `offline_check.py` 全 `[ok]`,再提 PR。
- 提交PR的信息中英文皆可。   
- 改动尽量聚焦,别“顺手”优化无关代码。   
- 锁屏 / CP / 服务相关的改动,在 PR 里说明你在什么环境(VM? 真机? 本地 / 微软账户?)验证过。   
- 大的技术决策(换模型、换识别后端、动 IPC 协议、前端大改)请先开 issue 讨论,这些都牵一发动全身,理由见 DESIGN_zh.md。  
- 代码层次的优化、模块化可以直接提交 PR，附上详细说明即可。

欢迎来玩 🙌
