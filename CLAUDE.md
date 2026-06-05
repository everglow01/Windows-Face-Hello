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

- 没有测试框架(pytest 等)。`scripts/offline_check.py` 是断言式自检,等价于冒烟测试:验证 matcher、DPAPI 加密往返、FaceMesh、InsightFace 加载。
- 首次运行自动下载模型到 `models/`:InsightFace `buffalo_l`(~281MB)、MediaPipe `face_landmarker.task`(~3.7MB)。`data/`(加密人脸库)和 `models/` 均 gitignored。
- `cred_vault` 的写/删需**管理员**终端;读需 **SYSTEM**(`psexec -s` 模拟,见 `cred_vault_cli.py` 顶部注释)。

## 架构

两层设计(路线 A)。当前阶段 1~4(Python 原型)完成,阶段 5(C++ Credential Provider 锁屏集成)未做。

**`face_hello/` 核心库**(无 Qt 依赖,可被 GUI、服务、脚本共用):
- `config.py` — 集中路径/模型/阈值。`DEFAULTS` 是阈值默认值,被 store 里持久化的 `settings` 覆盖。
- `camera.py` — OpenCV 采集,Windows 用 `CAP_DSHOW` 后端。
- `detector.py` — InsightFace `FaceAnalysis`(CPU),输出 512 维 `normed_embedding`。惰性加载 + `load()` 显式预热。
- `matcher.py` — 余弦相似度;embedding 已 L2 归一化,余弦即点积。
- `liveness.py` — MediaPipe Tasks `FaceLandmarker` 取 468 点 → EAR 判眨眼 + solvePnP 估 yaw 判转头。`LivenessSession` 是随机挑战(眨眼/左转/右转)+ 双重超时的逐帧状态机。
- `enroll.py` — `Enroller` 累积合格帧(过滤低分/太小的脸),取平均特征后重新归一化作模板。
- `store.py` — `FaceStore`:DPAPI(`win32crypt`)加密的 pickle 落盘到 `data/faces.dat`,存特征(非照片)+ 元数据 + settings。同名 profile 覆盖。
- `auth.py` — `AuthSession` 编排状态机:`liveness → recognize → done`,逐帧 `feed()` 驱动。`authenticate_blocking()` 是无 Qt 的阻塞版(开摄像头跑完整流程),供服务调用。
- `cred_vault.py` — 阶段 5 用:把登录密码存进 LSA Secret(键 `L$FaceHello_<user>`,UTF-16LE)。密码**永不经过 IPC**,由 CP 自己在 SYSTEM 上下文读。
- `service.py` — 命名管道(`\\.\pipe\FaceHello`)服务端,JSON 消息模式。命令 `ping` / `authenticate`,只返回 `{ok, user, similarity}`。

**`app/` PySide6 管理台**(三标签页:录入 / 测试解锁 / 设置):
- `main.py` — UI;`FaceDetector` 和 `FaceStore` 在 `MainWindow` 创建一次后注入各 Tab 共享。
- `workers.py` — 所有摄像头 + 推理放 `QThread`(`WarmupWorker`/`EnrollWorker`/`AuthWorker`),Signal 回主线程更新 UI,避免卡死。

数据流:`Camera` 出帧 → `AuthSession.feed()` 先跑 `liveness`,通过后 `detector` 提特征 → `matcher.best_match` 比对 `store` 里的 gallery → `AuthResult`。

## 本仓库特有的坑(改代码前必读)

- **工作目录含中文路径**。两个 C++ 后端库读不了非 ASCII 路径:
  - MediaPipe → 不能传模型路径,必须用 `model_asset_buffer=` 传字节(见 `liveness.py`)。
  - OpenCV → 不能用 `cv2.imread`,一律 `cv2.imdecode(np.fromfile(path), ...)`。
  - InsightFace/onnxruntime 加载 `.onnx` 支持 Unicode 路径,正常。
- **性能/预热**:首次推理有冷启动代价(onnxruntime + TFLite ~0.7s),已在启动期预热挪走。`detector.load()` 会真跑一次带人脸的样例图;`FaceMeshTracker` 也要预热一个实例。改启动路径时别破坏这个。`DET_SIZE=(320,320)` 且 `allowed_modules=["detection","recognition"]`(关掉 genderage/2d106/3d68)是有意的提速取舍。
- **MediaPipe 0.10.x 已移除 legacy `solutions`**,只能用 Tasks API,别退回旧写法。
- **安全红线**(阶段 5):绝不移除系统的密码/PIN 提供程序;管道要紧 ACL 限 SYSTEM;先在 VM/快照验证。RGB 单目天然抗不住照片/视频攻击,活体检测是底线。
