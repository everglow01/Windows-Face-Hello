#pragma once

#include <windows.h>
#include <string>

// 认证服务的命名管道客户端(对应 Python 的 scripts/auth_client.py)。
// 在锁屏的 SYSTEM 上下文里被 CP 调用,向 \\.\pipe\FaceHello 发 JSON 请求。
namespace PipeClient
{
    // 发一条 JSON 请求,成功返回 true 且 outResponse 为响应 JSON(已转宽字符);
    // 失败(服务未启动/忙/无响应)返回 false,outResponse 为原因文案。
    bool Call(const std::wstring& jsonRequest, std::wstring& outResponse);

    // 便捷封装:ping。里程碑 b 暂不解析 JSON,outSummary 直接给出响应原文。
    bool Ping(std::wstring& outSummary);
}
