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
import threading

import win32file
import win32pipe

from . import config
from .auth import AuthResult, authenticate_blocking
from .detector import FaceDetector
from .store import FaceStore

_BUF = 65536


class _AuthRunner:
    """后台跑一次认证,主循环用 auth_poll 取实时活体提示和最终结果。

    供 milestone d 的异步 CP:CP 选中磁贴 → auth_start(立即返回)→ 反复 auth_poll
    刷新锁屏提示文字,直到 done。摄像头由这个后台线程独占,主管道循环照常应答。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._instruction = ""
        self._done = False
        self._result: AuthResult | None = None

    @property
    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, detector: FaceDetector, store: FaceStore) -> None:
        with self._lock:
            if self._running:
                return  # 已有一次在跑,忽略重复 start
            self._instruction = "启动中…"
            self._done = False
            self._result = None
            self._thread = threading.Thread(
                target=self._run, args=(detector, store), daemon=True
            )
            self._thread.start()

    def _run(self, detector: FaceDetector, store: FaceStore) -> None:
        import time

        t0 = time.monotonic()

        def on_instr(s: str) -> None:
            with self._lock:
                self._instruction = s
            # 带相对时间戳,便于定位活体各阶段耗时(无脸等待 / 挑战 / 识别)
            print(f"[活体 +{time.monotonic() - t0:5.1f}s] {s}", flush=True)

        try:
            store.load()
            s = store.get_settings()  # 临时诊断:打印本次实际生效的活体阈值
            print(f"[活体设置] liveness={s['liveness_enabled']} "
                  f"challenge_timeout={s['challenge_timeout_s']} no_face={s['no_face_timeout_s']} "
                  f"yaw_thr={s['yaw_threshold_deg']} blinks={s['required_blinks']} "
                  f"ear={s['ear_threshold']}", flush=True)
            if store.is_empty():
                result = AuthResult(False, "尚未录入任何人脸")
            else:
                result = authenticate_blocking(detector, store, on_instruction=on_instr)
        except Exception as e:  # noqa: BLE001
            result = AuthResult(False, f"认证异常: {e}")
        print(f"[活体 +{time.monotonic() - t0:5.1f}s] 结束", flush=True)
        with self._lock:
            self._result = result
            self._done = True
        if result.success:
            print(f"[认证] 通过:user={result.name} similarity={result.similarity:.4f}", flush=True)
        else:
            print(f"[认证] 拒绝:{result.reason}", flush=True)

    def snapshot(self) -> dict:
        with self._lock:
            resp = {"ok": True, "done": self._done, "instruction": self._instruction}
            if self._done and self._result is not None:
                r = self._result
                resp["success"] = r.success
                if r.success:
                    resp["user"] = r.name
                    resp["similarity"] = round(r.similarity, 4)
                else:
                    resp["reason"] = r.reason
            return resp


_runner = _AuthRunner()


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
            print("[认证] 拒绝:尚未录入任何人脸", flush=True)
            return {"ok": False, "reason": "尚未录入任何人脸"}
        result = authenticate_blocking(
            detector, store, on_instruction=lambda s: print(f"[活体提示] {s}", flush=True)
        )
        if result.success:
            print(f"[认证] 通过:user={result.name} similarity={result.similarity:.4f}", flush=True)
            return {"ok": True, "user": result.name, "similarity": round(result.similarity, 4)}
        print(f"[认证] 拒绝:{result.reason}", flush=True)
        return {"ok": False, "reason": result.reason}
    if cmd == "auth_start":  # milestone d:异步认证,立即返回,随后用 auth_poll 取进度
        _runner.start(detector, store)
        return {"ok": True, "done": False}
    if cmd == "auth_poll":
        return _runner.snapshot()
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
            # ensure_ascii=False:中文 reason 直接发 UTF-8,CP 端按 UTF-8 解就不乱码
            win32file.WriteFile(pipe, json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            win32file.FlushFileBuffers(pipe)
        except Exception:  # noqa: BLE001 客户端可能已断开
            pass
        win32pipe.DisconnectNamedPipe(pipe)
    finally:
        win32file.CloseHandle(pipe)


def serve(should_continue=None) -> None:
    """常驻服务主循环。

    should_continue:返回 False 时退出循环(供 Windows 服务的 SvcStop 用);
    默认 None = 永远运行(控制台模式靠 Ctrl+C)。
    """
    if should_continue is None:
        should_continue = lambda: True  # noqa: E731
    print("[FaceHello 服务] 加载模型中…", flush=True)
    detector = FaceDetector()
    detector.load()
    _warm_liveness()
    store = FaceStore().load()
    print(f"[FaceHello 服务] 就绪,监听 {config.PIPE_NAME}", flush=True)
    try:
        while should_continue():
            _serve_one(detector, store)
    except KeyboardInterrupt:
        print("\n[FaceHello 服务] 已停止", flush=True)


if __name__ == "__main__":
    serve()
