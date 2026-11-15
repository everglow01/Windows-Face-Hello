#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include <string>
#include "common.h"

class AutoLogonBridge;

// 单个「刷脸」磁贴。给了用户 SID 时挂在该用户的账户下(ICredentialProviderCredential2:
// 用用户自己的头像,图标出现在其「登录选项」里);没给则是原来的独立磁贴。
class CFaceCredential : public ICredentialProviderCredential2
{
public:
    // IUnknown
    IFACEMETHODIMP_(ULONG) AddRef();
    IFACEMETHODIMP_(ULONG) Release();
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv);

    // ICredentialProviderCredential
    IFACEMETHODIMP Advise(ICredentialProviderCredentialEvents* pcpce);
    IFACEMETHODIMP UnAdvise();
    IFACEMETHODIMP SetSelected(BOOL* pbAutoLogon);
    IFACEMETHODIMP SetDeselected();
    IFACEMETHODIMP GetFieldState(DWORD dwFieldID,
        CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
        CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis);
    IFACEMETHODIMP GetStringValue(DWORD dwFieldID, PWSTR* ppwsz);
    IFACEMETHODIMP GetBitmapValue(DWORD dwFieldID, HBITMAP* phbmp);
    IFACEMETHODIMP GetCheckboxValue(DWORD dwFieldID, BOOL* pbChecked, PWSTR* ppwszLabel);
    IFACEMETHODIMP GetComboBoxValueCount(DWORD dwFieldID, DWORD* pcItems, DWORD* pdwSelectedItem);
    IFACEMETHODIMP GetComboBoxValueAt(DWORD dwFieldID, DWORD dwItem, PWSTR* ppwszItem);
    IFACEMETHODIMP GetSubmitButtonValue(DWORD dwFieldID, DWORD* pdwAdjacentTo);
    IFACEMETHODIMP SetStringValue(DWORD dwFieldID, PCWSTR pwz);
    IFACEMETHODIMP SetCheckboxValue(DWORD dwFieldID, BOOL bChecked);
    IFACEMETHODIMP SetComboBoxSelectedValue(DWORD dwFieldID, DWORD dwSelectedItem);
    IFACEMETHODIMP CommandLinkClicked(DWORD dwFieldID);
    IFACEMETHODIMP GetSerialization(
        CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
        CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
        PWSTR* ppwszOptionalStatusText,
        CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon);
    IFACEMETHODIMP ReportResult(NTSTATUS ntsStatus, NTSTATUS ntsSubstatus,
        PWSTR* ppwszOptionalStatusText,
        CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon);

    // ICredentialProviderCredential2
    IFACEMETHODIMP GetUserSid(PWSTR* ppszSid);

    // userSid / userName 为空 = 不绑定用户的独立磁贴;否则只接受识别结果等于 userName 的人脸。
    HRESULT Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, AutoLogonBridge* autoLogon,
                       PCWSTR userSid, PCWSTR userName);
    bool IsReadyToSubmit();  // 识别已通过、等待 LogonUI 取凭据(Provider 据此选自动提交的磁贴)
    CFaceCredential();

private:
    ~CFaceCredential();

    enum class AuthState { Idle, Running, Success, Failed };

    // 锁屏刷脸最多尝试次数(第 1 次自动,其余靠按「→」重试);用尽退回密码。
    static const int kMaxFaceAttempts = 3;

    void _StartAuthThread();
    void _StopAuthThread();
    void _StartHotkeyThread();
    void _StopHotkeyThread();
    void _AuthLoop();
    void _HotkeyLoop();
    static DWORD WINAPI _AuthThreadProc(LPVOID param);
    static DWORD WINAPI _HotkeyThreadProc(LPVOID param);
    void _SetStatus(PCWSTR text);  // 线程安全地更新状态字段并通知 LogonUI
    void _OnScanFailed(const std::wstring& reason);  // 一次扫描失败:计数 + 刷新状态(含剩余次数)
    PCWSTR _L(PCWSTR zh, PCWSTR en) const { return _en ? en : zh; }  // 按 lang.txt 选中/英文

    LONG _cRef;
    bool _en;  // 界面语言:读 C:\ProgramData\FaceHello\lang.txt,内容 "en" 为真,否则中文
    CREDENTIAL_PROVIDER_USAGE_SCENARIO _cpus;
    AutoLogonBridge* _autoLogon;
    ICredentialProviderCredentialEvents* _pCredProvCredentialEvents;
    PWSTR _rgFieldStrings[FFI_NUM_FIELDS]; // 各文本字段当前内容(CoTaskMem)

    CRITICAL_SECTION _cs;          // 保护 _authState/_authUser/状态字段/events 调用
    HANDLE _hAuthThread;
    HANDLE _hHotkeyThread;
    volatile LONG _stopFlag;       // 1 = 请求停止扫描线程
    volatile LONG _hotkeyStopFlag;
    AuthState _authState;
    std::wstring _authUser;        // 认证通过的账户名(供 GetSerialization)
    std::wstring _userSid;         // 绑定用户的 SID 字符串;空 = 独立磁贴(Initialize 后只读)
    std::wstring _boundUser;       // 绑定用户的本地账户名;空 = 不限定(Initialize 后只读)
    int _failCount;               // 已失败的刷脸次数(达 kMaxFaceAttempts 后停止重试,退回密码)
    int _hotkeyVk;
};
