#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include <shlwapi.h>

// 把一个字段描述符深拷贝到 CoTaskMem 分配的内存里(调用方/LogonUI 负责释放)。
// Provider::GetFieldDescriptorAt 用它返回字段定义。
inline HRESULT FieldDescriptorCoAllocCopy(
    const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR& rcpfd,
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd)
{
    HRESULT hr;
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* pcpfd =
        static_cast<CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR*>(
            CoTaskMemAlloc(sizeof(CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR)));
    if (pcpfd)
    {
        pcpfd->dwFieldID = rcpfd.dwFieldID;
        pcpfd->cpft = rcpfd.cpft;
        pcpfd->guidFieldType = rcpfd.guidFieldType;
        if (rcpfd.pszLabel)
        {
            hr = SHStrDupW(rcpfd.pszLabel, &pcpfd->pszLabel);
        }
        else
        {
            pcpfd->pszLabel = nullptr;
            hr = S_OK;
        }

        if (FAILED(hr))
        {
            CoTaskMemFree(pcpfd);
        }
    }
    else
    {
        hr = E_OUTOFMEMORY;
    }

    *ppcpfd = SUCCEEDED(hr) ? pcpfd : nullptr;
    return hr;
}
