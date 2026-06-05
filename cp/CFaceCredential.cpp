#include <new>
#include <string>
#include <shlwapi.h>
#include <ntsecapi.h>
#include "CFaceCredential.h"
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
    : _cRef(1), _cpus(CPUS_INVALID), _pCredProvCredentialEvents(nullptr)
{
    ZeroMemory(_rgFieldStrings, sizeof(_rgFieldStrings));
}

CFaceCredential::~CFaceCredential()
{
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

HRESULT CFaceCredential::Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus)
{
    _cpus = cpus;
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
    // 里程碑 a:选中磁贴不自动触发认证(等接入识别后再改成自动开始)。
    *pbAutoLogon = FALSE;

    // 里程碑 b:选中磁贴时 ping 认证服务,把响应(或失败原因)显示在状态栏,
    // 验证锁屏的 SYSTEM 上下文里 CP↔服务的命名管道通信成立。
    std::wstring summary;
    PipeClient::Ping(summary);
    CoTaskMemFree(_rgFieldStrings[FFI_STATUS]);
    _rgFieldStrings[FFI_STATUS] = nullptr;
    SHStrDupW(summary.c_str(), &_rgFieldStrings[FFI_STATUS]);
    if (_pCredProvCredentialEvents && _rgFieldStrings[FFI_STATUS])
    {
        _pCredProvCredentialEvents->SetFieldString(this, FFI_STATUS, _rgFieldStrings[FFI_STATUS]);
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetDeselected()
{
    return S_OK;
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

    // 1. 调认证服务做识别(c-1 用 mock,直接返回 {ok, user})。
    bool authOk = false;
    std::wstring user, reason;
    if (!PipeClient::Authenticate(authOk, user, reason))
    {
        _ReportFail((L"认证服务不可用: " + reason).c_str(), ppwszOptionalStatusText, pcpsiOptionalStatusIcon);
        return S_OK;
    }
    if (!authOk)
    {
        _ReportFail((L"刷脸未通过: " + reason).c_str(), ppwszOptionalStatusText, pcpsiOptionalStatusIcon);
        return S_OK;
    }

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
