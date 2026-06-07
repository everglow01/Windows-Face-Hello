#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include "CFaceCredential.h"

// FaceHello 的 Credential Provider:在登录/解锁场景下枚举出 1 个「刷脸」磁贴。
class CFaceProvider : public ICredentialProvider
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

    CFaceProvider();

    // 由凭据的扫描线程在识别通过后调用:置自动登录标志并通知 LogonUI 重新查询
    // (随后 LogonUI 会调 GetSerialization 完成提交)。ClearAutoLogon 在消费后复位。
    void SignalAutoLogon();
    void ClearAutoLogon();

private:
    ~CFaceProvider();
    void _CreateEnumeratedCredential(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus);
    void _ReleaseEnumeratedCredentials();

    LONG _cRef;
    CFaceCredential* _pCredential;
    ICredentialProviderEvents* _pcpe;
    UINT_PTR _upAdviseContext;
    bool _bAutoLogon;  // 识别通过后置 true,GetCredentialCount 据此让 LogonUI 自动提交
};

// 由 dll.cpp 的类工厂调用。
HRESULT CFaceProvider_CreateInstance(REFIID riid, void** ppv);
