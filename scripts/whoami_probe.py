"""只读探测当前登录身份的各种表示形式,用于确定 KERB 解锁该用哪个标识。

本地账户与微软账户返回的形式不同——在两种账户下各跑一次,把输出发回即可定方案。
纯读取,无任何系统改动。

运行:  uv run python -m scripts.whoami_probe
"""
from __future__ import annotations

import win32api

_FORMATS = [
    "NameSamCompatible",   # 本地: COMPUTER\user ; 微软账户常为本地后备名
    "NameDisplay",         # 显示名(全名)
    "NameUserPrincipal",   # UPN / 邮箱(微软账户多走这个)
    "NameUnique",
]


def main() -> None:
    print("GetUserName():", win32api.GetUserName())
    for name in _FORMATS:
        fmt = getattr(win32api, name, None)
        if fmt is None:
            print(f"{name}: (本机 win32api 无此常量)")
            continue
        try:
            print(f"{name}:", win32api.GetUserNameEx(fmt))
        except Exception as e:  # noqa: BLE001
            print(f"{name}: (失败) {e}")


if __name__ == "__main__":
    main()
