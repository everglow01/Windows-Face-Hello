#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include "CFaceCredential.h"

// LogonUI 未公开的显示状态回调。未收到有效的封面切换时，仍可手动按箭头。
MIDL_INTERFACE("A09BCC29-D779-4513-BB59-B4DB5D82D2B6")
ICredentialProviderWithDisplayState : public IUnknown
{
    virtual HRESULT STDMETHODCALLTYPE SetDisplayState(DWORD flags) = 0;
};

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
    bool IsNotifying();
    void Deactivate();

private:
    ~AutoLogonBridge();

    LONG _cRef;
    mutable SRWLOCK _lock;
    ICredentialProviderEvents* _events;
    UINT_PTR _context;
    volatile LONG _active;
    volatile LONG _requested;
    volatile LONG _notifying = 0;
};

// FaceHello 的 Credential Provider:在登录/解锁场景下枚举出 1 个「刷脸」磁贴。
class CFaceProvider : public ICredentialProvider, public ICredentialProviderWithDisplayState
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
    IFACEMETHODIMP SetDisplayState(DWORD flags);

    CFaceProvider();

private:
    ~CFaceProvider();
    void _CreateEnumeratedCredential(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus);
    void _ReleaseEnumeratedCredentials();

    LONG _cRef;
    CFaceCredential* _pCredential;
    AutoLogonBridge* _autoLogon;
    bool _sawLockCover = false;
    bool _signInVisible = false;
};

// 由 dll.cpp 的类工厂调用。
HRESULT CFaceProvider_CreateInstance(REFIID riid, void** ppv);
