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
