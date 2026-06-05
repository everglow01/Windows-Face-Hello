#pragma once

#include <windows.h>
#include <ntsecapi.h>
#include <credentialprovider.h>

// 把 域/用户/密码 打包成 KERB_INTERACTIVE_UNLOCK_LOGON 提交给 LSA 完成登录/解锁。
// 取自微软 Credential Provider 样例的标准做法。

HRESULT KerbInteractiveUnlockLogonInit(
    PCWSTR domain, PCWSTR user, PCWSTR password,
    CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
    KERB_INTERACTIVE_UNLOCK_LOGON* pkiul);

// 序列化成单块内存(字符串紧跟结构体之后,Buffer 存相对偏移)。
// 返回的 *prgb 由 CoTaskMemAlloc 分配,调用方/LogonUI 负责释放。
HRESULT KerbInteractiveUnlockLogonPack(
    const KERB_INTERACTIVE_UNLOCK_LOGON& kiul, BYTE** prgb, DWORD* pcb);

// 取 Negotiate 认证包的编号,填入 CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION。
HRESULT RetrieveNegotiateAuthPackage(ULONG* pulAuthPackage);
