"""认证服务测试客户端(模拟 Credential Provider 调用)。

用法:
  uv run python -m scripts.auth_client ping
  uv run python -m scripts.auth_client authenticate
"""
from __future__ import annotations

import json
import sys

import win32file

from face_hello import config


def call(req: dict) -> dict:
    handle = win32file.CreateFile(
        config.PIPE_NAME,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0, None, win32file.OPEN_EXISTING, 0, None,
    )
    try:
        # 客户端也切到消息读模式,与服务端消息管道匹配
        win32pipe_set_message_mode(handle)
        win32file.WriteFile(handle, json.dumps(req).encode("utf-8"))
        raw = win32file.ReadFile(handle, 65536)[1]
        return json.loads(raw.decode("utf-8"))
    finally:
        win32file.CloseHandle(handle)


def win32pipe_set_message_mode(handle) -> None:
    import win32pipe

    win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "ping"
    try:
        resp = call({"cmd": cmd})
    except Exception as e:  # noqa: BLE001
        print(f"调用失败(服务没起?): {e}")
        return 1
    print(json.dumps(resp, ensure_ascii=False))
    return 0 if resp.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
