"""定位 KERB 解锁该用哪个 (域, 用户名)。

用你锁屏解锁时实际输入的密码,逐一测试候选 (域,用户) 组合 —— 能拿到登录令牌的
那个,就是 Credential Provider 提交 KERB 时该用的身份。只验证凭据,立即关闭令牌,
不改任何系统状态。

运行:  python logon_probe.py
"""
from __future__ import annotations

import getpass

import win32api
import win32con
import win32security


def try_logon(user: str, domain: str, pw: str) -> str:
    try:
        h = win32security.LogonUser(
            user, domain, pw,
            win32con.LOGON32_LOGON_INTERACTIVE,
            win32con.LOGON32_PROVIDER_DEFAULT,
        )
        h.Close()
        return "OK"
    except Exception as e:  # noqa: BLE001
        return str(e)


def main() -> None:
    sam = win32api.GetUserName()
    comp = win32api.GetComputerName()
    try:
        samc = win32api.GetUserNameEx(win32api.NameSamCompatible)
    except Exception:  # noqa: BLE001
        samc = ""

    print(f"GetUserName       = {sam!r}")
    print(f"ComputerName      = {comp!r}")
    print(f"NameSamCompatible = {samc!r}")

    pw = getpass.getpass("输入你锁屏解锁时实际输入的密码: ")
    email = input("如果是微软账户,输入登录邮箱(本地账户直接回车跳过): ").strip()

    candidates: list[tuple[str, str]] = [
        (sam, "."),            # 本地账户,域用 .
        (sam, comp),           # 本地账户,域用计算机名
    ]
    if "\\" in samc:
        d, u = samc.split("\\", 1)
        candidates.append((u, d))   # NameSamCompatible 拆出来的组合
    if email:
        candidates.append((email, "MicrosoftAccount"))
        candidates.append((email, ""))

    print("\n--- 测试结果(标 OK 的就是正确组合)---")
    for u, d in candidates:
        r = try_logon(u, d, pw)
        flag = "✅ OK" if r == "OK" else "❌ " + r
        print(f"domain={d!r:18} user={u!r:32} -> {flag}")


if __name__ == "__main__":
    main()
