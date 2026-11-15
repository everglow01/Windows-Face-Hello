#include <new>
#include <string>
#include <shlwapi.h>
#include <sddl.h>
#include "CFaceProvider.h"
#include <wtsapi32.h>
#include "common.h"
#include "helpers.h"

namespace
{
constexpr DWORD kAuthScopeLogon = 0x1;
constexpr DWORD kAuthScopeUnlock = 0x2;
constexpr DWORD kAuthScopeDefault = kAuthScopeLogon | kAuthScopeUnlock;

DWORD ReadAuthScope()
{
    HANDLE file = CreateFileW(
        L"C:\\ProgramData\\FaceHello\\auth_scope.txt", GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
    {
        return kAuthScopeDefault;
    }

    LARGE_INTEGER size = {};
    if (!GetFileSizeEx(file, &size) || size.QuadPart != 1)
    {
        CloseHandle(file);
        return kAuthScopeDefault;
    }

    char value = '\0';
    DWORD read = 0;
    const BOOL ok = ReadFile(file, &value, 1, &read, nullptr);
    CloseHandle(file);
    if (!ok || read != 1 || value < '0' || value > '3')
    {
        return kAuthScopeDefault;
    }
    return static_cast<DWORD>(value - '0');
}

enum class SessionUserState
{
    Unknown,
    Absent,
    Present,
};

SessionUserState CurrentSessionUserState()
{
    LPWSTR user = nullptr;
    DWORD bytes = 0;
    const BOOL ok = WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION,
        WTSUserName, &user, &bytes);
    if (!ok)
    {
        return SessionUserState::Unknown;
    }
    const bool hasUser = user != nullptr && bytes > sizeof(wchar_t) && user[0] != L'\0';
    if (user)
    {
        WTSFreeMemory(user);
    }
    return hasUser ? SessionUserState::Present : SessionUserState::Absent;
}

// 当前 LogonUI 是否跑在远程(RDP 等)会话里。
// 摄像头接在物理机上,拍到的是坐在机器前的人,而不是远程发起登录的人:远程会话若也出
// 刷脸磁贴,远程一方就能借本机摄像头前的人完成认证。Windows Hello 生物识别同样不在远程
// 会话里提供。协议类型:0 = 控制台,1 = 旧版 ICA,2 = RDP;再用 SM_REMOTESESSION 兜底。
bool IsRemoteSession()
{
    LPWSTR buffer = nullptr;
    DWORD bytes = 0;
    if (WTSQuerySessionInformationW(
            WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION,
            WTSClientProtocolType, &buffer, &bytes))
    {
        const bool remote = buffer != nullptr && bytes >= sizeof(USHORT)
            && *reinterpret_cast<const USHORT*>(buffer) != 0;
        if (buffer)
        {
            WTSFreeMemory(buffer);
        }
        if (remote)
        {
            return true;
        }
    }
    return GetSystemMetrics(SM_REMOTESESSION) != 0;
}

bool IsUsageScenarioEnabled(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus)
{
    const DWORD scope = ReadAuthScope();
    if (cpus == CPUS_LOGON)
    {
        // Windows 10+ 通常把登录与解锁都作为 CPUS_LOGON。已有会话用户表示
        // Win+L 恢复;没有会话用户才是开机 / 注销后的登录。
        const SessionUserState state = CurrentSessionUserState();
        if (state == SessionUserState::Unknown)
        {
            // 无法区分时只接受两个场景都启用,避免违反用户明确关闭的范围。
            return (scope & kAuthScopeDefault) == kAuthScopeDefault;
        }
        const DWORD required = state == SessionUserState::Present
            ? kAuthScopeUnlock : kAuthScopeLogon;
        return (scope & required) != 0;
    }
    if (cpus == CPUS_UNLOCK_WORKSTATION)
    {
        // 旧系统或特定组策略仍可能显式发送解锁场景。
        return (scope & kAuthScopeUnlock) != 0;
    }
    return false;
}
}

// 字段定义,Provider 与 Credential 共用(声明在 common.h)。
static wchar_t g_imageLabel[] = L"Image";
static wchar_t g_faceLabel[] = L"Face Unlock";
static wchar_t g_submitLabel[] = L"\x5237\x8138\x89e3\x9501";
static wchar_t g_statusLabel[] = L"Status";
static wchar_t g_providerLabel[] = L"Provider";

// 磁贴挂在用户账户下(ICredentialProviderCredential2)时,LogonUI 用这两个字段类型在
// 「登录选项」里画本 Provider 的图标与名称。取值即 credentialprovider.h 的
// CPFG_CREDENTIAL_PROVIDER_LOGO / CPFG_CREDENTIAL_PROVIDER_LABEL;写成字面量让本表保持常量初始化。
#define FACE_CPFG_PROVIDER_LOGO \
    { 0x2d837775, 0xf6cd, 0x464e, { 0xa7, 0x45, 0x48, 0x2f, 0xd0, 0xb4, 0x74, 0x93 } }
#define FACE_CPFG_PROVIDER_LABEL \
    { 0x286bbff3, 0xbad4, 0x438f, { 0xb0, 0x07, 0x79, 0xb7, 0x26, 0x7c, 0x3d, 0x48 } }

const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR g_fieldDescriptors[FFI_NUM_FIELDS] =
{
    { FFI_TILEIMAGE, CPFT_TILE_IMAGE,    g_imageLabel, FACE_CPFG_PROVIDER_LOGO },
    { FFI_LABEL,     CPFT_LARGE_TEXT,    g_faceLabel },
    { FFI_SUBMIT,    CPFT_SUBMIT_BUTTON, g_submitLabel },
    { FFI_STATUS,    CPFT_SMALL_TEXT,    g_statusLabel },
    { FFI_PROVIDER_LABEL, CPFT_SMALL_TEXT, g_providerLabel, FACE_CPFG_PROVIDER_LABEL },
};

const FIELD_STATE_PAIR g_fieldStatePairs[FFI_NUM_FIELDS] =
{
    { CPFS_DISPLAY_IN_BOTH,          CPFIS_NONE }, // tile image
    { CPFS_DISPLAY_IN_BOTH,          CPFIS_NONE }, // label
    { CPFS_DISPLAY_IN_SELECTED_TILE, CPFIS_NONE }, // submit button
    { CPFS_DISPLAY_IN_SELECTED_TILE, CPFIS_NONE }, // status text
    { CPFS_HIDDEN,                   CPFIS_NONE }, // provider label(仅供「登录选项」图标的名称)
};

namespace
{
// 把 LogonUI 给的用户 SID 字符串解析成本地账户名(SAM 名)。人脸档案名、LSA 键与 KERB
// 账户名约定都是这个名字(微软账户也有本地后备名),所以绑定用户的磁贴用它核对识别结果。
bool SamNameFromSidString(PCWSTR sidString, std::wstring& outName)
{
    PSID sid = nullptr;
    if (!sidString || !ConvertStringSidToSidW(sidString, &sid))
    {
        return false;
    }
    wchar_t name[257] = {};
    wchar_t domain[257] = {};
    DWORD cchName = ARRAYSIZE(name);
    DWORD cchDomain = ARRAYSIZE(domain);
    SID_NAME_USE use = SidTypeUnknown;
    const BOOL ok = LookupAccountSidW(nullptr, sid, name, &cchName, domain, &cchDomain, &use);
    LocalFree(sid);
    if (!ok || name[0] == L'\0')
    {
        return false;
    }
    outName.assign(name);
    return true;
}
}

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
    : _cRef(1), _cpus(CPUS_INVALID), _users(nullptr), _recreate(false), _legacyTile(false),
      _autoLogon(new (std::nothrow) AutoLogonBridge())
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
    if (_users)
    {
        _users->Release();
        _users = nullptr;
    }
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
        QITABENT(CFaceProvider, ICredentialProviderSetUserArray),
        { nullptr },
    };
    return QISearch(this, qit, riid, ppv);
}

// 只在登录和解锁工作站两个场景出磁贴;其余场景不接管。远程会话一律不出磁贴。
// 磁贴推迟到 GetCredentialCount 再建:LogonUI 会在两者之间调 SetUserArray 给出用户列表。
IFACEMETHODIMP CFaceProvider::SetUsageScenario(
    CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD /*dwFlags*/)
{
    switch (cpus)
    {
    case CPUS_LOGON:
    case CPUS_UNLOCK_WORKSTATION:
        if (IsRemoteSession() || !IsUsageScenarioEnabled(cpus))
        {
            _ReleaseEnumeratedCredentials();
            _recreate = false;
            return E_NOTIMPL;
        }
        _cpus = cpus;
        _recreate = true;
        return S_OK;
    default:
        return E_NOTIMPL;
    }
}

// ICredentialProviderSetUserArray:LogonUI 给出登录界面上的用户列表,据此给每个用户建一个
// 挂在其账户下的刷脸磁贴(图标出现在该用户的「登录选项」里,头像用用户自己的)。
IFACEMETHODIMP CFaceProvider::SetUserArray(ICredentialProviderUserArray* users)
{
    if (users)
    {
        users->AddRef();
    }
    if (_users)
    {
        _users->Release();
    }
    _users = users;
    // 若已按「无用户列表」建了独立磁贴,拿到列表后重建一次;已是绑定用户的磁贴则不动,
    // 避免识别通过后 LogonUI 重新枚举时丢掉待提交的状态。
    if (_legacyTile)
    {
        _recreate = true;
    }
    return S_OK;
}

// 本 Provider 只枚举自己的磁贴,不处理外部反序列化。
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
    if (_recreate)
    {
        _recreate = false;
        _CreateEnumeratedCredentials();
    }
    *pdwCount = static_cast<DWORD>(_credentials.size());
    // 独立磁贴(旧行为)默认选中自己;挂在用户下的磁贴不抢默认,由 LogonUI 按上次使用的登录方式定。
    *pdwDefault = (_legacyTile && !_credentials.empty()) ? 0 : CREDENTIAL_PROVIDER_NO_DEFAULT;
    *pbAutoLogonWithDefault = FALSE;
    // 识别通过后 SignalAutoLogon 置位,LogonUI 据此对「识别通过的那一个」磁贴自动调
    // GetSerialization 完成提交。
    if (_autoLogon && _autoLogon->IsRequested())
    {
        for (size_t i = 0; i < _credentials.size(); ++i)
        {
            if (_credentials[i]->IsReadyToSubmit())
            {
                *pdwDefault = static_cast<DWORD>(i);
                *pbAutoLogonWithDefault = TRUE;
                break;
            }
        }
    }
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetCredentialAt(
    DWORD dwIndex, ICredentialProviderCredential** ppcpc)
{
    if (dwIndex < _credentials.size() && ppcpc)
    {
        return _credentials[dwIndex]->QueryInterface(IID_PPV_ARGS(ppcpc));
    }
    return E_INVALIDARG;
}

void CFaceProvider::_AddCredential(PCWSTR userSid, PCWSTR userName)
{
    CFaceCredential* credential = new (std::nothrow) CFaceCredential();
    if (!credential)
    {
        return;
    }
    if (!_autoLogon || FAILED(credential->Initialize(_cpus, _autoLogon, userSid, userName)))
    {
        credential->Release();
        return;
    }
    try
    {
        _credentials.push_back(credential);
    }
    catch (...)
    {
        credential->Release();
    }
}

void CFaceProvider::_CreateEnumeratedCredentials()
{
    _ReleaseEnumeratedCredentials();
    _legacyTile = false;

    DWORD userCount = 0;
    if (_users && SUCCEEDED(_users->GetCount(&userCount)) && userCount > 0)
    {
        for (DWORD i = 0; i < userCount; ++i)
        {
            ICredentialProviderUser* user = nullptr;
            if (FAILED(_users->GetAt(i, &user)) || !user)
            {
                continue;
            }
            PWSTR sid = nullptr;
            if (SUCCEEDED(user->GetSid(&sid)) && sid)
            {
                std::wstring samName;
                if (SamNameFromSidString(sid, samName))
                {
                    _AddCredential(sid, samName.c_str());
                }
            }
            CoTaskMemFree(sid);
            user->Release();
        }
        return;
    }

    // 系统没给用户列表(SetUserArray 未被调用):退回原来的独立「刷脸」磁贴。
    _legacyTile = true;
    _AddCredential(nullptr, nullptr);
}

void CFaceProvider::_ReleaseEnumeratedCredentials()
{
    for (CFaceCredential* credential : _credentials)
    {
        credential->Release();
    }
    _credentials.clear();
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
