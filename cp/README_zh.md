# FaceHello Credential Provider（C++）

锁屏 / 登录界面上的「Face Unlock」磁贴。一个 COM in-proc DLL，注册成 Windows Credential Provider；选中磁贴即在后台刷脸，识别通过后**自动提交真实凭据完成登录 / 解锁**。

> [English](./README.md) ｜ 整体设计见 [DESIGN_zh.md](../DESIGN_zh.md)，开发指南见 [contribute_zh.md](../contribute_zh.md)

- **CLSID**：`{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}`
- **进度**：磁贴 → 命名管道 → LocalSystem 服务 → InsightFace 识别 → 读 LSA 密码 → 打包 Kerberos 真解锁，**本地账户与微软账户（MSA 本地登录）均已端到端验证**。
- **职责边界**：CP 只负责锁屏 UI 与提交凭据；**所有摄像头采集、活体、识别都在 Python 服务里完成**，二者只靠本地命名管道 `\\.\pipe\FaceHello`（JSON）耦合。改 Python 不必重编 DLL。

---

## ⚠️ 安全提示

- **改了 C++ 代码后，再调试稳定之前，绝不要在你的主机上 `regsvr32` 注册本 DLL。** 只在**打了快照的 Windows 虚拟机**里注册测试。而如果修改了C++代码，再提交新代码前务必进行实机检验。
- 一个有缺陷的 Credential Provider 会让 LogonUI 异常，可能**进不去登录界面**。每次注册前先打快照、并留一个**备用管理员账户**。
- 本 CP **绝不替换 / 过滤**系统自带的密码 / PIN 提供程序——兜底登录方式始终保留。它只是**新增**一个磁贴。
- 出问题的恢复路径:VM 回滚快照 / 进安全模式 / 用另一个管理员账户登录后 `regsvr32 /u` 卸载（或手删下方两处注册表键）。

---

## 工作原理——解锁链路

```
选中「Face Unlock」磁贴
  → SetSelected 启后台扫描线程
  → PipeClient::AuthStart            （\\.\pipe\FaceHello，请求服务起一次认证）
  → 每 ~400ms PipeClient::AuthPoll   （取活体提示；SetFieldString 刷到磁贴状态文字）
  → 服务识别通过 → 缓存用户名 + SignalAutoLogon
  → CredentialsChanged → LogonUI 调 GetCredentialCount（pbAutoLogonWithDefault=TRUE）
  → LogonUI 自动调 GetSerialization
       → CredVault::RetrievePassword 从 LSA Secret 读该用户登录密码（CP 是 SYSTEM，可读）
       → KerbInteractiveUnlockLogon{Init,Pack} 打包 KERB 凭据
       → 交给 LogonUI 提交 → 真解锁
```

**要点**：
- **密码永不经过命名管道**。服务只回 `{ok, user, similarity}`；CP 自己在 SYSTEM 上下文读 LSA。
- **身份契约**：磁贴提交的账户名 == 服务返回的 `user` == LSA 键 `L$FaceHello_<user>` == 录入的 profile 名，四者必须一致解锁才成立。
- 只在 `CPUS_LOGON` 与 `CPUS_UNLOCK_WORKSTATION` 两个场景出磁贴，其余场景 `E_NOTIMPL` 不接管。

### 磁贴的两个可定制点

- **自定义头像**：把一张 PNG/JPG/BMP 放进 `C:\ProgramData\FaceHello\`，`GetBitmapValue` 用 WIC 读**第一张**图、按短边居中裁成正方形再缩放到 128×128；读不到 / 解码失败回退纯蓝占位图。该路径是纯 ASCII、SYSTEM 可读（CP 读不了 OneDrive / 中文路径）。
- **多语言**：CP 启动时读 `C:\ProgramData\FaceHello\lang.txt`（控制台改语言时写、服务以 SYSTEM 启动时同步），内容为 `en` 时磁贴标题 / 状态等**自有文案**走英文，否则中文。活体提示（「请向左转头」等）由 Python 服务**已按语言发来**，CP 原样显示。

> 运行前提:FaceHello 服务在跑 + 已写好该用户的 LSA 登录密码（都可在管理台「服务与凭据」页一键完成）。

---

## 构建

需要 Visual Studio 2022 +「使用 C++ 的桌面开发」工作负载。**用 PowerShell 编，别用 Bash**，实测MSYS 会损坏 `/p:` 参数。

```powershell
& "F:\VS2022\MSBuild\Current\Bin\MSBuild.exe" cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
```

- 产物：`cp\x64\Release\FaceHelloCP.dll`。
- 工程已设 `/MT`（静态链接 CRT），便于随安装包分发、不依赖 VC++ 运行库。

## 注册与卸载

`regsvr32` 调用 DLL 导出的 `DllRegisterServer` / `DllUnregisterServer`，各写 / 删两处注册表键:

```powershell
regsvr32 FaceHelloCP.dll        # 注册
regsvr32 /u FaceHelloCP.dll     # 卸载
```

| 写入位置 | 内容 |
|---|---|
| `HKCR\CLSID\{CLSID}` + `InprocServer32` | DLL 路径 + `ThreadingModel=Apartment` |
| `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{CLSID}` | 注册成 Credential Provider |

注册后 `Win+L` 锁屏或注销，应能看到「Face Unlock」磁贴。
> 正式安装时，Inno 安装器会自动 `regsvr32` 注册 / 卸载这块；此处手动命令仅供开发与排错。

---

## 文件

| 文件 | 作用 |
|------|------|
| `guid.h` | 本 CP 的 CLSID 定义 |
| `common.h` | 磁贴字段枚举（图标 / 标题 / 提交 / 状态）+ 共享声明 |
| `helpers.h` | 字段描述符深拷贝（`FieldDescriptorCoAllocCopy`） |
| `CFaceProvider.{h,cpp}` | `ICredentialProvider`：枚举出 1 个磁贴；`SignalAutoLogon` 触发自动提交 |
| `CFaceCredential.{h,cpp}` | `ICredentialProviderCredential`：后台扫描线程、状态刷新、头像 / 语言、`GetSerialization` 解锁 |
| `PipeClient.{h,cpp}` | 命名管道客户端（`AuthStart` / `AuthPoll`），管道忙 / 重建空窗时重试 |
| `CredVault.{h,cpp}` | 从 LSA Secret 读登录密码（`L$FaceHello_<user>`） |
| `KerbHelpers.{h,cpp}` | 打包 `KERB_INTERACTIVE_UNLOCK_LOGON` + 取 Negotiate 认证包 |
| `dll.cpp` | `DllMain` / 类工厂 / `DllRegisterServer` 等导出 + 注册表读写 |
| `FaceHelloCP.def` | 导出表（4 个标准 COM 导出） |
