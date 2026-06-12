# Face_hello — 普通摄像头人脸解锁 Windows(设计文档)

> [English](./DESIGN.md) ｜ 让不支持 Windows Hello 的普通 RGB 摄像头(如笔记本前置摄像头 / USB 摄像头)也能用人脸识别解锁电脑。

本文是**设计与决策记录**:讲清楚为什么这么做、当前做到哪、还剩什么。面向用户的使用说明见 [README_zh.md](./README_zh.md);开发环境、代码地图、踩坑清单见 [contribute_zh.md](./contribute_zh.md)。

---

## 0. 当前进度总览

**主体已打通并发布(最新 `v0.1.2`):** 锁屏磁贴 → 命名管道 → LocalSystem 服务 → InsightFace 识别 → 读 LSA 密码 → 打包 KERB 真解锁,**本地账户与微软账户(MSA 本地登录)均已在 VM 与真机端到端验证**。已有一键安装包(Inno + 中文向导)、一键干净卸载、GitHub Release 自动化分发。

| 模块 | 状态 |
|------|------|
| 阶段 1–4:Python 识别 / 活体 / 录入 / 认证编排 + PySide6 管理台 | ✅ 完成 |
| 阶段 5:C++ Credential Provider 锁屏集成(磁贴 → 服务 → KERB 解锁) | ✅ 主体完成,真机验证 |
| 本地账户 + 微软账户(MSA-backed)解锁 | ✅ 端到端验证 |
| 锁屏期实时活体提示(`auth_start`/`auth_poll` 异步对) | ✅ 完成 |
| 锁屏磁贴自定义头像(WIC 读 `ProgramData`,回退纯蓝) | ✅ 完成 |
| 安装态 / 开发态路径分流(`.installed` 标记 + `FACEHELLO_HOME`) | ✅ 完成 |
| 便携包(standalone CPython + 依赖)+ Inno 安装器 + 中文向导 | ✅ 完成 |
| 一键干净卸载(停删服务、注销 CP、清 LSA 密码 + 人脸库) | ✅ 完成 |
| 体积瘦身:PySide6-Essentials + buffalo_l 剪枝 → `setup.exe` ~322MB | ✅ 完成 |
| GitHub Release 自动化(打 tag → CI 出 setup.exe) | ✅ 完成 |
| **5-4 加固:命名管道 ACL 限 SYSTEM、失败兜底 / 锁定、日志完善** | ⏳ 待做 |
| **代码签名(Authenticode / EV 证书免 SmartScreen)** | ⏳ 待定 |
| 进一步瘦身:opencv-headless、砍 scipy/onnx 传递依赖 | ⏳ 待做 |
| 被动活体(反欺骗 CNN)、pytest 测试框架 | ⏳ 待做 |

详细路线见 [§7 路线图](#7-路线图);剩余加固项见 [§9.2](#92-剩余加固5-4)和 [§10.5 发布前置](#105-发布前置)。

---

## 1. 背景与目标

Windows Hello 人脸不支持普通摄像头,根本原因不是模型不够好,而是**硬件与框架层的限制**:

1. **必须是 IR(红外)摄像头** —— 用于防伪(照片 / 屏幕攻击)+ 暗光成像。
2. **必须有 WBF 驱动** —— 摄像头要通过 Windows Biometric Framework 注册成「生物识别传感器」,系统才认。
3. **活体检测** —— IR + 深度天然能做,RGB 单目较弱。

**本项目目标**:用普通 RGB 摄像头 + 开源深度学习模型,实现「刷脸解锁电脑」,作为密码 / PIN 之外的**并列**登录方式(绝不删除密码登录)。

---

## 2. 技术路线选择

| 路线 | 原理 | 优点 | 缺点 | 结论 |
|------|------|------|------|------|
| **A. Credential Provider** | 实现 `ICredentialProvider` COM,加一个自定义登录方式,匹配成功后向 winlogon 提交凭据 | 无需 IR 硬件、无需驱动签名、模型自由 | C++ COM 调试痛苦;需安全存储密码 | **采用** |
| B. WBDI 生物识别驱动 | 写 UMDF 驱动把摄像头伪装成 Hello 兼容传感器(Sensor/Engine/Storage Adapter) | 原生接入「设置 → 登录选项 → 人脸」 | 复杂度高一档、需驱动签名、RGB 大概率被 IR/ESS 策略拒 | 放弃 |

**决策:走路线 A。** 先用 Python 把「识别 + 活体」管线跑通,再用 C++ Credential Provider 做登录集成层,两者通过本地 IPC(命名管道)通信。事实证明这条路走通了。

---

## 3. 系统架构(路线 A)

```
┌──────────────────────────────────────────────────┐
│ 锁屏 / 登录界面 (LogonUI, SYSTEM)                   │
│  └─ FaceHello Credential Provider (C++ COM DLL)    │
│        │  ① auth_start / auth_poll                 │
│        ▼                                            │
│  本地 IPC:命名管道 \\.\pipe\FaceHello (JSON)        │
│        │                                            │
│        ▼                                            │
│  人脸认证服务 (Python, LocalSystem, 常驻)            │
│   ├─ 摄像头采集 (OpenCV, CAP_DSHOW)                  │
│   ├─ 活体检测   (MediaPipe FaceLandmarker:眨眼/转头) │
│   ├─ 人脸识别   (InsightFace ArcFace, 512 维)        │
│   └─ 比对注册库 → 返回 {ok, user, similarity}        │
│        │                                            │
│        ▼  ② 匹配成功                                │
│  CP 在 SYSTEM 上下文自读 LSA Secret 里的密码,        │
│  构造 KERB_INTERACTIVE_UNLOCK_LOGON 提交解锁         │
└──────────────────────────────────────────────────┘
```

**两层是有意为之:** Python 那套识别算法塞不进 LogonUI 进程,所以拆成「DLL 负责 UI / 服务负责算法」,两者**只靠命名管道协议耦合**——改 Python 不必重编 DLL。**密码永不经过 IPC**:服务只回 `{ok, user, similarity}`,密码由 CP 自己在 SYSTEM 上下文读 LSA。

---

## 4. 模型选型

| 环节 | 实际采用 | 备注 |
|------|---------|------|
| 人脸检测 | InsightFace `det_10g`(buffalo_l) | 与识别同包,`DET_SIZE=(320,320)` |
| 特征识别 | **ArcFace `w600k_r50`**(buffalo_l,512 维) | onnxruntime CPU 推理,精度高 |
| 活体检测 | **主动**:眨眼(EAR)+ 转头(solvePnP)随机挑战 | MediaPipe Tasks `FaceLandmarker` 468 点 |

被动反欺骗 CNN(CASIA-SURF / replay 训练)列为**候选纵深防御**,当前未启用(见 [§11](#11-同类项目教训))。

---

## 5. 安全性现实(重要)

- 普通 RGB 单目**天然抗不住照片 / 视频攻击**,这正是微软强制 IR 的原因。
- 本方案**安全强度弱于原生 Hello**,且暗光基本不可用。
- **活体检测是底线**,否则一张照片就能解锁;别为「方便」默认关掉。
- 密码以 LSA Secret 存储,**永不经过 IPC**;人脸库存特征向量(非照片),DPAPI 机器范围加密落盘。
- **绝不移除系统的密码 / PIN 提供程序**——兜底登录必须始终在。CP 注册 / 真机测试先打快照 + 留备用管理员账户 + 系统还原点。
- **多账户防错配(margin)**:一台机器多人录入时,gallery 与单一阈值共用,`best_match` 取全库最相似者——若两人特征接近,可能把 A 判成 B 进而**解错账户**(单目 RGB 的固有弱点)。为此识别阶段加了 **margin 校验**:除了 `相似度 ≥ match_threshold`,还要求 `最佳 − 最相似的另一个人 ≥ match_margin`(默认 0.05);贴得太近则判为「身份不明确」直接拒绝,宁可让用户走密码兜底,也不冒险解错账户。只录一个人时无竞争者(margin=∞),不触发;阈值在设置页可调,`match_margin=0` 关闭。识别按 profile 名区分竞争者,同名多模板不互算对手。

---

## 6. 关键实现注记(落地时定的)

> 操作层面的踩坑清单(中文路径、`FaceLandmarker.close()` 阻塞 40s、SYSTEM 服务字体缓存等)已整理进 [contribute_zh.md](./contribute_zh.md),此处只记设计级决策。

- **活体取关键点**:mediapipe 0.10.x 已移除 legacy `solutions`,改用 **Tasks API `FaceLandmarker`**(`RunningMode.VIDEO` + 严格递增时间戳);EAR / solvePnP 下游逻辑不变。
- **中文路径绕法**:工作目录含中文 → mediapipe 用 `model_asset_buffer` 传字节、OpenCV 用 `cv2.imdecode(np.fromfile(...))`;InsightFace/onnxruntime 加载 `.onnx` 原生支持 Unicode,正常。
- **识别性能调优**:`FaceAnalysis(allowed_modules=["detection","recognition"])` 只跑 2 个模型;启动期 warmup 真跑一次样例图,把冷启动代价挪走。实测单脸 640×480 识别 ≈ 250ms。
- **冷启动磁盘 I/O**:删掉 buffalo_l 里用不到的 `1k3d68/2d106/genderage`,冷读 341MB → 191MB,识别精度无损。

---

## 7. 路线图

- [x] **阶段 1 — Python 识别原型**:摄像头 → 检测 → 识别(`camera/detector/matcher`)。
- [x] **阶段 2 — 活体检测**:眨眼(EAR)+ 转头(solvePnP)主动随机挑战(`liveness`)。
- [x] **阶段 3 — 注册 / 比对**:多帧平均特征录入 + DPAPI 加密入库(`enroll/store`)。
- [x] **阶段 4 — 认证编排 + 管理台**:`auth` 状态机 + PySide6 管理台(`app/`)。
- [x] **阶段 5 — Credential Provider**:C++ COM 锁屏集成 + LSA 凭据 + KERB 解锁。**主体完成、真机验证**(详见 §9)。
- [x] **分发 — setup.exe**:便携包 + Inno 中文向导 + 干净卸载 + Release 自动化,已发布 `v0.1.2`(详见 §10)。
- [ ] **加固(5-4)**:命名管道 ACL 限 SYSTEM、失败兜底 / 锁定、日志完善。
- [ ] **发布前置**:代码签名(EV 证书免 SmartScreen)。
- [ ] **可选增强**:被动活体、GPU 推理、pytest、进一步瘦身。

---

## 8. 阶段 5 设计决策(Credential Provider + 服务)

- **不走真·Hello(WBF 驱动)**:RGB 受 IR/ESS 策略限制,大概率无法注册为官方 Hello 人脸,放弃。
- **凭据存储 = LSA Secret**:`face_hello/cred_vault.py`,键名 `L$FaceHello_<user>`,密码 UTF-16LE。写 / 删需**管理员**(管理台),读需 **SYSTEM**(锁屏 CP)。
- **谁读密码 = CP 自己读**(它在 LogonUI 里是 SYSTEM)。**密码永不经过 IPC**;服务只回 `{ok, user, similarity}`。
- **身份契约**(四者一致才解得开):profile 名 == `GetUserName()`(本地 SAM 名)== LSA 键 `L$FaceHello_<user>` == KERB 账户名。微软账户走 MSA-backed 本地登录,也是这条链;LSA 键名不能含反斜杠。
- **组件划分**:
  - ① 管理台(GUI,管理员):录入人脸 + 写登录密码到 LSA Secret。
  - ② 认证服务(常驻,LocalSystem):相机 + 识别 + 活体,命名管道暴露 `authenticate` / `auth_start` / `auth_poll`。
  - ③ Credential Provider(C++ COM):锁屏磁贴 → 调 ② → 成功读 LSA → 构造 `KERB_INTERACTIVE_UNLOCK_LOGON` 提交。

---

## 9. 阶段 5 落地记录

### 9.1 已完成(里程碑 a→d)

- [x] **凭据保险箱 `cred_vault`**(LSA Secret 读写)+ 测试 CLI。管理员写 → SYSTEM 读验证通过。
- [x] **认证服务化**:命名管道 `\\.\pipe\FaceHello`,**单实例串行**,JSON 消息;同步 `ping`/`authenticate` + 异步 `auth_start`/`auth_poll`(锁屏边识别边刷活体提示)。客户端 `scripts/auth_client.py` 自测。
- [x] **C++ Credential Provider**(基于微软 SampleV2CredentialProvider):磁贴枚举、扫描线程轮询、`SignalAutoLogon` 自动提交、`GetSerialization` 读 LSA → KERB 解锁。
- [x] **锁屏磁贴自定义头像**:CP 用 WIC 读 `C:\ProgramData\FaceHello\` 第一张图(PNG/JPG/BMP)缩放成 128×128,失败回退纯蓝占位。
- [x] **端到端验证**:VM(打快照)+ 真机,**本地账户与微软账户**均成功刷脸解锁。SYSTEM/session-0 进程在锁屏能打开摄像头(服务可作 LocalSystem 常驻)。

### 9.2 加固(5-4,均已落地,纯 Python 侧)

- [x] **命名管道 ACL + 防抢注**:`service.py` 的 `CreateNamedPipe` 现带显式 DACL,只放行 **SYSTEM + Administrators**(CP 是 SYSTEM 能连;管理员身份的 GUI / `auth_client.py` 测试仍可用,挡掉本地非特权进程冒充 CP 调认证)。并加 `FILE_FLAG_FIRST_PIPE_INSTANCE`:同名实例已存在则创建失败 → 记安全告警 + 退避,不静默。
  - **残留风险(已知,留待将来闭合)**:服务是「建管道→应答→关→重建」单实例串行,`关→重建` 有微秒级空窗;DACL 拦不住「别的进程抢先创建同名管道」(那是它自己的内核对象)。彻底堵死抢注需 **CP 端连上后用 `GetNamedPipeServerProcessId` 校验服务端进程是 SYSTEM**——属 C++ DLL 改动,本轮（只改 Python）未做。主要缓解是 **LocalSystem 开机自启早于任何用户态代码、首个实例即占名**,空窗期抢注窗口极小。
- [x] **失败兜底 / 锁定**:`_AuthRunner` 服务侧内存计数——**只对真生物特征拒绝**(不匹配 / 身份歧义 / 活体失败 / 未见人脸)计数,基础设施错误(未录入 / 摄像头不可用 / 异常)不计;连续 `lockout_max_fails`(默认 5)次后冷却 `lockout_seconds`(默认 30)秒,期间 `auth_start` 直接回「已锁定,走密码」不开摄像头;成功或冷却到期清零。阈值在设置页可调(0 关闭)。摄像头路径超时从 30s 收到 8s(`authenticate_blocking(camera_timeout_s=8)`),设备缺失/被占时快速回退密码而非干等。系统密码 / PIN 提供程序始终保留,天然兜底。
- [x] **日志完善**:`service.py` 引入 `logging` + `RotatingFileHandler`(`service.log`,约 1MB×3,带时间戳 / 级别),替换裸 `print`;服务态用 `_StreamToLogger` 垫片把 `sys.stdout/stderr`(含原生库 print 与未捕获 traceback)转进同一滚动日志(纯 C 层 stderr 噪声可能不落盘,仅启动横幅、非审计内容)。**从不记密码**;记 user 名 + similarity(本地日志,SYSTEM / 管理员可读)。

---

## 10. 分发与安装包(setup.exe)

目标:一个 `setup.exe`(Inno Setup,管理员权限),在干净的 Win10/11 机器上一键完成「装文件 → 建可写数据目录 → 注册并自启服务 → 注册 CP DLL → 放管理台快捷方式」,并能**完全干净卸载**且绝不留下损坏的 LogonUI。**已实现并发布 `v0.1.2`。**

### 10.1 关键决策(均已落地)

- [x] **Python 运行时 = standalone CPython + 依赖随包**(非 PyInstaller)。带一份 python-build-standalone(uv 同源)+ 装好的 `site-packages`,服务 / GUI 用绝对路径调 `python.exe` 跑源码。理由:mediapipe / insightface / onnxruntime 的原生数据文件原样保留,避开冻结 hook 与 pywin32 服务冻结的坑。
- [x] **模型打进安装器**:buffalo_l(det_10g + w600k_r50,~191MB)+ face_landmarker.task(~3.7MB)内置,**首解锁不依赖联网**。
- [x] **安装态 / 开发态分流**:`config.py` 按安装根的 **`.installed` 标记文件**(或 `FACEHELLO_HOME`)切换。用标记文件而非只靠环境变量,是因为 SCM 把系统环境变量块缓存到下次重启,服务刚装好读不到新设的变量;标记文件随安装即落盘,服务 / GUI 立刻一致。
- [x] **C++ DLL 用 `/MT` 静态 CRT 编**:免装 VC++ 运行库。
- [ ] **代码签名**:暂未做。`setup.exe` / CP DLL 会触发 SmartScreen 警告但 CP 仍能加载。签名列为发布前最后一步(见 §10.5)。

### 10.2 安装布局

```
C:\Program Files\FaceHello\          (只读,程序文件)
  ├─ python\                         standalone CPython(含 site-packages)
  ├─ app\  face_hello\               源码(原样拷贝)
  ├─ winservice_main.py  uninstall_cleanup.py
  ├─ FaceHelloCP.dll                 (/MT 编译,Release|x64)
  ├─ models\  buffalo_l\ + face_landmarker.task
  └─ .installed                      安装态标记(空文件)

C:\ProgramData\FaceHello\           (可写,运行期数据;SYSTEM 与提权 GUI 共享)
  ├─ data\  faces.dat  service.log
  └─ <avatar>.png                   锁屏磁贴头像(CP 在 SYSTEM 读)
```

程序写入 ProgramData 的原因:Program Files 对普通用户只读,而**录入 GUI 跑在(提权)用户上下文、服务跑在 LocalSystem**,二者都要写 `faces.dat` / 日志。ProgramData 纯 ASCII、两边可写。

### 10.3 前置代码改动(均已完成)

- [x] **`config.py` 路径分流**:安装态 `DATA_DIR` → `C:\ProgramData\FaceHello\data`、`MODELS_DIR` → 安装根 `models\`;开发态保持仓库相对路径,不破坏 `uv run` 流程。
- [x] **服务 ImagePath 绝对路径**:`winservice_main.py` install 把 ImagePath 写成全路径带引号的 `python.exe ...winservice_main.py`,不依赖 venv / 当前目录。`MPLBACKEND=Agg` + `MPLCONFIGDIR` 指向 ProgramData 数据目录。
- [x] **CP DLL 头像路径**:`cp/CFaceCredential.cpp` 硬编码 `C:\ProgramData\FaceHello\` 与 `AVATAR_DIR` 一致。

### 10.4 构建与分发流水线(已实现)

- [x] **编 CP DLL**:`MSBuild cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64`(`/MT`)。
- [x] **便携包**:`scripts/build_release.py` —— 取 standalone CPython 3.11 → 装 `dist` 依赖组 → 瘦身 → 拷源码 + 模型 + DLL + pywin32 运行 DLL。产物默认 `%LOCALAPPDATA%\FaceHello-build\FaceHello`。
- [x] **Inno 编译**:`installer\FaceHello.iss` → `installer\Output\FaceHello-Setup-x.y.z.exe`。`.iss`/`.isl` 为 **UTF-8 with BOM**(否则中文 Windows 当 GBK 读 → 乱码)。中文向导随仓库带 `ChineseSimplified.isl`(Inno 不自带中文)。
- [x] **CD 自动化**:`.github/workflows/release.yml` —— 打 `v*` tag 触发:备模型 → 编 DLL + 便携包 → Inno 打 setup.exe → 传 GitHub Release。版本号从 tag 注入,`installer`/`pyproject` 不必手改。
- [ ] **签名**:发布前最后一步,暂未做。

### 10.5 卸载(完全干净;安全红线:不能留坏 CP)

`installer\FaceHello.iss` 的 `[UninstallRun]` + `[UninstallDelete]` 已实现,顺序为先停服务再反注册再删文件:

- [x] `winservice_main.py stop` → `regsvr32 /s /u FaceHelloCP.dll`(**先反注册再删 DLL**,否则注册表残留指向不存在的 DLL → LogonUI 风险)→ `winservice_main.py remove`。
- [x] **完全干净**:`uninstall_cleanup.py` 清 LSA 登录密码 + 删人脸库;`[UninstallDelete]` 删 ProgramData 数据目录与安装目录下运行期生成的文件(.pyc / .installed / service.log / 头像)。
  > 卸载策略已从早期「弹窗问用户保留还是删」改为**无条件清干净**(用户明确要求「完全干净的卸载」)。
- [x] 恢复路径(文档化):若 CP 异常,安全模式 / 另一管理员账户 `regsvr32 /u` / 删 HKLM Credential Providers 下本 CLSID 键。

### 10.6 发布前置

- [x] 干净 VM(快照)端到端:装 → 录入 → 锁屏解锁 → 卸载干净、LogonUI 正常。
- [x] 真机端到端(本地 + 微软账户)。
- [ ] Authenticode 签名 `setup.exe` + `FaceHelloCP.dll` + 嵌入式 `python.exe`(EV 证书免 SmartScreen)。
- [ ] 5-4 加固收尾(管道 ACL、失败兜底、日志)建议先于更大范围公开分发完成。

### 10.7 安装路径策略(已实现)

- [x] 安装目录用户可选(`DefaultDirName={autopf}\FaceHello`,可改)。大头(模型 + Python 依赖)随安装目录走,**装到 D: 则 C: 几乎不占**。
- ✅ 任意**固定内置 NTFS 盘**(C/D/E…)。
- ❌ 禁**可移动 / USB 盘、网络盘、开机未自动解锁的 BitLocker 盘**——CP DLL 要在锁屏(LogonUI/SYSTEM)早期加载,这些盘那时可能未挂载 → 磁贴加载失败。
- **唯一固定在 C 盘的是 `C:\ProgramData\FaceHello\data`**(人脸库 + 日志,很小,几十 KB ~ 几 MB)。
- 含空格路径回归:`C:\Program Files\FaceHello` 本身含空格,ImagePath 已全路径带引号,VM/真机安装自启验证通过(参考 §11 对方 #25 教训)。

### 10.8 体积:实测与瘦身

`setup.exe` 实测 **~322MB**(`v0.1.x`),靠以下手段达成,无识别精度损失:

- [x] **PySide6 → PySide6-Essentials**(`dist` 依赖组):去掉 Addons,最大头是 `Qt6WebEngineCore.dll`(~196MB);再手删 `qml/`、非中英 `translations/`、`include/` 等。
- [x] **buffalo_l 剪枝**:删 `1k3d68`(144MB)/`2d106`/`genderage`,只留 det_10g + w600k_r50。
- [x] **排除 `buffalo_l.zip`**:insightface 下载后残留的解压前原始包(~281MB),不进包(否则 setup.exe 直接翻倍到 ~597MB——CI 全新下载踩过这个坑)。
- [x] **通用清理**:`__pycache__`、`tests/`。

**可选的进一步瘦身(暂未做,优先级低)**:
- [ ] **opencv-python → opencv-python-headless**:dist 组当前仍用 `opencv-python`。注意 mediapipe 强依赖 `opencv-contrib-python`(也提供 cv2),headless 替换省不掉两者并存,需另行实测裁剪。
- [ ] **砍传递依赖**:`scipy`(92M)、`onnx`(41M,≠运行所需的 `onnxruntime`)。`skimage` 几乎确定要留(insightface 人脸对齐用 `SimilarityTransform`,又拖 scipy);`onnx` 包(模型构建用,推理只靠 onnxruntime)可能可删,须 `offline_check.py` 实测后再动。

### 10.9 已消解的风险

- [x] **standalone CPython 的 pywin32 服务可用性**:已验证。`build_release.py` 把 `pythoncomXX.dll`/`pywintypesXX.dll` 拷到 python 根,服务(SYSTEM)能正常 import `win32service`/`servicemanager` 并被 SCM 拉起。
- [x] **GitHub Release 资产体验**:~322MB 单文件上传 / 下载正常,远低于 2GB 上限。

---

## 11. 同类项目教训(参考 FaceWinUnlock-Tauri)

[FaceWinUnlock-Tauri](https://github.com/zs1083339604/FaceWinUnlock-Tauri)(Tauri+Vue3 GUI / Rust CP DLL / OpenCV 识别 / SQLite 存凭据,2026-03 起核心闭源)功能与本项目重合,从其真实用户 bug 列表提炼出:

- [x] **含空格安装路径**:对方 #25 是开机自启在带空格路径下失败。本项目服务 ImagePath 全路径带引号,`C:\Program Files\FaceHello`(含空格)安装自启已回归验证(见 §10.7)。
- [x] **卸载顺序佐证**:对方「先卸核心组件 → 再卸主程序,否则残留坏 CP」与本项目「先停服务 → `regsvr32 /u` → 再删」一致。
- **旁证**:对方也踩 OpenCV 中文目录问题,验证本项目 `imdecode` / `model_asset_buffer` 绕法的必要性。

**调研项(暂不定)**:对方用通义 RGB 被动活体模型(`cv_manual_face-liveness_flrgb`,阈值 0.6)替代主动挑战,体验更顺,但其自承活体准确率一直未调好。可作为本项目「低打扰模式」或纵深防御候选,优先级低于现有主动挑战。

> **架构差异结论**:对方密码**明文经管道传输**(其 README 自承嗅探风险),本项目密码**永不过 IPC**(CP 在 SYSTEM 自读 LSA);识别用 ArcFace 512 维优于其 OpenCV 传统特征。体积上对方 Rust + 系统 WebView2 远小于本项目嵌入式 Python,但不构成重写理由(见 §10.8 取舍)。

---

## 12. 参考

- Linux 上的 **Howdy**(普通摄像头 + PAM 类 Hello 人脸登录)—— 识别 / 活体思路可借鉴。
- 微软官方样例 `microsoft/Windows-classic-samples` → `SampleV2CredentialProvider`(Credential Provider 骨架)。
- InsightFace:<https://github.com/deepinsight/insightface>
