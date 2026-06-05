#pragma once

#include <windows.h>
#include <string>

// 读 LSA Secret 里的登录密码(对应 Python 的 face_hello/cred_vault.py)。
// 键名 L$FaceHello_<user>。读取需 SYSTEM —— 锁屏的 CP 正是 SYSTEM。
namespace CredVault
{
    // 成功返回 true 且 outPassword 为明文密码;不存在/无权限返回 false。
    bool RetrievePassword(const std::wstring& user, std::wstring& outPassword);
}
