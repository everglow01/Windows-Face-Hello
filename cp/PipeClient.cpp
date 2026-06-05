#include "PipeClient.h"

namespace
{
constexpr wchar_t kPipeName[] = L"\\\\.\\pipe\\FaceHello";
constexpr DWORD kBufSize = 65536;

std::string WideToUtf8(const std::wstring& w)
{
    if (w.empty()) { return {}; }
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()),
                                nullptr, 0, nullptr, nullptr);
    std::string s(static_cast<size_t>(n), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()),
                        s.data(), n, nullptr, nullptr);
    return s;
}

std::wstring Utf8ToWide(const char* p, int len)
{
    if (len <= 0) { return {}; }
    int n = MultiByteToWideChar(CP_UTF8, 0, p, len, nullptr, 0);
    std::wstring w(static_cast<size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, p, len, w.data(), n);
    return w;
}
} // namespace

bool PipeClient::Call(const std::wstring& jsonRequest, std::wstring& outResponse)
{
    HANDLE hPipe = INVALID_HANDLE_VALUE;
    for (int attempt = 0; attempt < 2; ++attempt)
    {
        hPipe = CreateFileW(kPipeName, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                            OPEN_EXISTING, 0, nullptr);
        if (hPipe != INVALID_HANDLE_VALUE) { break; }

        if (GetLastError() != ERROR_PIPE_BUSY)
        {
            outResponse = L"auth service not running";
            return false;
        }
        if (!WaitNamedPipeW(kPipeName, 3000)) // 服务忙,等一会儿管道实例
        {
            outResponse = L"auth service busy / timeout";
            return false;
        }
    }
    if (hPipe == INVALID_HANDLE_VALUE)
    {
        outResponse = L"auth service not running";
        return false;
    }

    // 切到消息读模式,与服务端 PIPE_TYPE_MESSAGE 一致(一次请求一条消息)。
    DWORD mode = PIPE_READMODE_MESSAGE;
    SetNamedPipeHandleState(hPipe, &mode, nullptr, nullptr);

    bool ok = false;
    const std::string req = WideToUtf8(jsonRequest);
    DWORD written = 0;
    if (WriteFile(hPipe, req.data(), static_cast<DWORD>(req.size()), &written, nullptr))
    {
        std::string buf(kBufSize, '\0');
        DWORD read = 0;
        if (ReadFile(hPipe, buf.data(), kBufSize, &read, nullptr) && read > 0)
        {
            outResponse = Utf8ToWide(buf.data(), static_cast<int>(read));
            ok = true;
        }
        else
        {
            outResponse = L"no response from service";
        }
    }
    else
    {
        outResponse = L"failed to send request";
    }

    CloseHandle(hPipe);
    return ok;
}

bool PipeClient::Ping(std::wstring& outSummary)
{
    std::wstring resp;
    const bool ok = Call(L"{\"cmd\": \"ping\"}", resp);
    outSummary = resp; // 里程碑 b:成功/失败都把原文显示出来
    return ok;
}

namespace
{
// 极简 JSON 取值(响应来自我们自己的服务,格式可控)。
bool ExtractBool(const std::wstring& json, const std::wstring& field, bool& val)
{
    const std::wstring key = L"\"" + field + L"\"";
    size_t p = json.find(key);
    if (p == std::wstring::npos) { return false; }
    p = json.find(L':', p + key.size());
    if (p == std::wstring::npos) { return false; }
    ++p;
    while (p < json.size() && json[p] == L' ') { ++p; }
    if (json.compare(p, 4, L"true") == 0) { val = true; return true; }
    if (json.compare(p, 5, L"false") == 0) { val = false; return true; }
    return false;
}

bool ExtractString(const std::wstring& json, const std::wstring& field, std::wstring& val)
{
    const std::wstring key = L"\"" + field + L"\"";
    size_t p = json.find(key);
    if (p == std::wstring::npos) { return false; }
    p = json.find(L':', p + key.size());
    if (p == std::wstring::npos) { return false; }
    p = json.find(L'"', p);
    if (p == std::wstring::npos) { return false; }
    const size_t end = json.find(L'"', p + 1);
    if (end == std::wstring::npos) { return false; }
    val = json.substr(p + 1, end - p - 1);
    return true;
}
} // namespace

bool PipeClient::Authenticate(bool& outOk, std::wstring& outUser, std::wstring& outReason)
{
    std::wstring resp;
    if (!Call(L"{\"cmd\": \"authenticate\"}", resp))
    {
        outOk = false;
        outReason = resp; // 传输失败原因
        return false;
    }

    outOk = false;
    ExtractBool(resp, L"ok", outOk);
    if (outOk)
    {
        if (!ExtractString(resp, L"user", outUser)) { outUser.clear(); }
        outReason.clear();
    }
    else if (!ExtractString(resp, L"reason", outReason))
    {
        outReason = resp;
    }
    return true; // 拿到了服务响应,结果看 outOk
}
