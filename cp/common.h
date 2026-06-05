#pragma once

#include <windows.h>
#include <strsafe.h>
#include <credentialprovider.h>

// 刷脸磁贴上的字段(里程碑 a):图标 + 标题 + 提交按钮 + 状态文字。
enum FACE_FIELD_ID
{
    FFI_TILEIMAGE  = 0,
    FFI_LABEL      = 1,
    FFI_SUBMIT     = 2,
    FFI_STATUS     = 3,
    FFI_NUM_FIELDS = 4,
};

// 字段的显示状态(在普通磁贴 / 仅选中磁贴时显示)与交互状态。
struct FIELD_STATE_PAIR
{
    CREDENTIAL_PROVIDER_FIELD_STATE cpfs;
    CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE cpfis;
};

// 在 CFaceProvider.cpp 中定义,Provider 与 Credential 共用。
extern const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR g_fieldDescriptors[FFI_NUM_FIELDS];
extern const FIELD_STATE_PAIR g_fieldStatePairs[FFI_NUM_FIELDS];

// 全局 DLL 引用计数(dll.cpp 实现),控制 DllCanUnloadNow。
void DllAddRef();
void DllRelease();
