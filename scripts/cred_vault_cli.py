"""凭据保险箱测试 CLI(验证 LSA Secret 读写)。

用法(在终端里跑):
  set   写入密码(需**管理员**终端):
        uv run python -m scripts.cred_vault_cli set [用户名]
  get   读取确认(管理员/ SYSTEM):
        uv run python -m scripts.cred_vault_cli get [用户名] [--show]
  clear 删除(需管理员):
        uv run python -m scripts.cred_vault_cli clear [用户名]

SYSTEM 读取测试(模拟 Credential Provider 上下文),需 PsExec:
  psexec -s -accepteula <venv>\Scripts\python.exe -m scripts.cred_vault_cli get 用户名 --show
"""
from __future__ import annotations

import getpass
import sys

import win32api

from face_hello import cred_vault


def _whoami() -> str:
    try:
        return win32api.GetUserNameEx(win32api.NameSamCompatible)  # 域\用户
    except Exception:
        return win32api.GetUserName()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    user = argv[1] if len(argv) > 1 and not argv[1].startswith("-") else win32api.GetUserName()
    show = "--show" in argv

    print(f"[当前进程身份] {_whoami()}")
    print(f"[目标用户名]   {user}")

    if cmd == "set":
        pw = getpass.getpass("输入要存储的登录密码: ")
        if not pw:
            print("空密码,放弃")
            return 1
        cred_vault.store_password(user, pw)
        print("已写入 LSA Secret")
        return 0

    if cmd == "get":
        pw = cred_vault.retrieve_password(user)
        if pw is None:
            print("未读到(不存在或无权限——读取需 SYSTEM)")
            return 1
        print(f"读到密码,长度 {len(pw)}" + (f":{pw}" if show else "(加 --show 显示明文)"))
        return 0

    if cmd == "clear":
        cred_vault.clear_password(user)
        print("已删除")
        return 0

    print(f"未知命令: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
