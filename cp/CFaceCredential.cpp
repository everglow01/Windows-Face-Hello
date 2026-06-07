#include <new>
#include <string>
#include <shlwapi.h>
#include <ntsecapi.h>
#include "CFaceCredential.h"
#include "CFaceProvider.h"
#include "common.h"
#include "PipeClient.h"
#include "CredVault.h"
#include "KerbHelpers.h"
#include "guid.h"

// 生成一张纯色磁贴位图(避免引入二进制资源,里程碑 a 够用)。
static HBITMAP _CreateSolidBitmap(int w, int h, COLORREF color)
{
    BITMAPINFO bmi = {};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = w;
    bmi.bmiHeader.biHeight = -h; // 负高 = 自上而下
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    void* pBits = nullptr;
    HBITMAP hbmp = CreateDIBSection(nullptr, &bmi, DIB_RGB_COLORS, &pBits, nullptr, 0);
    if (hbmp && pBits)
    {
        const DWORD bgr = (GetRValue(color) << 16) | (GetGValue(color) << 8) | GetBValue(color);
        DWORD* px = static_cast<DWORD*>(pBits);
        for (int i = 0; i < w * h; ++i)
        {
            px[i] = 0xFF000000 | bgr; // 不透明
        }
    }
    return hbmp;
}

CFaceCredential::CFaceCredential()
    : _cRef(1), _cpus(CPUS_INVALID), _pProvider(nullptr),
      _pCredProvCredentialEvents(nullptr), _hAuthThread(nullptr),
      _stopFlag(0), _authState(AuthState::Idle)
{
    ZeroMemory(_rgFieldStrings, sizeof(_rgFieldStrings));
    InitializeCriticalSection(&_cs);
}

CFaceCredential::~CFaceCredential()
{
    _StopAuthThread();
    DeleteCriticalSection(&_cs);
    for (PWSTR& s : _rgFieldStrings)
    {
        CoTaskMemFree(s);
        s = nullptr;
    }
    if (_pCredProvCredentialEvents)
    {
        _pCredProvCredentialEvents->Release();
        _pCredProvCredentialEvents = nullptr;
    }
}

HRESULT CFaceCredential::Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, CFaceProvider* pProvider)
{
    _cpus = cpus;
    _pProvider = pProvider;
    HRESULT hr = SHStrDupW(L"Face Unlock", &_rgFieldStrings[FFI_LABEL]);
    if (SUCCEEDED(hr))
    {
        hr = SHStrDupW(L"", &_rgFieldStrings[FFI_STATUS]);
    }
    return hr;
}

// IUnknown
IFACEMETHODIMP_(ULONG) CFaceCredential::AddRef()
{
    return InterlockedIncrement(&_cRef);
}

IFACEMETHODIMP_(ULONG) CFaceCredential::Release()
{
    LONG cRef = InterlockedDecrement(&_cRef);
    if (cRef == 0)
    {
        delete this;
    }
    return cRef;
}

IFACEMETHODIMP CFaceCredential::QueryInterface(REFIID riid, void** ppv)
{
    static const QITAB qit[] =
    {
        QITABENT(CFaceCredential, ICredentialProviderCredential),
        { nullptr },
    };
    return QISearch(this, qit, riid, ppv);
}

IFACEMETHODIMP CFaceCredential::Advise(ICredentialProviderCredentialEvents* pcpce)
{
    if (_pCredProvCredentialEvents)
    {
        _pCredProvCredentialEvents->Release();
    }
    _pCredProvCredentialEvents = pcpce;
    if (_pCredProvCredentialEvents)
    {
        _pCredProvCredentialEvents->AddRef();
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::UnAdvise()
{
    if (_pCredProvCredentialEvents)
    {
        _pCredProvCredentialEvents->Release();
        _pCredProvCredentialEvents = nullptr;
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetSelected(BOOL* pbAutoLogon)
{
    // milestone d:选中磁贴即后台开始刷脸(不在此处自动提交,成功后再由线程触发)。
    *pbAutoLogon = FALSE;
    _StartAuthThread();
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetDeselected()
{
    _StopAuthThread();
    return S_OK;
}

// 选中磁贴时拉起后台扫描线程。仅在空闲/失败态允许重新开始。
void CFaceCredential::_StartAuthThread()
{
    bool canStart = false;
    EnterCriticalSection(&_cs);
    if (_hAuthThread == nullptr &&
        (_authState == AuthState::Idle || _authState == AuthState::Failed))
    {
        _authState = AuthState::Running;
        _stopFlag = 0;
        canStart = true;
    }
    LeaveCriticalSection(&_cs);
    if (!canStart)
    {
        return;
    }
    AddRef();  // 线程持有一个引用,线程退出时释放
    _hAuthThread = CreateThread(nullptr, 0, _AuthThreadProc, this, 0, nullptr);
    if (_hAuthThread == nullptr)
    {
        Release();
        EnterCriticalSection(&_cs);
        _authState = AuthState::Idle;
        LeaveCriticalSection(&_cs);
    }
}

// 取消选中/销毁时停掉扫描线程(等它退出,确保不再回调已失效的 events)。
void CFaceCredential::_StopAuthThread()
{
    InterlockedExchange(&_stopFlag, 1);
    HANDLE h = _hAuthThread;
    _hAuthThread = nullptr;
    if (h != nullptr)
    {
        WaitForSingleObject(h, 5000);  // poll 很快返回,通常 <1s
        CloseHandle(h);
    }
    EnterCriticalSection(&_cs);
    if (_authState == AuthState::Running)
    {
        _authState = AuthState::Idle;
    }
    LeaveCriticalSection(&_cs);
}

DWORD WINAPI CFaceCredential::_AuthThreadProc(LPVOID param)
{
    CFaceCredential* self = static_cast<CFaceCredential*>(param);
    self->_AuthLoop();
    self->Release();  // 对应 _StartAuthThread 的 AddRef
    return 0;
}

void CFaceCredential::_AuthLoop()
{
    std::wstring reason;
    if (!PipeClient::AuthStart(reason))
    {
        _SetStatus((L"认证服务不可用: " + reason).c_str());
        EnterCriticalSection(&_cs);
        _authState = AuthState::Failed;
        LeaveCriticalSection(&_cs);
        return;
    }

    for (;;)
    {
        if (InterlockedCompareExchange(&_stopFlag, 0, 0) == 1)
        {
            return;  // 被取消;状态已在 _StopAuthThread 里复位
        }
        bool done = false, success = false;
        std::wstring instr, user, rsn;
        if (!PipeClient::AuthPoll(done, success, instr, user, rsn))
        {
            _SetStatus(L"与认证服务通信中断");
            EnterCriticalSection(&_cs);
            _authState = AuthState::Failed;
            LeaveCriticalSection(&_cs);
            return;
        }
        if (!done)
        {
            if (!instr.empty())
            {
                _SetStatus(instr.c_str());  // 把"请眨眼/转头"刷到锁屏
            }
            Sleep(400);
            continue;
        }
        if (success)
        {
            EnterCriticalSection(&_cs);
            _authUser = user;
            _authState = AuthState::Success;
            LeaveCriticalSection(&_cs);
            _SetStatus(L"识别通过,正在登录…");
            if (_pProvider != nullptr)
            {
                _pProvider->SignalAutoLogon();  // 触发 LogonUI 调 GetSerialization
            }
        }
        else
        {
            _SetStatus((L"刷脸未通过: " + rsn).c_str());
            EnterCriticalSection(&_cs);
            _authState = AuthState::Failed;
            LeaveCriticalSection(&_cs);
        }
        return;
    }
}

void CFaceCredential::_SetStatus(PCWSTR text)
{
    EnterCriticalSection(&_cs);
    CoTaskMemFree(_rgFieldStrings[FFI_STATUS]);
    _rgFieldStrings[FFI_STATUS] = nullptr;
    SHStrDupW(text, &_rgFieldStrings[FFI_STATUS]);
    if (_pCredProvCredentialEvents != nullptr && _rgFieldStrings[FFI_STATUS] != nullptr &&
        InterlockedCompareExchange(&_stopFlag, 0, 0) == 0)
    {
        _pCredProvCredentialEvents->SetFieldString(this, FFI_STATUS, _rgFieldStrings[FFI_STATUS]);
    }
    LeaveCriticalSection(&_cs);
}

IFACEMETHODIMP CFaceCredential::GetFieldState(
    DWORD dwFieldID,
    CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
    CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis)
{
    if (dwFieldID < FFI_NUM_FIELDS && pcpfs && pcpfis)
    {
        *pcpfs = g_fieldStatePairs[dwFieldID].cpfs;
        *pcpfis = g_fieldStatePairs[dwFieldID].cpfis;
        return S_OK;
    }
    return E_INVALIDARG;
}

IFACEMETHODIMP CFaceCredential::GetStringValue(DWORD dwFieldID, PWSTR* ppwsz)
{
    if (dwFieldID < FFI_NUM_FIELDS && ppwsz)
    {
        PCWSTR src = _rgFieldStrings[dwFieldID] ? _rgFieldStrings[dwFieldID] : L"";
        return SHStrDupW(src, ppwsz);
    }
    return E_INVALIDARG;
}

IFACEMETHODIMP CFaceCredential::GetBitmapValue(DWORD dwFieldID, HBITMAP* phbmp)
{
    if (dwFieldID == FFI_TILEIMAGE && phbmp)
    {
        HBITMAP hbmp = _CreateSolidBitmap(128, 128, RGB(0, 120, 215)); // Windows 蓝
        if (hbmp)
        {
            *phbmp = hbmp;
            return S_OK;
        }
        return HRESULT_FROM_WIN32(GetLastError());
    }
    return E_INVALIDARG;
}

IFACEMETHODIMP CFaceCredential::GetSubmitButtonValue(DWORD dwFieldID, DWORD* pdwAdjacentTo)
{
    if (dwFieldID == FFI_SUBMIT && pdwAdjacentTo)
    {
        *pdwAdjacentTo = FFI_LABEL; // 提交按钮挂在标题旁
        return S_OK;
    }
    return E_INVALIDARG;
}

// 里程碑 c-1:点提交 → 调认证服务 → 读 LSA 密码 → 打包 KERB 提交解锁。
static void _ReportFail(PCWSTR msg, PWSTR* ppwszStatus, CREDENTIAL_PROVIDER_STATUS_ICON* pIcon)
{
    SHStrDupW(msg, ppwszStatus);
    *pIcon = CPSI_ERROR;
}

IFACEMETHODIMP CFaceCredential::GetSerialization(
    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
    PWSTR* ppwszOptionalStatusText,
    CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon)
{
    ZeroMemory(pcpcs, sizeof(*pcpcs));
    *pcpgsr = CPGSR_NO_CREDENTIAL_NOT_FINISHED;
    *ppwszOptionalStatusText = nullptr;
    *pcpsiOptionalStatusIcon = CPSI_NONE;

    // 1. milestone d:识别由后台扫描线程完成,这里只看缓存结果。
    //    未识别成功就返回 NOT_FINISHED(LogonUI 仅在自动提交时调到这里)。
    std::wstring user;
    EnterCriticalSection(&_cs);
    const bool ready = (_authState == AuthState::Success);
    if (ready) { user = _authUser; }
    LeaveCriticalSection(&_cs);
    if (!ready)
    {
        return S_OK;  // 还没识别通过,什么都不提交
    }
    // 这次自动提交已消费:复位状态并清掉自动登录标志,避免失败后死循环重试。
    EnterCriticalSection(&_cs);
    _authState = AuthState::Idle;
    LeaveCriticalSection(&_cs);
    if (_pProvider != nullptr) { _pProvider->ClearAutoLogon(); }

    // 2. 从 LSA Secret 取该用户登录密码(CP 在锁屏是 SYSTEM,可读)。
    std::wstring password;
    if (!CredVault::RetrievePassword(user, password))
    {
        _ReportFail(L"已识别,但未找到登录密码(请先写入 LSA Secret)",
                    ppwszOptionalStatusText, pcpsiOptionalStatusIcon);
        return S_OK;
    }

    // 3. 拆 domain\user;本地账户用计算机名作域。
    std::wstring domain, account;
    const size_t bs = user.find(L'\\');
    if (bs != std::wstring::npos)
    {
        domain = user.substr(0, bs);
        account = user.substr(bs + 1);
    }
    else
    {
        wchar_t comp[MAX_COMPUTERNAME_LENGTH + 1] = {};
        DWORD cch = ARRAYSIZE(comp);
        GetComputerNameW(comp, &cch);
        domain = comp;
        account = user;
    }

    // 4. 打包 KERB_INTERACTIVE_UNLOCK_LOGON 交给 LSA 完成解锁。
    KERB_INTERACTIVE_UNLOCK_LOGON kiul;
    HRESULT hr = KerbInteractiveUnlockLogonInit(
        domain.c_str(), account.c_str(), password.c_str(), _cpus, &kiul);
    if (SUCCEEDED(hr))
    {
        BYTE* rgb = nullptr;
        DWORD cb = 0;
        hr = KerbInteractiveUnlockLogonPack(kiul, &rgb, &cb);
        if (SUCCEEDED(hr))
        {
            ULONG ulAuthPackage = 0;
            hr = RetrieveNegotiateAuthPackage(&ulAuthPackage);
            if (SUCCEEDED(hr))
            {
                pcpcs->ulAuthenticationPackage = ulAuthPackage;
                pcpcs->clsidCredentialProvider = CLSID_FaceHelloProvider;
                pcpcs->rgbSerialization = rgb;
                pcpcs->cbSerialization = cb;
                *pcpgsr = CPGSR_RETURN_CREDENTIAL_FINISHED; // 交给 LogonUI 提交
            }
            else
            {
                CoTaskMemFree(rgb);
            }
        }
    }

    if (!password.empty())
    {
        SecureZeroMemory(&password[0], password.size() * sizeof(wchar_t));
    }
    if (FAILED(hr))
    {
        _ReportFail(L"构造登录凭据失败", ppwszOptionalStatusText, pcpsiOptionalStatusIcon);
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::ReportResult(
    NTSTATUS /*ntsStatus*/, NTSTATUS /*ntsSubstatus*/,
    PWSTR* ppwszOptionalStatusText,
    CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon)
{
    *ppwszOptionalStatusText = nullptr;
    *pcpsiOptionalStatusIcon = CPSI_NONE;
    return S_OK;
}

// ---- 以下字段类型在本磁贴用不到,统一返回 E_NOTIMPL ----
IFACEMETHODIMP CFaceCredential::GetCheckboxValue(DWORD, BOOL*, PWSTR*) { return E_NOTIMPL; }
IFACEMETHODIMP CFaceCredential::GetComboBoxValueCount(DWORD, DWORD*, DWORD*) { return E_NOTIMPL; }
IFACEMETHODIMP CFaceCredential::GetComboBoxValueAt(DWORD, DWORD, PWSTR*) { return E_NOTIMPL; }
IFACEMETHODIMP CFaceCredential::SetStringValue(DWORD, PCWSTR) { return E_NOTIMPL; }
IFACEMETHODIMP CFaceCredential::SetCheckboxValue(DWORD, BOOL) { return E_NOTIMPL; }
IFACEMETHODIMP CFaceCredential::SetComboBoxSelectedValue(DWORD, DWORD) { return E_NOTIMPL; }
IFACEMETHODIMP CFaceCredential::CommandLinkClicked(DWORD) { return E_NOTIMPL; }
