"""里程碑 c-1:把当前账户的 Windows 登录密码存进 LSA Secret(键 L$FaceHello_<user>),
供 Credential Provider 在锁屏读取并提交解锁。

逻辑同 face_hello/cred_vault.py,做成「只依赖 pywin32 的单文件」方便拷进 VM。
需在**管理员**终端运行。

用法:
  python lsa_store.py set            # 给当前账户存密码(交互输入,不回显)
  python lsa_store.py set <user>     # 指定账户名
  python lsa_store.py clear [user]   # 删除
"""
from __future__ import annotations

import getpass
import sys

import win32api
import win32security

_PREFIX = "L$FaceHello_"


def _open():
    return win32security.LsaOpenPolicy(None, win32security.POLICY_CREATE_SECRET)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    user = argv[1] if len(argv) > 1 else win32api.GetUserName()
    print(f"[目标账户] {user}")

    if cmd == "set":
        pw = getpass.getpass("输入该账户的 Windows 登录密码: ")
        if not pw:
            print("空密码,放弃")
            return 1
        pol = _open()
        try:
            win32security.LsaStorePrivateData(pol, _PREFIX + user, pw)
        finally:
            win32security.LsaClose(pol)
        print("已写入 LSA Secret")
        return 0

    if cmd == "clear":
        pol = _open()
        try:
            win32security.LsaStorePrivateData(pol, _PREFIX + user, None)
        finally:
            win32security.LsaClose(pol)
        print("已删除")
        return 0

    print(f"未知命令: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
