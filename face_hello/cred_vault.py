"""登录凭据保险箱:把密码存进 LSA Secret(本地 secret,SYSTEM 可读)。

A 路线下"刷脸匹配 ≠ 密码",必须存一份可释放的密码,供 Credential Provider
在锁屏(SYSTEM 上下文)取出并提交给 LSA 完成解锁。

权限:
  - 写 / 删:需要**管理员**(POLICY_CREATE_SECRET)—— 管理台来做。
  - 读:需要 **SYSTEM**(锁屏的 Credential Provider);管理员通常也能读自己写的。

密码以 Unicode 字符串传入,pywin32 底层封成 LSA_UNICODE_STRING(即 UTF-16LE),
将来 C++ Credential Provider 可直接按 wchar_t 读取。
键名用 "L$" 前缀(本地 secret,不参与远程复制)。
"""
from __future__ import annotations

import win32api
import win32security

_KEY_PREFIX = "L$FaceHello_"


def current_user() -> str:
    """当前账户的 SAM 名 —— 与 CP 在锁屏用 GetUserName() 取到的本地后备名一致。

    人脸档案名、LSA 键、CP 提交 KERB 用的账户名三者必须是这同一个字符串。
    微软账户登录的机器也返回本地后备名(见 scripts/logon_probe.py 实测)。
    """
    return win32api.GetUserName()


def _key(username: str) -> str:
    return _KEY_PREFIX + username


def store_password(username: str, password: str) -> None:
    """写入密码(需管理员)。"""
    pol = win32security.LsaOpenPolicy(None, win32security.POLICY_CREATE_SECRET)
    try:
        win32security.LsaStorePrivateData(pol, _key(username), password)
    finally:
        win32security.LsaClose(pol)


def retrieve_password(username: str) -> str | None:
    """读取密码(需 SYSTEM)。不存在或无权限返回 None。"""
    try:
        pol = win32security.LsaOpenPolicy(None, win32security.POLICY_GET_PRIVATE_INFORMATION)
    except Exception:
        return None
    try:
        data = win32security.LsaRetrievePrivateData(pol, _key(username))
    except Exception:
        return None
    finally:
        win32security.LsaClose(pol)
    # pywin32 返回 Unicode 字符串(已从 LSA_UNICODE_STRING 解出)
    return data or None


def clear_password(username: str) -> None:
    """删除密码(写 None 即删除;需管理员)。"""
    pol = win32security.LsaOpenPolicy(None, win32security.POLICY_CREATE_SECRET)
    try:
        win32security.LsaStorePrivateData(pol, _key(username), None)
    finally:
        win32security.LsaClose(pol)
