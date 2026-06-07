#include "CredVault.h"
#include <ntsecapi.h>

bool CredVault::RetrievePassword(const std::wstring& user, std::wstring& outPassword)
{
    LSA_OBJECT_ATTRIBUTES oa;
    ZeroMemory(&oa, sizeof(oa));
    LSA_HANDLE hPolicy = nullptr;
    if (LsaOpenPolicy(nullptr, &oa, POLICY_GET_PRIVATE_INFORMATION, &hPolicy) != 0)
    {
        return false;
    }

    // 前缀须与 face_hello/cred_vault.py 的 _KEY_PREFIX 一致(跨语言契约)。
    const std::wstring keyStr = L"L$FaceHello_" + user;
    LSA_UNICODE_STRING key;
    key.Buffer = const_cast<PWSTR>(keyStr.c_str());
    key.Length = static_cast<USHORT>(keyStr.size() * sizeof(wchar_t));
    key.MaximumLength = static_cast<USHORT>((keyStr.size() + 1) * sizeof(wchar_t));

    PLSA_UNICODE_STRING pData = nullptr;
    NTSTATUS st = LsaRetrievePrivateData(hPolicy, &key, &pData);

    bool ok = false;
    if (st == 0 && pData && pData->Buffer && pData->Length)
    {
        outPassword.assign(pData->Buffer, pData->Length / sizeof(wchar_t));
        ok = true;
    }
    if (pData)
    {
        LsaFreeMemory(pData);
    }
    LsaClose(hPolicy);
    return ok;
}
