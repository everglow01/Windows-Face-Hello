# Face_hello — 普通摄像头人脸解锁 Windows

> 让不支持 Windows Hello 的普通 RGB 摄像头(如本机笔记本前置摄像头)也能用人脸识别解锁电脑。

## 1. 背景与目标

Windows Hello 人脸不支持普通摄像头,根本原因不是模型不够好,而是 **硬件与框架层的限制**:

1. **必须是 IR(红外)摄像头** —— 用于防伪(照片/屏幕攻击)+ 暗光成像。
2. **必须有 WBF 驱动** —— 摄像头要通过 Windows Biometric Framework 注册成"生物识别传感器",系统才认。
3. **活体检测** —— IR + 深度天然能做,RGB 单目较弱。

**本项目目标**:用普通 RGB 摄像头 + 自训练/开源深度学习模型,实现"刷脸解锁电脑",作为密码/PIN 之外的并列登录方式。

## 2. 技术路线选择

| 路线 | 原理 | 优点 | 缺点 | 结论 |
|------|------|------|------|------|
| **A. Credential Provider** | 实现 `ICredentialProvider` COM,加一个自定义登录方式,匹配成功后向 winlogon 提交凭据 | 无需 IR 硬件、无需驱动签名、模型自由 | C++ COM 调试痛苦;需安全存储密码(DPAPI) | **采用** |
| B. WBDI 生物识别驱动 | 写 UMDF 驱动把摄像头伪装成 Hello 兼容传感器(Sensor/Engine/Storage Adapter) | 原生接入"设置→登录选项→人脸" | 复杂度高一档、需驱动签名 | 暂不采用 |

**决策:走路线 A。** 先用 Python 把"识别+活体"管线跑通验证,再用 C++ Credential Provider 做登录集成层,两者通过本地 IPC(命名管道)通信。

## 3. 系统架构(路线 A)

```
┌─────────────────────────────────────────────┐
│ 锁屏 / 登录界面 (LogonUI)                       │
│  └─ FaceHello Credential Provider (C++ COM)    │
│        │  ① 触发认证                            │
│        ▼                                        │
│  本地 IPC (命名管道)                            │
│        │                                        │
│        ▼                                        │
│  人脸认证服务 (Python/原型 → 后期可编译)         │
│   ├─ 摄像头采集 (OpenCV)                         │
│   ├─ 人脸检测   (MediaPipe / RetinaFace)        │
│   ├─ 特征识别   (ArcFace / InsightFace)         │
│   ├─ 活体检测   (眨眼/转头 + 反欺骗 CNN)         │
│   └─ 比对注册库 → 返回 匹配/拒绝                  │
│        │                                        │
│        ▼  ② 匹配成功                            │
│  Credential Provider 取出 DPAPI 加密的密码,     │
│  构造 KERB_INTERACTIVE_UNLOCK_LOGON 提交解锁     │
└─────────────────────────────────────────────┘
```

## 4. 模型选型

| 环节 | 方案 | 备注 |
|------|------|------|
| 人脸检测 | MediaPipe Face Detection / RetinaFace | MediaPipe 轻量、落地快 |
| 特征识别 | **ArcFace (InsightFace)** 首选;FaceNet/dlib 备选 | InsightFace 准确率高,onnxruntime 推理 |
| 活体检测(必做) | 主动:眨眼/转头挑战;被动:反欺骗 CNN(CASIA-SURF/replay 训练) | RGB 必须有活体,否则照片即可解锁 |

## 5. 安全性现实(重要)

- 普通 RGB 单目**天然抗不住照片/视频攻击**,这正是微软强制 IR 的原因。
- 本方案**便利性 OK,安全强度弱于原生 Hello**,暗光基本不可用。
- **活体检测是底线**,否则一张照片就能解锁。
- 密码必须 DPAPI 加密存储,不可明文。

## 6. 参考

- Linux 上的 **Howdy**(普通摄像头 + PAM 类 Hello 人脸登录)—— 识别/活体思路可借鉴。
- 微软官方样例 `microsoft/Windows-classic-samples` → `SampleV2CredentialProvider`(Credential Provider 骨架)。
- InsightFace:<https://github.com/deepinsight/insightface>

## 7. 路线图

- [x] **阶段 1 — Python 识别原型**:摄像头采集 → 检测 → 识别(`camera/detector/matcher`)。
- [x] **阶段 2 — 活体检测**:眨眼(EAR)+ 转头(solvePnP)主动随机挑战(`liveness`)。
- [x] **阶段 3 — 注册/比对**:多帧平均特征录入 + DPAPI 加密入库(`enroll/store`)。
- [x] **阶段 4 — 认证编排 + 管理台**:`auth` 状态机 + PySide6 三视图(`app/`)。
- [ ] **阶段 5 — Credential Provider**:C++ COM,锁屏集成 + DPAPI 凭据提交(独立里程碑)。

> 阶段 1~4 已离线自检通过(`scripts/offline_check.py`);摄像头端到端(录入/解锁/照片防伪)需本人交互验证。

## 8. 环境与实现注记(落地时定的)

- **环境**:uv 管理,Python 3.11,虚拟环境 `.venv`(非 base)。
- **活体取关键点**:本机 mediapipe 0.10.35 已移除 legacy `solutions`,改用 **Tasks API `FaceLandmarker`**;
  EAR/solvePnP 下游逻辑不变。
- **中文路径坑**:工作目录含中文。
  - mediapipe C++ 无法按路径打开模型 → 改用 `model_asset_buffer` 传字节。
  - `cv2.imread` 同样读不了中文路径 → 读图一律用 `cv2.imdecode(np.fromfile(p), ...)`。
  - InsightFace/onnxruntime 加载 `.onnx` 支持 Unicode 路径,正常。
- **识别性能调优**(解锁卡顿优化):
  - `FaceAnalysis(allowed_modules=["detection","recognition"])` 只跑 2 个模型,关掉
    genderage/2d106/3d68;`DET_SIZE=(320,320)`。
  - 启动 warmup 真正跑一次 `app.get(样例图)`,把 onnxruntime 冷启动代价挪到启动期。
  - 实测单脸 640×480 识别 ≈ 250ms(优化前首次解锁约 1.5~2s)。
- **待确认**:本机摄像头是否仅普通 RGB(无 IR/深度)—— 影响后续被动反欺骗选型。

## 9. 阶段 5 落地决策(路线 A:Credential Provider + 服务)

- **不走真·Hello(WBF 驱动)**:RGB 受 IR/ESS 策略限制,大概率无法注册为官方 Hello 人脸,放弃。
- **凭据存储 = LSA Secret**:`face_hello/cred_vault.py`,键名 `L$FaceHello_<user>`,密码以 UTF-16LE 存。
  - 写/删需**管理员**(管理台);读需 **SYSTEM**(锁屏的 CP)。
- **谁读密码 = Credential Provider 自己读**(它在 LogonUI 里是 SYSTEM)。
  **密码永不经过 IPC**;服务只返回 `{匹配, 用户名}`。
- **组件划分**:
  - ① 管理台(现有 GUI,管理员):录入人脸 + 写登录密码到 LSA Secret。
  - ② 认证服务(常驻,LocalSystem):相机 + 识别 + 活体,命名管道(ACL 限 SYSTEM)暴露 `authenticate`。
  - ③ Credential Provider(C++ COM):锁屏磁贴 → 调 ② → 成功则读 LSA Secret →
    构造 `KERB_INTERACTIVE_UNLOCK_LOGON` 提交。
- **安全红线**:绝不移除密码/PIN 提供程序;全程先在 **VM/快照** 验证;管道上紧 ACL。

### 阶段 5 构建顺序
1. [x] 凭据保险箱 `cred_vault`(LSA Secret 读写)+ 测试 CLI。
   **已验证**:管理员写 → SYSTEM 读(计划任务跑出 `WORKGROUP\DCR$` 即 SYSTEM)成功读回密码。
   SYSTEM 在本机也能访问 OneDrive 路径(无 0x2);正式部署仍建议装到 `C:\Program Files\FaceHello`。
2. [进行中] 认证服务化:无界面 `authenticate → {ok, user}`,命名管道 `\\.\pipe\FaceHello` + 客户端自测。
3. C++ Credential Provider(基于微软 SampleV2CredentialProvider),VM 内联调。
4. 加固:活体、防锁死回退、管道 ACL(限 SYSTEM)、日志、设备忙兜底;打包签名。
