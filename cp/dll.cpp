// FaceHello Credential Provider —— DLL 入口、类工厂、COM 注册。
//
// 安全提示:DllRegisterServer/DllUnregisterServer 只在 regsvr32 调用时写注册表。
// 绝不在主机上注册——只在 Windows 虚拟机(已打快照)里 regsvr32 测试。
#include <new>
#include <windows.h>
#include <strsafe.h>
#include <shlwapi.h>

#include <initguid.h> // 必须在 guid.h 之前,使 DEFINE_GUID 在本 TU 真正分配实例
#include "guid.h"
#include "CFaceProvider.h"
#include "common.h"

static LONG g_cRef = 0;       // DLL 全局对象计数
static HINSTANCE g_hinst = nullptr;

static const wchar_t kProviderName[] = L"FaceHello Credential Provider";

void DllAddRef()  { InterlockedIncrement(&g_cRef); }
void DllRelease() { InterlockedDecrement(&g_cRef); }

// ---- 类工厂 ----
class CClassFactory : public IClassFactory
{
public:
    CClassFactory() : _cRef(1) {}

    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv)
    {
        static const QITAB qit[] =
        {
            QITABENT(CClassFactory, IClassFactory),
            { nullptr },
        };
        return QISearch(this, qit, riid, ppv);
    }
    IFACEMETHODIMP_(ULONG) AddRef() { return InterlockedIncrement(&_cRef); }
    IFACEMETHODIMP_(ULONG) Release()
    {
        LONG cRef = InterlockedDecrement(&_cRef);
        if (cRef == 0) { delete this; }
        return cRef;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* pUnkOuter, REFIID riid, void** ppv)
    {
        if (pUnkOuter) { return CLASS_E_NOAGGREGATION; }
        return CFaceProvider_CreateInstance(riid, ppv);
    }
    IFACEMETHODIMP LockServer(BOOL bLock)
    {
        if (bLock) { DllAddRef(); } else { DllRelease(); }
        return S_OK;
    }

private:
    ~CClassFactory() {}
    LONG _cRef;
};

// ---- DLL 导出 ----
STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv)
{
    if (rclsid == CLSID_FaceHelloProvider)
    {
        CClassFactory* pcf = new (std::nothrow) CClassFactory();
        if (!pcf) { return E_OUTOFMEMORY; }
        HRESULT hr = pcf->QueryInterface(riid, ppv);
        pcf->Release();
        return hr;
    }
    return CLASS_E_CLASSNOTAVAILABLE;
}

STDAPI DllCanUnloadNow()
{
    return (g_cRef > 0) ? S_FALSE : S_OK;
}

static HRESULT _SetSz(HKEY hk, PCWSTR name, PCWSTR val)
{
    DWORD cb = static_cast<DWORD>((wcslen(val) + 1) * sizeof(wchar_t));
    LONG r = RegSetValueExW(hk, name, 0, REG_SZ, reinterpret_cast<const BYTE*>(val), cb);
    return HRESULT_FROM_WIN32(r);
}

STDAPI DllUnregisterServer();

STDAPI DllRegisterServer()
{
    wchar_t szClsid[64];
    StringFromGUID2(CLSID_FaceHelloProvider, szClsid, ARRAYSIZE(szClsid));

    wchar_t szModule[MAX_PATH];
    if (!GetModuleFileNameW(g_hinst, szModule, ARRAYSIZE(szModule)))
    {
        return HRESULT_FROM_WIN32(GetLastError());
    }

    wchar_t key[512];

    // HKCR\CLSID\{clsid}  +  InprocServer32
    StringCchPrintfW(key, ARRAYSIZE(key), L"CLSID\\%s", szClsid);
    HKEY hk = nullptr;
    LONG r = RegCreateKeyExW(HKEY_CLASSES_ROOT, key, 0, nullptr, 0,
                             KEY_WRITE, nullptr, &hk, nullptr);
    if (r != ERROR_SUCCESS) { return HRESULT_FROM_WIN32(r); }
    HRESULT hr = _SetSz(hk, nullptr, kProviderName);
    if (FAILED(hr))
    {
        RegCloseKey(hk);
        DllUnregisterServer();
        return hr;
    }
    HKEY hkInproc = nullptr;
    r = RegCreateKeyExW(hk, L"InprocServer32", 0, nullptr, 0, KEY_WRITE, nullptr, &hkInproc, nullptr);
    if (r != ERROR_SUCCESS)
    {
        RegCloseKey(hk);
        DllUnregisterServer();
        return HRESULT_FROM_WIN32(r);
    }
    hr = _SetSz(hkInproc, nullptr, szModule);
    if (SUCCEEDED(hr))
    {
        hr = _SetSz(hkInproc, L"ThreadingModel", L"Apartment");
    }
    RegCloseKey(hkInproc);
    RegCloseKey(hk);
    if (FAILED(hr))
    {
        DllUnregisterServer();
        return hr;
    }

    // HKLM\...\Authentication\Credential Providers\{clsid}
    StringCchPrintfW(key, ARRAYSIZE(key),
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Providers\\%s",
        szClsid);
    r = RegCreateKeyExW(HKEY_LOCAL_MACHINE, key, 0, nullptr, 0, KEY_WRITE, nullptr, &hk, nullptr);
    if (r != ERROR_SUCCESS)
    {
        DllUnregisterServer();
        return HRESULT_FROM_WIN32(r);
    }
    hr = _SetSz(hk, nullptr, kProviderName);
    RegCloseKey(hk);
    if (FAILED(hr))
    {
        DllUnregisterServer();
        return hr;
    }

    return S_OK;
}

STDAPI DllUnregisterServer()
{
    wchar_t szClsid[64];
    StringFromGUID2(CLSID_FaceHelloProvider, szClsid, ARRAYSIZE(szClsid));

    wchar_t key[512];
    StringCchPrintfW(key, ARRAYSIZE(key),
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Providers\\%s",
        szClsid);
    RegDeleteTreeW(HKEY_LOCAL_MACHINE, key);

    StringCchPrintfW(key, ARRAYSIZE(key), L"CLSID\\%s", szClsid);
    RegDeleteTreeW(HKEY_CLASSES_ROOT, key);

    return S_OK;
}

BOOL APIENTRY DllMain(HINSTANCE hinstDll, DWORD dwReason, LPVOID /*lpReserved*/)
{
    if (dwReason == DLL_PROCESS_ATTACH)
    {
        g_hinst = hinstDll;
        DisableThreadLibraryCalls(hinstDll);
    }
    return TRUE;
}
