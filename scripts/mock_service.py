"""里程碑 b 的最小 mock 认证服务:只为在 VM 里验证 CP 的命名管道客户端。

不加载任何模型/摄像头,ping 返回固定用户列表,authenticate 返回占位失败。
管道语义(消息模式)与真服务 face_hello/service.py 完全一致,故对 CP 透明。

仅依赖 pywin32:  pip install pywin32
运行:           python mock_service.py
"""
from __future__ import annotations

import json

import win32file
import win32pipe

PIPE_NAME = r"\\.\pipe\FaceHello"
_BUF = 65536
_USERS = ["owen", "test"]  # 固定假数据,证明 CP 客户端拿到的是服务端返回值


def _handle(req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "ping":
        return {"ok": True, "ready": True, "users": _USERS}
    if cmd == "authenticate":
        return {"ok": False, "reason": "mock 服务不做真识别(里程碑 b)"}
    return {"ok": False, "reason": f"unknown cmd: {cmd}"}


def _serve_one() -> None:
    pipe = win32pipe.CreateNamedPipe(
        PIPE_NAME,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        1, _BUF, _BUF, 0, None,
    )
    try:
        win32pipe.ConnectNamedPipe(pipe, None)
        try:
            raw = win32file.ReadFile(pipe, _BUF)[1]
            resp = _handle(json.loads(raw.decode("utf-8")))
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "reason": f"bad request: {e}"}
        try:
            win32file.WriteFile(pipe, json.dumps(resp).encode("utf-8"))
            win32file.FlushFileBuffers(pipe)
        except Exception:  # noqa: BLE001 客户端可能已断开
            pass
        win32pipe.DisconnectNamedPipe(pipe)
    finally:
        win32file.CloseHandle(pipe)


def main() -> None:
    print(f"[mock service] listening {PIPE_NAME} (Ctrl+C to stop)")
    try:
        while True:
            _serve_one()
    except KeyboardInterrupt:
        print("\n[mock service] stopped")


if __name__ == "__main__":
    main()
