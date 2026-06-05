#include "KerbHelpers.h"

namespace
{
void InitUnicodeString(PCWSTR pwz, UNICODE_STRING* pus)
{
    const size_t len = pwz ? wcslen(pwz) : 0;
    pus->Length = static_cast<USHORT>(len * sizeof(WCHAR));
    pus->MaximumLength = static_cast<USHORT>((len + (pwz ? 1 : 0)) * sizeof(WCHAR));
    pus->Buffer = const_cast<PWSTR>(pwz);
}

// 把源字符串拷到 blob 末尾,目标 UNICODE_STRING.Buffer 改存相对结构体首地址的偏移。
void PackString(const UNICODE_STRING& src, BYTE* base, BYTE** ppCur, UNICODE_STRING* dst)
{
    dst->Length = src.Length;
    dst->MaximumLength = src.Length;
    if (src.Length)
    {
        CopyMemory(*ppCur, src.Buffer, src.Length);
        dst->Buffer = reinterpret_cast<PWSTR>(*ppCur - base);
        *ppCur += src.Length;
    }
    else
    {
        dst->Buffer = nullptr;
    }
}
} // namespace

HRESULT KerbInteractiveUnlockLogonInit(
    PCWSTR domain, PCWSTR user, PCWSTR password,
    CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
    KERB_INTERACTIVE_UNLOCK_LOGON* pkiul)
{
    KERB_INTERACTIVE_UNLOCK_LOGON kiul;
    ZeroMemory(&kiul, sizeof(kiul));
    KERB_INTERACTIVE_LOGON* pkil = &kiul.Logon;

    switch (cpus)
    {
    case CPUS_UNLOCK_WORKSTATION:
        pkil->MessageType = KerbWorkstationUnlockLogon;
        break;
    case CPUS_LOGON:
        pkil->MessageType = KerbInteractiveLogon;
        break;
    default:
        return E_FAIL;
    }

    InitUnicodeString(domain, &pkil->LogonDomainName);
    InitUnicodeString(user, &pkil->UserName);
    InitUnicodeString(password, &pkil->Password);

    *pkiul = kiul;
    return S_OK;
}

HRESULT KerbInteractiveUnlockLogonPack(
    const KERB_INTERACTIVE_UNLOCK_LOGON& kiul, BYTE** prgb, DWORD* pcb)
{
    const KERB_INTERACTIVE_LOGON* pkil = &kiul.Logon;
    const DWORD cb = sizeof(kiul) + pkil->LogonDomainName.Length +
                     pkil->UserName.Length + pkil->Password.Length;

    KERB_INTERACTIVE_UNLOCK_LOGON* p =
        static_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(CoTaskMemAlloc(cb));
    if (!p)
    {
        return E_OUTOFMEMORY;
    }

    ZeroMemory(&p->LogonId, sizeof(p->LogonId));
    KERB_INTERACTIVE_LOGON* pout = &p->Logon;
    pout->MessageType = pkil->MessageType;

    BYTE* base = reinterpret_cast<BYTE*>(p);
    BYTE* cur = base + sizeof(*p);
    PackString(pkil->LogonDomainName, base, &cur, &pout->LogonDomainName);
    PackString(pkil->UserName, base, &cur, &pout->UserName);
    PackString(pkil->Password, base, &cur, &pout->Password);

    *prgb = base;
    *pcb = cb;
    return S_OK;
}

HRESULT RetrieveNegotiateAuthPackage(ULONG* pulAuthPackage)
{
    HANDLE hLsa = nullptr;
    NTSTATUS st = LsaConnectUntrusted(&hLsa);
    if (st != 0)
    {
        return HRESULT_FROM_WIN32(LsaNtStatusToWinError(st));
    }

    ULONG ulPackage = 0;
    char szNegotiate[] = "Negotiate";
    LSA_STRING name;
    name.Buffer = szNegotiate;
    name.Length = static_cast<USHORT>(strlen(szNegotiate));
    name.MaximumLength = static_cast<USHORT>(strlen(szNegotiate) + 1);

    st = LsaLookupAuthenticationPackage(hLsa, &name, &ulPackage);
    HRESULT hr;
    if (st == 0)
    {
        *pulAuthPackage = ulPackage;
        hr = S_OK;
    }
    else
    {
        hr = HRESULT_FROM_WIN32(LsaNtStatusToWinError(st));
    }
    LsaDeregisterLogonProcess(hLsa);
    return hr;
}
