# 代码签名

给 `FaceHelloCP.dll` 与 `FaceHello-Setup-*.exe` 加数字签名。**当前阶段:自签名,用于在开发机 / VM 端到端验证签名管道。**

## 这件事的定位

- CP DLL **不签名也能加载**(Windows 对 Credential Provider 无强制签名门槛,这跟需要 WHQL/EV 的 Windows Hello 生物驱动是两回事)。签名是为了**去掉 setup.exe 的 SmartScreen「未知发布者」警告、降杀软误报、显得正规**。
- **自签名只在「装了这张根证书的机器」上可信**,不能消除别人下载时的 SmartScreen 警告。要真实分发,换 **Azure Trusted Signing** 或 **EV 证书**即可——下面的管道(env 变量 + Inno `SignTool`)不用重搭,只换证书来源。
- ⚠️ 2023-06 起公共 CA 的 OV/EV 证书私钥必须在硬件令牌 / 云 HSM 上,**不再有可下载的 .pfx**。所以真实证书阶段走的是「云签 / 令牌签」,不是把 pfx 丢进 CI。

## 一次性:生成自签名证书

```powershell
# 管理员终端(-Trust 要写本机信任库)。产出 scripts\sign\out\FaceHello-Dev.{pfx,cer}
powershell -ExecutionPolicy Bypass -File scripts\sign\setup_selfsigned.ps1 -Trust
```

`out\` 与 `*.pfx` 已被 `.gitignore` 忽略,**私钥绝不入库**。在另一台测试 VM 上要让签名校验通过,把 `FaceHello-Dev.cer` 拷过去装进信任库:

```powershell
Import-Certificate -FilePath FaceHello-Dev.cer -CertStoreLocation Cert:\LocalMachine\Root
Import-Certificate -FilePath FaceHello-Dev.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
```

## 签 DLL —— 跟着构建走

`build_release.py` 在编完 DLL 后会**按 env 变量决定是否签名**(没设就跳过,无证书构建不受影响):

```powershell
$env:FACEHELLO_SIGN_PFX  = "$PWD\scripts\sign\out\FaceHello-Dev.pfx"
$env:FACEHELLO_SIGN_PASS = "facehello"
uv run python scripts/build_release.py     # DLL 被签 + verify;打进包里的就是签名版
```

可选 env:`FACEHELLO_SIGN_TS`(时间戳服务器,默认 `http://timestamp.digicert.com`)、`SIGNTOOL`(覆盖 signtool.exe 路径,默认从 Windows SDK 自动找)。

单独签 / 重签某个文件:

```powershell
signtool sign /fd SHA256 /f scripts\sign\out\FaceHello-Dev.pfx /p facehello `
  /tr http://timestamp.digicert.com /td SHA256 cp\x64\Release\FaceHelloCP.dll
signtool verify /pa /v cp\x64\Release\FaceHelloCP.dll
```

## 签安装器 —— 交给 Inno

`FaceHello.iss` 里 `SignTool`/`SignedUninstaller` 用 `#ifdef Sign` 门控。编译时加 `/DSign` 并用 `/Sfacehello=<命令>` 提供签名命令(`$f` 是 Inno 注入的待签文件占位符),即对 **setup.exe 与卸载器**都签名:

```powershell
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
$build = "$env:LOCALAPPDATA\FaceHello-build\FaceHello"
$pfx = "$PWD\scripts\sign\out\FaceHello-Dev.pfx"
& $iscc /DSign `
  "/Sfacehello=signtool sign /fd sha256 /f $pfx /p facehello /tr http://timestamp.digicert.com /td sha256 `$f" `
  "/DMyAppVersion=0.1.0" "/DBuildDir=$build" installer\FaceHello.iss
```

不传 `/DSign` 就是原来的无签名构建。

## 验证

```powershell
signtool verify /pa /v cp\x64\Release\FaceHelloCP.dll
signtool verify /pa /v installer\Output\FaceHello-Setup-0.1.0.exe
# 或右键文件 → 属性 → 数字签名 选项卡
```

时间戳(`/tr`)很重要:有它,**证书过期后**已签的文件仍被认为「签名时有效」。

## 之后换真实证书

把上面 `FACEHELLO_SIGN_PFX`/`/Sfacehello=...` 里的 pfx 换成正式签名方式即可:

- **Azure Trusted Signing**(~$10/月,无令牌,有官方 GitHub Action):在 `release.yml` 里加 `azure/trusted-signing-action`,对 build 产出的 DLL 与 setup.exe 签名;个人订阅需先在 Azure 通过身份资格审核。
- **EV 证书**(即时 SmartScreen 信誉):私钥在硬件令牌上,通常在本机插着令牌手动 `signtool sign`(`/n "<主体名>"` 走证书库,而非 `/f pfx`),CI 云签较难。
