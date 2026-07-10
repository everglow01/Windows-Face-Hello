"""认证服务测试客户端(模拟 Credential Provider 调用)。

用法:
  uv run python -m scripts.auth_client ping
  uv run python -m scripts.auth_client authenticate
"""
from __future__ import annotations

import sys

from face_hello import probes


def call(req: dict) -> dict:
    return probes.call_pipe(req)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "ping"
    try:
        resp = call({"cmd": cmd})
    except Exception as e:  # noqa: BLE001
        print(f"调用失败(服务没起?): {e}")
        return 1
    import json

    print(json.dumps(resp, ensure_ascii=False))
    return 0 if resp.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
