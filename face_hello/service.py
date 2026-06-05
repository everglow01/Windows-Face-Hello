"""认证服务:命名管道服务端,供 Credential Provider 请求刷脸认证。

请求/响应都是单条 JSON(消息模式管道):
  请求  {"cmd": "ping"}            -> {"ok": true, "ready": true, "users": [...]}
  请求  {"cmd": "authenticate"}    -> {"ok": true, "user": "owen", "similarity": 0.6}
                                   或 {"ok": false, "reason": "..."}

设计:密码不经过本服务——服务只回 {ok, user},由 CP 自己读 LSA Secret 提交。
当前为控制台常驻进程(开发/自测用);正式部署再封成 Windows 服务(阶段 5-4)。
ACL 暂用默认(创建者 + 管理员 + SYSTEM 可访问),限 SYSTEM 的加固留到阶段 5-4。

运行:  uv run python -m face_hello.service
"""
from __future__ import annotations

import json

import win32file
import win32pipe

from . import config
from .auth import authenticate_blocking
from .detector import FaceDetector
from .store import FaceStore

_BUF = 65536


def _warm_liveness() -> None:
    """预热 MediaPipe,首次 authenticate 不卡。"""
    try:
        import numpy as np

        from .liveness import FaceMeshTracker

        tr = FaceMeshTracker()
        tr.process(np.zeros((480, 640, 3), dtype=np.uint8))
        tr.close()
    except Exception:  # noqa: BLE001
        pass


def _handle(req: dict, detector: FaceDetector, store: FaceStore) -> dict:
    cmd = req.get("cmd")
    if cmd == "ping":
        return {"ok": True, "ready": True, "users": [p.name for p in store.list_profiles()]}
    if cmd == "authenticate":
        store.load()  # 取最新人脸库
        if store.is_empty():
            return {"ok": False, "reason": "尚未录入任何人脸"}
        result = authenticate_blocking(
            detector, store, on_instruction=lambda s: print(f"[活体提示] {s}", flush=True)
        )
        if result.success:
            return {"ok": True, "user": result.name, "similarity": round(result.similarity, 4)}
        return {"ok": False, "reason": result.reason}
    return {"ok": False, "reason": f"未知命令: {cmd}"}


def _serve_one(detector: FaceDetector, store: FaceStore) -> None:
    pipe = win32pipe.CreateNamedPipe(
        config.PIPE_NAME,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        1, _BUF, _BUF, 0, None,
    )
    try:
        win32pipe.ConnectNamedPipe(pipe, None)
        try:
            raw = win32file.ReadFile(pipe, _BUF)[1]
            resp = _handle(json.loads(raw.decode("utf-8")), detector, store)
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "reason": f"请求处理失败: {e}"}
        try:
            win32file.WriteFile(pipe, json.dumps(resp).encode("utf-8"))
            win32file.FlushFileBuffers(pipe)
        except Exception:  # noqa: BLE001 客户端可能已断开
            pass
        win32pipe.DisconnectNamedPipe(pipe)
    finally:
        win32file.CloseHandle(pipe)


def serve() -> None:
    print("[FaceHello 服务] 加载模型中…")
    detector = FaceDetector()
    detector.load()
    _warm_liveness()
    store = FaceStore().load()
    print(f"[FaceHello 服务] 就绪,监听 {config.PIPE_NAME}(Ctrl+C 退出)")
    try:
        while True:
            _serve_one(detector, store)
    except KeyboardInterrupt:
        print("\n[FaceHello 服务] 已停止")


if __name__ == "__main__":
    serve()
