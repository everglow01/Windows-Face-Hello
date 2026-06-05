# Face_hello

让普通 RGB 摄像头也能人脸解锁 Windows。设计与决策见 [DESIGN.md](./DESIGN.md)。

## 状态

阶段 1~4 完成(Python 原型:采集 / 检测识别 / 眨眼+转头活体 / DPAPI 加密存储 / PySide6 管理台)。
阶段 5(锁屏 Credential Provider)未做,见 DESIGN 路线图。

## 环境(uv 管理,Python 3.11)

```powershell
uv sync                       # 创建 .venv 并安装依赖
uv run python -m scripts.offline_check   # 离线自检(不需摄像头)
uv run python -m app.main     # 启动管理台 GUI
```

首次运行会自动下载模型:InsightFace `buffalo_l`(~281MB)→ `models/buffalo_l/`,
MediaPipe `face_landmarker.task`(~3.7MB)→ `models/`。

## 使用

1. **录入人脸**:输入用户名 → 开始录入,正对摄像头采集若干帧。
2. **测试解锁**:按提示完成活体动作(随机:眨眼 N 次 / 向左 / 向右转头)→ 识别比对。
3. **设置与安全**:查看/删除已录入用户、人脸有效期;调匹配阈值、转头角度、眨眼次数、有效期天数。

## 目录

```
face_hello/   核心库
  camera.py     摄像头采集
  detector.py   InsightFace 检测 + 512 维特征
  matcher.py    余弦相似度比对
  liveness.py   FaceLandmarker → EAR 眨眼 + solvePnP 转头 + 随机挑战
  enroll.py     多帧平均特征录入
  store.py      DPAPI 加密人脸库 + 设置
  auth.py       认证编排(活体→识别)状态机
app/          PySide6 管理台(main.py + 后台 workers.py)
scripts/      offline_check.py 离线自检
data/         加密人脸库(gitignored)
models/       模型权重(gitignored)
```
