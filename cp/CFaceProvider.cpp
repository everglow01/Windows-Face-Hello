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

AutoLogonBridge::AutoLogonBridge()
    : _cRef(1), _events(nullptr), _context(0), _active(1), _requested(0)
{
    InitializeSRWLock(&_lock);
}

AutoLogonBridge::~AutoLogonBridge()
{
    UnAdvise();
}

ULONG AutoLogonBridge::AddRef()
{
    return InterlockedIncrement(&_cRef);
}

ULONG AutoLogonBridge::Release()
{
    LONG value = InterlockedDecrement(&_cRef);
    if (value == 0)
    {
        delete this;
    }
    return value;
}

void AutoLogonBridge::Advise(ICredentialProviderEvents* events, UINT_PTR context)
{
    if (events)
    {
        events->AddRef();
    }
    AcquireSRWLockExclusive(&_lock);
    ICredentialProviderEvents* old = _events;
    _events = events;
    _context = context;
    ReleaseSRWLockExclusive(&_lock);
    if (old)
    {
        old->Release();
    }
}

void AutoLogonBridge::UnAdvise()
{
    AcquireSRWLockExclusive(&_lock);
    ICredentialProviderEvents* old = _events;
    _events = nullptr;
    _context = 0;
    ReleaseSRWLockExclusive(&_lock);
    if (old)
    {
        old->Release();
    }
}

void AutoLogonBridge::Signal()
{
    ICredentialProviderEvents* events = nullptr;
    UINT_PTR context = 0;
    AcquireSRWLockShared(&_lock);
    if (InterlockedCompareExchange(&_active, 0, 0) != 0)
    {
        InterlockedExchange(&_requested, 1);
        if (_events)
        {
            events = _events;
            events->AddRef();
            context = _context;
        }
    }
    ReleaseSRWLockShared(&_lock);
    if (events)
    {
        events->CredentialsChanged(context);
        events->Release();
    }
}

void AutoLogonBridge::Clear()
{
    InterlockedExchange(&_requested, 0);
}

bool AutoLogonBridge::IsRequested()
{
    return InterlockedCompareExchange(&_requested, 0, 0) != 0;
}

void AutoLogonBridge::Deactivate()
{
    InterlockedExchange(&_active, 0);
    Clear();
    UnAdvise();
}

CFaceProvider::CFaceProvider()
    : _cRef(1), _pCredential(nullptr), _autoLogon(new (std::nothrow) AutoLogonBridge())
{
    DllAddRef();
}

CFaceProvider::~CFaceProvider()
{
    if (_autoLogon)
    {
        _autoLogon->Deactivate();
    }
    _ReleaseEnumeratedCredentials();
    if (_autoLogon)
    {
        _autoLogon->Release();
        _autoLogon = nullptr;
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
        if (!_pCredential)
        {
            _CreateEnumeratedCredential(cpus);
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
    if (_autoLogon)
    {
        _autoLogon->Advise(pcpe, upAdviseContext);
    }
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::UnAdvise()
{
    if (_autoLogon)
    {
        _autoLogon->UnAdvise();
    }
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
    // 识别通过后 SignalAutoLogon 置位,LogonUI 据此自动调 GetSerialization 完成提交
    *pbAutoLogonWithDefault = _autoLogon && _autoLogon->IsRequested() ? TRUE : FALSE;
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

void CFaceProvider::_CreateEnumeratedCredential(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus)
{
    _ReleaseEnumeratedCredentials();
    _pCredential = new (std::nothrow) CFaceCredential();
    if (_pCredential)
    {
        if (!_autoLogon || FAILED(_pCredential->Initialize(cpus, _autoLogon)))
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
