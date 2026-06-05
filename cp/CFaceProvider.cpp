#include <new>
#include <shlwapi.h>
#include "CFaceProvider.h"
#include "common.h"
#include "helpers.h"

// 字段定义,Provider 与 Credential 共用(声明在 common.h)。
// 注:pszLabel 类型为 LPWSTR,这里用字符串字面量初始化会触发常量性告警,
// 工程已关闭 /permissive- (ConformanceMode=false) 允许之。
const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR g_fieldDescriptors[FFI_NUM_FIELDS] =
{
    { FFI_TILEIMAGE, CPFT_TILE_IMAGE,    L"Image" },
    { FFI_LABEL,     CPFT_LARGE_TEXT,    L"Face Unlock" },
    { FFI_SUBMIT,    CPFT_SUBMIT_BUTTON, L"\x5237\x8138\x89e3\x9501" }, // “刷脸解锁”
    { FFI_STATUS,    CPFT_SMALL_TEXT,    L"Status" },
};

const FIELD_STATE_PAIR g_fieldStatePairs[FFI_NUM_FIELDS] =
{
    { CPFS_DISPLAY_IN_BOTH,          CPFIS_NONE }, // tile image
    { CPFS_DISPLAY_IN_BOTH,          CPFIS_NONE }, // label
    { CPFS_DISPLAY_IN_SELECTED_TILE, CPFIS_NONE }, // submit button
    { CPFS_DISPLAY_IN_SELECTED_TILE, CPFIS_NONE }, // status text
};

CFaceProvider::CFaceProvider()
    : _cRef(1), _pCredential(nullptr), _pcpe(nullptr),
      _upAdviseContext(0), _cpus(CPUS_INVALID)
{
    DllAddRef();
}

CFaceProvider::~CFaceProvider()
{
    _ReleaseEnumeratedCredentials();
    if (_pcpe)
    {
        _pcpe->Release();
        _pcpe = nullptr;
    }
    DllRelease();
}

// IUnknown
IFACEMETHODIMP_(ULONG) CFaceProvider::AddRef()
{
    return InterlockedIncrement(&_cRef);
}

IFACEMETHODIMP_(ULONG) CFaceProvider::Release()
{
    LONG cRef = InterlockedDecrement(&_cRef);
    if (cRef == 0)
    {
        delete this;
    }
    return cRef;
}

IFACEMETHODIMP CFaceProvider::QueryInterface(REFIID riid, void** ppv)
{
    static const QITAB qit[] =
    {
        QITABENT(CFaceProvider, ICredentialProvider),
        { nullptr },
    };
    return QISearch(this, qit, riid, ppv);
}

// 只在登录和解锁工作站两个场景出磁贴;其余场景不接管。
IFACEMETHODIMP CFaceProvider::SetUsageScenario(
    CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD /*dwFlags*/)
{
    switch (cpus)
    {
    case CPUS_LOGON:
    case CPUS_UNLOCK_WORKSTATION:
        _cpus = cpus;
        if (!_pCredential)
        {
            _CreateEnumeratedCredential();
        }
        return S_OK;
    default:
        return E_NOTIMPL;
    }
}

// 里程碑 a 不处理外部反序列化(将来也用不到——我们自己出磁贴)。
IFACEMETHODIMP CFaceProvider::SetSerialization(
    const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* /*pcpcs*/)
{
    return E_NOTIMPL;
}

IFACEMETHODIMP CFaceProvider::Advise(ICredentialProviderEvents* pcpe, UINT_PTR upAdviseContext)
{
    if (_pcpe)
    {
        _pcpe->Release();
    }
    _pcpe = pcpe;
    if (_pcpe)
    {
        _pcpe->AddRef();
    }
    _upAdviseContext = upAdviseContext;
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::UnAdvise()
{
    if (_pcpe)
    {
        _pcpe->Release();
        _pcpe = nullptr;
    }
    _upAdviseContext = 0;
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetFieldDescriptorCount(DWORD* pdwCount)
{
    *pdwCount = FFI_NUM_FIELDS;
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetFieldDescriptorAt(
    DWORD dwIndex, CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd)
{
    if (dwIndex < FFI_NUM_FIELDS && ppcpfd)
    {
        return FieldDescriptorCoAllocCopy(g_fieldDescriptors[dwIndex], ppcpfd);
    }
    return E_INVALIDARG;
}

IFACEMETHODIMP CFaceProvider::GetCredentialCount(
    DWORD* pdwCount, DWORD* pdwDefault, BOOL* pbAutoLogonWithDefault)
{
    *pdwCount = _pCredential ? 1 : 0;
    *pdwDefault = 0;
    *pbAutoLogonWithDefault = FALSE; // 里程碑 a 不自动登录,等用户点磁贴
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetCredentialAt(
    DWORD dwIndex, ICredentialProviderCredential** ppcpc)
{
    if (dwIndex == 0 && _pCredential && ppcpc)
    {
        return _pCredential->QueryInterface(IID_PPV_ARGS(ppcpc));
    }
    return E_INVALIDARG;
}

void CFaceProvider::_CreateEnumeratedCredential()
{
    _ReleaseEnumeratedCredentials();
    _pCredential = new (std::nothrow) CFaceCredential();
    if (_pCredential)
    {
        if (FAILED(_pCredential->Initialize(_cpus)))
        {
            _ReleaseEnumeratedCredentials();
        }
    }
}

void CFaceProvider::_ReleaseEnumeratedCredentials()
{
    if (_pCredential)
    {
        _pCredential->Release();
        _pCredential = nullptr;
    }
}

HRESULT CFaceProvider_CreateInstance(REFIID riid, void** ppv)
{
    HRESULT hr;
    CFaceProvider* pProvider = new (std::nothrow) CFaceProvider();
    if (pProvider)
    {
        hr = pProvider->QueryInterface(riid, ppv);
        pProvider->Release();
    }
    else
    {
        hr = E_OUTOFMEMORY;
    }
    return hr;
}
