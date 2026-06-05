# FaceHello Credential Provider（阶段 5-3，C++）

锁屏/登录界面上的「刷脸」磁贴。COM in-proc DLL，注册为 Windows Credential Provider。

- **CLSID**：`{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}`
- **当前进度：里程碑 a**（空磁贴）——能注册、登录/解锁界面能看到「Face Unlock」磁贴，点提交只弹占位提示，**不做任何认证、不提交任何凭据**。

## ⚠️ 安全红线

- **绝不在主机上 `regsvr32` 注册本 DLL。** 只在 **Windows 虚拟机（已打快照）**里注册测试。
- 一个有缺陷的 Credential Provider 可能让 LogonUI 异常，导致**登录界面进不去**。每次注册前先打快照。
- 本 CP **不替换/不过滤**系统自带的密码/PIN 提供程序，始终保留兜底登录方式。
- 出问题的恢复路径：VM 回滚快照 / 安全模式 / 另一个管理员账户登录后 `regsvr32 /u` 卸载或删注册表键。

## 构建（主机上做没问题，编译不等于注册）

需要 Visual Studio 2022 + “使用 C++ 的桌面开发”工作负载。

```powershell
# 用 VS 打开 cp\FaceHelloCP.sln，选 Release|x64 生成；或命令行：
& "F:\VS2022\MSBuild\Current\Bin\MSBuild.exe" cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
```

产物：`cp\x64\Release\FaceHelloCP.dll`。

## 在 VM 里注册 / 卸载（仅虚拟机！）

把 `FaceHelloCP.dll` 拷进 VM，**管理员**命令行：

```cmd
regsvr32 FaceHelloCP.dll        :: 注册（写 HKCR\CLSID 和 HKLM\...\Credential Providers）
regsvr32 /u FaceHelloCP.dll     :: 卸载
```

注册后锁屏（Win+L）或注销，应能看到蓝色磁贴「Face Unlock」。点它会显示占位提示——这就是里程碑 a 的预期结果。

## 文件

| 文件 | 作用 |
|------|------|
| `guid.h` | 本 CP 的 CLSID |
| `common.h` | 磁贴字段定义（图标/标题/提交/状态）+ 共享声明 |
| `helpers.h` | 字段描述符深拷贝辅助 |
| `CFaceProvider.{h,cpp}` | `ICredentialProvider`：枚举出 1 个磁贴 |
| `CFaceCredential.{h,cpp}` | `ICredentialProviderCredential`：磁贴字段 + 提交逻辑 |
| `dll.cpp` | DllMain / 类工厂 / `DllRegisterServer` 等导出 |
| `FaceHelloCP.def` | 导出表 |

## 后续里程碑

- **b**：接命名管道客户端，点磁贴调服务 `ping`，状态栏显示已录入用户（验证锁屏下 CP↔服务通信）。
- **c**：`GetSerialization` 里调 `authenticate` → 读 LSA Secret `L$FaceHello_<user>` 密码 → 打包 `KERB_INTERACTIVE_UNLOCK_LOGON` 真解锁。
- **d**：认证放到工作线程，识别时 UI 不卡；错误兜底。
