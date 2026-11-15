#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include <vector>
#include "CFaceCredential.h"

class AutoLogonBridge
{
public:
    AutoLogonBridge();
    ULONG AddRef();
    ULONG Release();
    void Advise(ICredentialProviderEvents* events, UINT_PTR context);
    void UnAdvise();
    void Signal();
    void Clear();
    bool IsRequested();
    void Deactivate();

private:
    ~AutoLogonBridge();

    LONG _cRef;
    mutable SRWLOCK _lock;
    ICredentialProviderEvents* _events;
    UINT_PTR _context;
    volatile LONG _active;
    volatile LONG _requested;
};

// FaceHello 的 Credential Provider:在登录/解锁场景下枚举出 1 个「刷脸」磁贴。
class CFaceProvider : public ICredentialProvider, public ICredentialProviderSetUserArray
{
public:
    // IUnknown
    IFACEMETHODIMP_(ULONG) AddRef();
    IFACEMETHODIMP_(ULONG) Release();
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv);

    // ICredentialProvider
    IFACEMETHODIMP SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD dwFlags);
    IFACEMETHODIMP SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs);
    IFACEMETHODIMP Advise(ICredentialProviderEvents* pcpe, UINT_PTR upAdviseContext);
    IFACEMETHODIMP UnAdvise();
    IFACEMETHODIMP GetFieldDescriptorCount(DWORD* pdwCount);
    IFACEMETHODIMP GetFieldDescriptorAt(DWORD dwIndex,
        CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd);
    IFACEMETHODIMP GetCredentialCount(DWORD* pdwCount, DWORD* pdwDefault,
        BOOL* pbAutoLogonWithDefault);
    IFACEMETHODIMP GetCredentialAt(DWORD dwIndex, ICredentialProviderCredential** ppcpc);

    // ICredentialProviderSetUserArray
    IFACEMETHODIMP SetUserArray(ICredentialProviderUserArray* users);

    CFaceProvider();

private:
    ~CFaceProvider();
    void _CreateEnumeratedCredentials();
    void _AddCredential(PCWSTR userSid, PCWSTR userName);
    void _ReleaseEnumeratedCredentials();

    LONG _cRef;
    CREDENTIAL_PROVIDER_USAGE_SCENARIO _cpus;
    ICredentialProviderUserArray* _users;      // LogonUI 给的用户列表(可能为空)
    std::vector<CFaceCredential*> _credentials; // 每个用户一个磁贴;无用户列表时退回 1 个独立磁贴
    bool _recreate;      // SetUsageScenario 之后,下次 GetCredentialCount 时(重)建磁贴
    bool _legacyTile;    // true = 当前是不绑定用户的独立磁贴(旧行为)
    AutoLogonBridge* _autoLogon;
};

// 由 dll.cpp 的类工厂调用。
HRESULT CFaceProvider_CreateInstance(REFIID riid, void** ppv);
