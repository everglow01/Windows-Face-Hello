#pragma once

// FaceHello Credential Provider 的专属 CLSID。
// 注册表字符串形式: {E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}
//
// 注意: DEFINE_GUID 只在「包含了 <initguid.h> 的那个 .cpp」(本工程是 dll.cpp)里
// 真正分配 GUID 实例;其它 .cpp 包含本头只拿到 extern 声明。所以 dll.cpp 必须先
// #include <initguid.h> 再 #include "guid.h"。
DEFINE_GUID(CLSID_FaceHelloProvider,
    0xe071a7ce, 0x5d7f, 0x4063, 0x9a, 0x10, 0xae, 0x39, 0xae, 0xc6, 0x4e, 0xe8);
