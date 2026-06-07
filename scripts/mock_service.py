"""里程碑 b 的最小 mock 认证服务:只为在 VM 里验证 CP 的命名管道客户端。

不加载任何模型/摄像头,ping 返回固定用户列表,authenticate 返回占位失败。
管道语义(消息模式)与真服务 face_hello/service.py 完全一致,故对 CP 透明。

仅依赖 pywin32:  pip install pywin32
运行:           python mock_service.py
"""
from __future__ import annotations

import json
import sys

import win32api
import win32file
import win32pipe

PIPE_NAME = r"\\.\pipe\FaceHello"
_BUF = 65536

# 服务返回的登录标识。可用命令行参数显式指定,验证不同账户类型:
#   本地账户:  python mock_service.py                 (默认 = 当前账户名)
#   本地显式:  python mock_service.py "DCR\owen"
#   微软账户:  python mock_service.py "MicrosoftAccount\1250933321@qq.com"
# CP 会按 \ 拆成 域\用户:本地 -> 计算机名作域;微软 -> 域=MicrosoftAccount,用户=邮箱。
_IDENTITY = sys.argv[1] if len(sys.argv) > 1 else win32api.GetUserName()


def _handle(req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "ping":
        return {"ok": True, "ready": True, "users": [_IDENTITY]}
    if cmd == "authenticate":
        # 不做真识别,直接"假装识别通过",返回配置的登录标识。
        # 真正解锁靠 CP 用这个标识去读 LSA 密码 + 提交 KERB。
        return {"ok": True, "user": _IDENTITY}
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
    print(f"[mock service] identity = {_IDENTITY!r}")
    print(f"[mock service] listening {PIPE_NAME} (Ctrl+C to stop)")
    try:
        while True:
            _serve_one()
    except KeyboardInterrupt:
        print("\n[mock service] stopped")


if __name__ == "__main__":
    main()
