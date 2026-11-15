#include <new>
#include <string>
#include <shlwapi.h>
#include <ntsecapi.h>
#include <wincodec.h>
#include <strsafe.h>
#include "CFaceCredential.h"
#include "CFaceProvider.h"
#include "common.h"
#include "PipeClient.h"
#include "CredVault.h"
#include "KerbHelpers.h"
#include "guid.h"

// 生成一张纯色磁贴位图,供自定义头像不可用时回退。
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

// 内置默认图标:深灰蓝底 + 白色「扫脸」线条(四角取景框、双眼、微笑)。
// 登录界面画这张图时不认透明通道(实测透明处显示为黑),所以用不透明底色;
// 先在 512×512 上用粗线画,再 HALFTONE 缩小到目标尺寸,得到平滑边缘。
// 任一步失败返回 nullptr,交由调用方退回纯色占位图。
static HBITMAP _CreateDefaultIconBitmap(int w, int h)
{
    const int S = 512;
    auto makeDib = [](int cx, int cy, void** bits) -> HBITMAP
    {
        BITMAPINFO bmi = {};
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        bmi.bmiHeader.biWidth = cx;
        bmi.bmiHeader.biHeight = -cy; // 自上而下
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = BI_RGB;
        return CreateDIBSection(nullptr, &bmi, DIB_RGB_COLORS, bits, nullptr, 0);
    };

    void* bigBits = nullptr;
    void* outBits = nullptr;
    HBITMAP hBig = makeDib(S, S, &bigBits);
    HBITMAP hOut = makeDib(w, h, &outBits);
    HDC dcBig = CreateCompatibleDC(nullptr);
    HDC dcOut = CreateCompatibleDC(nullptr);
    if (!hBig || !hOut || !dcBig || !dcOut || !outBits)
    {
        if (hBig) DeleteObject(hBig);
        if (hOut) DeleteObject(hOut);
        if (dcBig) DeleteDC(dcBig);
        if (dcOut) DeleteDC(dcOut);
        return nullptr;
    }

    HGDIOBJ oldBig = SelectObject(dcBig, hBig);
    HGDIOBJ oldOut = SelectObject(dcOut, hOut);

    RECT all = { 0, 0, S, S };
    HBRUSH background = CreateSolidBrush(RGB(0x2B, 0x34, 0x45));
    FillRect(dcBig, &all, background);
    DeleteObject(background);

    LOGBRUSH lb = {};
    lb.lbStyle = BS_SOLID;
    lb.lbColor = RGB(255, 255, 255);
    HPEN pen = ExtCreatePen(PS_GEOMETRIC | PS_SOLID | PS_ENDCAP_ROUND | PS_JOIN_ROUND, 34, &lb, 0, nullptr);
    HGDIOBJ oldPen = SelectObject(dcBig, pen);
    HGDIOBJ oldBrush = SelectObject(dcBig, GetStockObject(NULL_BRUSH));

    // 四角取景框
    const int a = 96, b = S - 96, L = 96;
    const POINT corners[4][3] = {
        { { a, a + L }, { a, a }, { a + L, a } },
        { { b - L, a }, { b, a }, { b, a + L } },
        { { b, b - L }, { b, b }, { b - L, b } },
        { { a + L, b }, { a, b }, { a, b - L } },
    };
    for (const auto& c : corners)
    {
        Polyline(dcBig, c, 3);
    }
    // 双眼
    MoveToEx(dcBig, 204, 204, nullptr);
    LineTo(dcBig, 204, 244);
    MoveToEx(dcBig, 308, 204, nullptr);
    LineTo(dcBig, 308, 244);
    // 微笑:椭圆下半段(默认逆时针,从左端画到右端)
    Arc(dcBig, 176, 216, 336, 356, 186, 310, 326, 310);

    SelectObject(dcBig, oldBrush);
    SelectObject(dcBig, oldPen);
    DeleteObject(pen);

    SetStretchBltMode(dcOut, HALFTONE);
    SetBrushOrgEx(dcOut, 0, 0, nullptr);
    StretchBlt(dcOut, 0, 0, w, h, dcBig, 0, 0, S, S, SRCCOPY);
    GdiFlush();

    // GDI 不写 alpha:统一置为不透明。
    DWORD* px = static_cast<DWORD*>(outBits);
    for (int i = 0; i < w * h; ++i)
    {
        px[i] |= 0xFF000000;
    }

    SelectObject(dcBig, oldBig);
    SelectObject(dcOut, oldOut);
    DeleteDC(dcBig);
    DeleteDC(dcOut);
    DeleteObject(hBig);
    return hOut;
}

// 用 WIC 解码 png/jpg/bmp,按短边居中裁成正方形(不拉伸变形)再缩放到 w×h,
// 转成 top-down 32bpp 后返回 HBITMAP。
// 任一步失败返回 nullptr,交由调用方回退纯色占位图。
static HBITMAP _LoadBitmapFromFileWIC(PCWSTR path, int w, int h)
{
    // CP 跑在 LogonUI 进程,COM 一般已初始化;RPC_E_CHANGED_MODE 视为已初始化、不反初始化。
    HRESULT hrInit = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    bool needUninit = SUCCEEDED(hrInit);

    HBITMAP hbmp = nullptr;
    IWICImagingFactory* pFactory = nullptr;
    IWICBitmapDecoder* pDecoder = nullptr;
    IWICBitmapFrameDecode* pFrame = nullptr;
    IWICBitmapClipper* pClipper = nullptr;
    IWICBitmapScaler* pScaler = nullptr;
    IWICFormatConverter* pConverter = nullptr;

    HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                  IID_PPV_ARGS(&pFactory));
    if (SUCCEEDED(hr))
        hr = pFactory->CreateDecoderFromFilename(path, nullptr, GENERIC_READ,
                                                 WICDecodeMetadataCacheOnDemand, &pDecoder);
    if (SUCCEEDED(hr))
        hr = pDecoder->GetFrame(0, &pFrame);
    // 按短边取中间正方形:避免非正方形图被直接缩放拉伸变形
    UINT uiW = 0, uiH = 0;
    if (SUCCEEDED(hr))
        hr = pFrame->GetSize(&uiW, &uiH);
    if (SUCCEEDED(hr))
        hr = pFactory->CreateBitmapClipper(&pClipper);
    if (SUCCEEDED(hr))
    {
        const UINT side = (uiW < uiH) ? uiW : uiH;
        WICRect rc = { static_cast<INT>((uiW - side) / 2),
                       static_cast<INT>((uiH - side) / 2),
                       static_cast<INT>(side), static_cast<INT>(side) };
        hr = pClipper->Initialize(pFrame, &rc);
    }
    if (SUCCEEDED(hr))
        hr = pFactory->CreateBitmapScaler(&pScaler);
    if (SUCCEEDED(hr))
        hr = pScaler->Initialize(pClipper, w, h, WICBitmapInterpolationModeFant);
    if (SUCCEEDED(hr))
        hr = pFactory->CreateFormatConverter(&pConverter);
    if (SUCCEEDED(hr))
        hr = pConverter->Initialize(pScaler, GUID_WICPixelFormat32bppPBGRA,
                                    WICBitmapDitherTypeNone, nullptr, 0.0,
                                    WICBitmapPaletteTypeCustom);
    if (SUCCEEDED(hr))
    {
        BITMAPINFO bmi = {};
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        bmi.bmiHeader.biWidth = w;
        bmi.bmiHeader.biHeight = -h; // 负高 = 自上而下,与 _CreateSolidBitmap 一致
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = BI_RGB;

        void* pBits = nullptr;
        HBITMAP hTmp = CreateDIBSection(nullptr, &bmi, DIB_RGB_COLORS, &pBits, nullptr, 0);
        if (hTmp && pBits)
        {
            const UINT stride = static_cast<UINT>(w) * 4;
            const UINT cbBuffer = stride * static_cast<UINT>(h);
            hr = pConverter->CopyPixels(nullptr, stride, cbBuffer,
                                        static_cast<BYTE*>(pBits));
            if (SUCCEEDED(hr))
                hbmp = hTmp;
            else
                DeleteObject(hTmp);
        }
    }

    if (pConverter) pConverter->Release();
    if (pScaler)    pScaler->Release();
    if (pClipper)   pClipper->Release();
    if (pFrame)     pFrame->Release();
    if (pDecoder)   pDecoder->Release();
    if (pFactory)   pFactory->Release();
    if (needUninit) CoUninitialize();
    return hbmp;
}

// 在 dir 里找第一张 png/jpg/jpeg/bmp,把全路径写进 outPath。找到返回 true。
static bool _FindFirstImageInFolder(PCWSTR dir, PWSTR outPath, size_t cch)
{
    wchar_t pattern[MAX_PATH];
    if (FAILED(StringCchCopyW(pattern, ARRAYSIZE(pattern), dir)) ||
        FAILED(StringCchCatW(pattern, ARRAYSIZE(pattern), L"*")))
        return false;

    WIN32_FIND_DATAW fd = {};
    HANDLE hFind = FindFirstFileW(pattern, &fd);
    if (hFind == INVALID_HANDLE_VALUE)
        return false;

    bool found = false;
    do
    {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            continue;
        PCWSTR ext = PathFindExtensionW(fd.cFileName);
        if (_wcsicmp(ext, L".png") == 0 || _wcsicmp(ext, L".jpg") == 0 ||
            _wcsicmp(ext, L".jpeg") == 0 || _wcsicmp(ext, L".bmp") == 0)
        {
            if (SUCCEEDED(StringCchCopyW(outPath, cch, dir)) &&
                SUCCEEDED(StringCchCatW(outPath, cch, fd.cFileName)))
                found = true;
            break;
        }
    } while (FindNextFileW(hFind, &fd));

    FindClose(hFind);
    return found;
}

// 读 C:\ProgramData\FaceHello\lang.txt(控制台 / 服务写的语言镜像)。内容以 "en" 开头
// 返回 true(英文),否则一律按中文(默认)。CP 在锁屏是 SYSTEM,可读该 ASCII 路径;
// 控制台读不了 DPAPI 人脸库,故语言以此明文文件跨进程传递。
static bool _IsEnglishUI()
{
    HANDLE h = CreateFileW(L"C:\\ProgramData\\FaceHello\\lang.txt", GENERIC_READ,
                           FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE)
        return false;
    char buf[8] = {};
    DWORD read = 0;
    bool en = ReadFile(h, buf, sizeof(buf) - 1, &read, nullptr) && read >= 2 &&
              buf[0] == 'e' && buf[1] == 'n';
    CloseHandle(h);
    return en;
}

static int _ReadHotkeyVk()
{
    HANDLE h = CreateFileW(L"C:\\ProgramData\\FaceHello\\hotkey.txt", GENERIC_READ,
                           FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE)
        return 0;
    char buf[32] = {};
    DWORD read = 0;
    ReadFile(h, buf, sizeof(buf) - 1, &read, nullptr);
    CloseHandle(h);
    std::string s(buf);
    while (!s.empty() && (s.back() == '\r' || s.back() == '\n' || s.back() == ' '))
        s.pop_back();
    for (char& c : s)
    {
        if (c >= 'a' && c <= 'z')
            c = static_cast<char>(c - 'a' + 'A');
    }
    if (s == "SPACE")
        return VK_SPACE;
    if (s == "ENTER")
        return VK_RETURN;
    if (s.size() == 1 && ((s[0] >= 'A' && s[0] <= 'Z') || (s[0] >= '0' && s[0] <= '9')))
        return static_cast<unsigned char>(s[0]);
    return 0;
}

CFaceCredential::CFaceCredential()
    : _cRef(1), _cpus(CPUS_INVALID), _autoLogon(nullptr),
      _pCredProvCredentialEvents(nullptr), _hAuthThread(nullptr), _hHotkeyThread(nullptr),
      _stopFlag(0), _hotkeyStopFlag(0), _authState(AuthState::Idle), _en(false),
      _failCount(0), _hotkeyVk(0)
{
    ZeroMemory(_rgFieldStrings, sizeof(_rgFieldStrings));
    InitializeCriticalSection(&_cs);
    DllAddRef();
}

CFaceCredential::~CFaceCredential()
{
    _StopHotkeyThread();
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
    if (_autoLogon)
    {
        _autoLogon->Release();
        _autoLogon = nullptr;
    }
    DllRelease();
}

HRESULT CFaceCredential::Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, AutoLogonBridge* autoLogon,
                                    PCWSTR userSid, PCWSTR userName)
{
    _cpus = cpus;
    _autoLogon = autoLogon;
    if (_autoLogon)
    {
        _autoLogon->AddRef();
    }
    // 两者都给才算绑定用户;只给其一按独立磁贴处理,避免出现「挂在用户下却不核对身份」的状态。
    if (userSid && userSid[0] != L'\0' && userName && userName[0] != L'\0')
    {
        _userSid = userSid;
        _boundUser = userName;
    }
    _en = _IsEnglishUI();  // 读一次语言镜像,贯穿本磁贴所有文案
    _hotkeyVk = _ReadHotkeyVk();
    HRESULT hr = SHStrDupW(_L(L"面部解锁", L"Face Unlock"), &_rgFieldStrings[FFI_LABEL]);
    if (SUCCEEDED(hr))
    {
        hr = SHStrDupW(L"", &_rgFieldStrings[FFI_STATUS]);
    }
    if (SUCCEEDED(hr))
    {
        hr = SHStrDupW(_L(L"面部解锁", L"Face Unlock"), &_rgFieldStrings[FFI_PROVIDER_LABEL]);
    }
    return hr;
}

bool CFaceCredential::IsReadyToSubmit()
{
    EnterCriticalSection(&_cs);
    const bool ready = (_authState == AuthState::Success);
    LeaveCriticalSection(&_cs);
    return ready;
}

// ICredentialProviderCredential2:返回绑定用户的 SID,LogonUI 据此把本磁贴并入该用户的账户。
IFACEMETHODIMP CFaceCredential::GetUserSid(PWSTR* ppszSid)
{
    if (!ppszSid)
    {
        return E_INVALIDARG;
    }
    *ppszSid = nullptr;
    if (_userSid.empty())
    {
        return S_FALSE;
    }
    return SHStrDupW(_userSid.c_str(), ppszSid);
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
    if (!ppv)
    {
        return E_POINTER;
    }
    *ppv = nullptr;
    // ICredentialProviderCredential2 只在绑定了用户时才对外承认:不绑定用户的磁贴若也实现它,
    // LogonUI 会把它并进「其他用户」,而不是原来那个独立磁贴。
    if (riid == __uuidof(IUnknown) || riid == __uuidof(ICredentialProviderCredential) ||
        (riid == __uuidof(ICredentialProviderCredential2) && !_userSid.empty()))
    {
        *ppv = static_cast<ICredentialProviderCredential2*>(this);
        AddRef();
        return S_OK;
    }
    return E_NOINTERFACE;
}

IFACEMETHODIMP CFaceCredential::Advise(ICredentialProviderCredentialEvents* pcpce)
{
    if (pcpce)
    {
        pcpce->AddRef();
    }
    EnterCriticalSection(&_cs);
    ICredentialProviderCredentialEvents* old = _pCredProvCredentialEvents;
    _pCredProvCredentialEvents = pcpce;
    LeaveCriticalSection(&_cs);
    if (old)
    {
        old->Release();
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::UnAdvise()
{
    EnterCriticalSection(&_cs);
    ICredentialProviderCredentialEvents* old = _pCredProvCredentialEvents;
    _pCredProvCredentialEvents = nullptr;
    LeaveCriticalSection(&_cs);
    if (old)
    {
        old->Release();
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetSelected(BOOL* pbAutoLogon)
{
    *pbAutoLogon = FALSE;
    bool firstReady;
    EnterCriticalSection(&_cs);
    firstReady = (_authState == AuthState::Idle && _failCount == 0);
    LeaveCriticalSection(&_cs);
    if (firstReady)
    {
        _SetStatus(_L(L"按 → 开始刷脸", L"Press → to start face unlock"));
    }
    _StartHotkeyThread();
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetDeselected()
{
    _StopHotkeyThread();
    _StopAuthThread();
    return S_OK;
}

// 选中磁贴时拉起后台扫描线程。仅在空闲/失败态允许重新开始。
void CFaceCredential::_StartAuthThread()
{
    // 回收上一轮已自然结束的线程句柄,否则失败/成功后再选中磁贴无法重新扫描。
    if (_hAuthThread != nullptr && WaitForSingleObject(_hAuthThread, 0) == WAIT_OBJECT_0)
    {
        CloseHandle(_hAuthThread);
        _hAuthThread = nullptr;
    }

    bool canStart = false;
    EnterCriticalSection(&_cs);
    if (_hAuthThread == nullptr &&
        (_authState == AuthState::Idle || _authState == AuthState::Failed) &&
        _failCount < kMaxFaceAttempts)  // 用尽 3 次后:自动起与手动重试都不再刷脸
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
        if (GetThreadId(h) != GetCurrentThreadId())
        {
            WaitForSingleObject(h, 5000);  // poll 很快返回,通常 <1s
        }
        CloseHandle(h);
    }
    EnterCriticalSection(&_cs);
    if (_authState == AuthState::Running)
    {
        _authState = AuthState::Idle;
    }
    LeaveCriticalSection(&_cs);
}

void CFaceCredential::_StartHotkeyThread()
{
    if (_hotkeyVk == 0)
        return;
    if (_hHotkeyThread != nullptr && WaitForSingleObject(_hHotkeyThread, 0) == WAIT_OBJECT_0)
    {
        CloseHandle(_hHotkeyThread);
        _hHotkeyThread = nullptr;
    }

    bool canStart = false;
    EnterCriticalSection(&_cs);
    if (_hHotkeyThread == nullptr && _authState != AuthState::Running &&
        _authState != AuthState::Success && _failCount < kMaxFaceAttempts)
    {
        _hotkeyStopFlag = 0;
        canStart = true;
    }
    LeaveCriticalSection(&_cs);
    if (!canStart)
        return;
    AddRef();
    _hHotkeyThread = CreateThread(nullptr, 0, _HotkeyThreadProc, this, 0, nullptr);
    if (_hHotkeyThread == nullptr)
    {
        Release();
    }
}

void CFaceCredential::_StopHotkeyThread()
{
    InterlockedExchange(&_hotkeyStopFlag, 1);
    HANDLE h = _hHotkeyThread;
    _hHotkeyThread = nullptr;
    if (h != nullptr)
    {
        if (GetThreadId(h) != GetCurrentThreadId())
        {
            WaitForSingleObject(h, 1000);
        }
        CloseHandle(h);
    }
}

DWORD WINAPI CFaceCredential::_AuthThreadProc(LPVOID param)
{
    CFaceCredential* self = static_cast<CFaceCredential*>(param);
    self->_AuthLoop();
    self->Release();  // 对应 _StartAuthThread 的 AddRef
    return 0;
}

DWORD WINAPI CFaceCredential::_HotkeyThreadProc(LPVOID param)
{
    CFaceCredential* self = static_cast<CFaceCredential*>(param);
    self->_HotkeyLoop();
    self->Release();
    return 0;
}

void CFaceCredential::_HotkeyLoop()
{
    GetAsyncKeyState(_hotkeyVk);
    bool wasDown = (GetAsyncKeyState(_hotkeyVk) & 0x8000) != 0;
    for (;;)
    {
        if (InterlockedCompareExchange(&_hotkeyStopFlag, 0, 0) == 1)
            return;
        SHORT st = GetAsyncKeyState(_hotkeyVk);
        bool down = (st & 0x8000) != 0;
        if ((st & 0x0001) != 0 || (down && !wasDown))
        {
            _StartAuthThread();
            return;
        }
        wasDown = down;
        Sleep(30);
    }
}

void CFaceCredential::_AuthLoop()
{
    std::wstring reason;
    if (!PipeClient::AuthStart(reason))
    {
        _OnScanFailed(std::wstring(_L(L"认证服务不可用: ", L"Auth service unavailable: ")) + reason);
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
            _OnScanFailed(_L(L"与认证服务通信中断", L"Lost connection to auth service"));
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
            // 绑定了用户的磁贴只接受该用户的脸:服务在整库里取最相似者,识别出的若是别人,
            // 不能拿别人的身份去登录当前选中的账户。
            if (!_boundUser.empty() && _wcsicmp(user.c_str(), _boundUser.c_str()) != 0)
            {
                _OnScanFailed(_L(L"刷脸未通过: 识别到的人脸不属于此账户",
                                 L"Face check failed: the recognized face does not belong to this account"));
                return;
            }
            EnterCriticalSection(&_cs);
            _authUser = user;
            _authState = AuthState::Success;
            LeaveCriticalSection(&_cs);
            _SetStatus(_L(L"识别通过,正在登录…", L"Recognized, signing in…"));
            if (_autoLogon != nullptr)
            {
                _autoLogon->Signal();  // 触发 LogonUI 调 GetSerialization
            }
        }
        else
        {
            _OnScanFailed(std::wstring(_L(L"刷脸未通过: ", L"Face check failed: ")) + rsn);
        }
        return;
    }
}

void CFaceCredential::_SetStatus(PCWSTR text)
{
    ICredentialProviderCredentialEvents* events = nullptr;
    std::wstring status(text ? text : L"");
    EnterCriticalSection(&_cs);
    CoTaskMemFree(_rgFieldStrings[FFI_STATUS]);
    _rgFieldStrings[FFI_STATUS] = nullptr;
    SHStrDupW(text, &_rgFieldStrings[FFI_STATUS]);
    if (_pCredProvCredentialEvents != nullptr && _rgFieldStrings[FFI_STATUS] != nullptr &&
        InterlockedCompareExchange(&_stopFlag, 0, 0) == 0)
    {
        events = _pCredProvCredentialEvents;
        events->AddRef();
    }
    LeaveCriticalSection(&_cs);
    if (events)
    {
        events->SetFieldString(this, FFI_STATUS, status.c_str());
        events->Release();
    }
}

// 一次刷脸扫描失败:计数 +1、置 Failed,据剩余次数刷新状态文字。
// 任何失败都算(置信度低/反欺骗/活体/不匹配,或服务不可用/通信中断)。
// 文案里的「→」是 LogonUI 渲染的提交按钮箭头;工程用 /utf-8 编译,直接写中文与 → 均可。
void CFaceCredential::_OnScanFailed(const std::wstring& reason)
{
    int remaining;
    EnterCriticalSection(&_cs);
    ++_failCount;
    _authState = AuthState::Failed;
    remaining = kMaxFaceAttempts - _failCount;
    LeaveCriticalSection(&_cs);

    std::wstring msg;
    if (remaining > 0)
    {
        // 例:"刷脸未通过: 相似度低(按 → 重试,剩 2 次)"
        msg = reason;
        msg += _L(L"(按 → 重试,剩 ", L" (press → to retry, ");
        msg += std::to_wstring(remaining);
        msg += _L(L" 次)", L" left)");
    }
    else
    {
        msg = _L(L"刷脸已失败 ", L"Face unlock failed ");
        msg += std::to_wstring(kMaxFaceAttempts);
        msg += _L(L" 次,请改用密码登录", L" times — use your password");
    }
    _SetStatus(msg.c_str());
    if (remaining > 0)
    {
        _StartHotkeyThread();
    }
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
        // 优先用 C:\ProgramData\FaceHello\ 里的自定义头像;读不到/解码失败用内置扫脸图标,
        // 连它也画不出来才退回纯蓝占位。
        HBITMAP hbmp = nullptr;
        wchar_t imgPath[MAX_PATH];
        if (_FindFirstImageInFolder(L"C:\\ProgramData\\FaceHello\\", imgPath, ARRAYSIZE(imgPath)))
            hbmp = _LoadBitmapFromFileWIC(imgPath, 128, 128);
        if (!hbmp)
            hbmp = _CreateDefaultIconBitmap(128, 128);
        if (!hbmp)
            hbmp = _CreateSolidBitmap(128, 128, RGB(0, 120, 215)); // Windows 蓝
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

    // 识别由后台扫描线程完成,这里只看缓存结果。
    //    未识别成功就返回 NOT_FINISHED(LogonUI 仅在自动提交时调到这里)。
    std::wstring user;
    EnterCriticalSection(&_cs);
    const bool ready = (_authState == AuthState::Success);
    if (ready) { user = _authUser; }
    LeaveCriticalSection(&_cs);
    if (!ready)
    {
        // 用户按了「→」提交按钮但还没识别成功:开始或重试刷脸。
        // 还有机会且当前没有扫描在跑 → 重启刷脸;否则什么都不做——
        // 状态文字已由 _OnScanFailed 设成「(按 → 重试,剩 N 次)」或用尽时的「请改用密码登录」,
        // 扫描进行中(Running)则正由 _AuthLoop 刷活体提示,都不该被覆盖。
        bool canRetry;
        EnterCriticalSection(&_cs);
        canRetry = (_failCount < kMaxFaceAttempts && _authState != AuthState::Running);
        LeaveCriticalSection(&_cs);
        if (canRetry)
        {
            _StartAuthThread();  // 发起下一次刷脸
        }
        return S_OK;  // 仍 NOT_FINISHED,不提交凭据
    }
    // 这次自动提交已消费:复位状态并清掉自动登录标志,避免失败后死循环重试。
    EnterCriticalSection(&_cs);
    _authState = AuthState::Idle;
    LeaveCriticalSection(&_cs);
    if (_autoLogon != nullptr) { _autoLogon->Clear(); }

    // 从 LSA Secret 取该用户登录密码(CP 在锁屏是 SYSTEM,可读)。
    std::wstring password;
    if (!CredVault::RetrievePassword(user, password))
    {
        _ReportFail(_L(L"已识别,但未找到登录密码(请先写入 LSA Secret)",
                       L"Recognized, but no sign-in password found (set it in the console first)"),
                    ppwszOptionalStatusText, pcpsiOptionalStatusIcon);
        return S_OK;
    }

    // 拆 domain\user;本地账户用计算机名作域。
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

    // 打包 KERB_INTERACTIVE_UNLOCK_LOGON 交给 LSA 完成解锁。
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
        _ReportFail(_L(L"构造登录凭据失败", L"Failed to build sign-in credential"),
                    ppwszOptionalStatusText, pcpsiOptionalStatusIcon);
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
