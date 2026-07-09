# FaceHello Credential Provider (C++)

The "Face Unlock" tile on the lock / sign-in screen. A COM in-proc DLL registered as a Windows Credential Provider; selecting the tile shows the prompt, and pressing "→" or the configured hotkey starts face recognition. Once recognized, it **submits the real credential to actually sign in / unlock**.

> [中文](./README_zh.md) ｜ Overall design: [DESIGN.md](../DESIGN.md), developer guide: [contribute.md](../contribute.md)

- **CLSID**: `{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}`
- **Status**: tile → named pipe → LocalSystem service → InsightFace recognition → read the LSA password → pack a Kerberos credential to actually unlock. **Both local accounts and Microsoft accounts (MSA local login) are verified end-to-end.**
- **Boundary of responsibility**: the CP only handles the lock-screen UI and credential submission; **all camera capture, liveness, and recognition happen in the Python service**. The two are coupled only through the local named pipe `\\.\pipe\FaceHello` (JSON). Changing the Python side does not require rebuilding the DLL.

---

## ⚠️ Safety notice

- **After editing the C++ code, never `regsvr32`-register this DLL on your host machine until it's debugged and stable.** Register and test only inside a **snapshotted Windows VM**. And if you've changed the C++ code, always validate on real hardware before committing the new code.
- A buggy Credential Provider can break LogonUI and potentially **lock you out of the sign-in screen**. Take a snapshot before every registration, and keep a **spare administrator account**.
- This CP **never replaces or filters** the system's built-in password / PIN providers — the fallback login is always there. It only **adds** a tile.
- Recovery paths when things go wrong: roll back the VM snapshot / boot into Safe Mode / sign in with another administrator account and `regsvr32 /u` to unregister (or manually delete the two registry keys listed below).

---

## How it works — the unlock chain

```
Select the "Face Unlock" tile
  → SetSelected shows the prompt
  → press "→" or the configured hotkey to start the background scan thread
  → PipeClient::AuthStart            (\\.\pipe\FaceHello, asks the service to run one auth)
  → PipeClient::AuthPoll every ~400ms (fetch the liveness prompt; SetFieldString pushes it to the tile's status text)
  → service recognizes the face → cache the username + SignalAutoLogon
  → CredentialsChanged → LogonUI calls GetCredentialCount (pbAutoLogonWithDefault=TRUE)
  → LogonUI calls GetSerialization automatically
       → CredVault::RetrievePassword reads the user's sign-in password from the LSA Secret (the CP is SYSTEM, so it can)
       → KerbInteractiveUnlockLogon{Init,Pack} packs the KERB credential
       → handed to LogonUI to submit → actual unlock
```

**Key points**:
- **The password never travels over the named pipe.** The service only returns `{ok, user, similarity}`; the CP reads the LSA itself in the SYSTEM context.
- **Identity contract**: the account name the tile submits == the `user` the service returns == the LSA key `L$FaceHello_<user>` == the enrolled profile name. All four must match for the unlock to succeed.
- The tile is shown only in the `CPUS_LOGON` and `CPUS_UNLOCK_WORKSTATION` scenarios; for all others it returns `E_NOTIMPL` and does not take over.

### Customizable parts of the tile

- **Custom avatar**: drop a PNG/JPG/BMP into `C:\ProgramData\FaceHello\`. `GetBitmapValue` uses WIC to read the **first** image, center-crops it to a square by the shorter side, then scales it to 128×128; if nothing is found or decoding fails, it falls back to a solid-blue placeholder. That path is pure ASCII and SYSTEM-readable (the CP can't read OneDrive / non-ASCII paths).
- **Multi-language**: at startup the CP reads `C:\ProgramData\FaceHello\lang.txt` (written by the console when you change language, and synced by the service as SYSTEM on startup). When its content is `en`, the tile's **own text** (title, status, etc.) is English, otherwise Chinese. The liveness prompts ("Turn your head left", etc.) arrive **already localized from the Python service**, and the CP displays them as-is.
- **Face unlock hotkey**: at startup the CP reads `C:\ProgramData\FaceHello\hotkey.txt` (written by the console Settings page). Supported values are `SPACE`, `ENTER`, one letter, or one digit; empty means only "→" starts scanning.

> Prerequisites: the FaceHello service is running, and the user's LSA sign-in password has been set (both can be done on the console's "Service, credentials & diagnostics" page).

---

## Build

Requires Visual Studio 2022 with the "Desktop development with C++" workload. **Build with PowerShell, not Bash** — in practice MSYS mangles the `/p:` arguments.

```powershell
& "F:\VS2022\MSBuild\Current\Bin\MSBuild.exe" cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
```

- Output: `cp\x64\Release\FaceHelloCP.dll`.
- The project is set to `/MT` (statically linked CRT), so it ships with the installer without depending on the VC++ runtime.

## Register & unregister

`regsvr32` calls the DLL's exported `DllRegisterServer` / `DllUnregisterServer`, which write / delete two registry keys each:

```powershell
regsvr32 FaceHelloCP.dll        # register
regsvr32 /u FaceHelloCP.dll     # unregister
```

| Location | Contents |
|---|---|
| `HKCR\CLSID\{CLSID}` + `InprocServer32` | DLL path + `ThreadingModel=Apartment` |
| `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{CLSID}` | registers it as a Credential Provider |

After registering, lock with `Win+L` or sign out, and you should see the "Face Unlock" tile.
> For a real install, the Inno installer registers / unregisters this automatically; the manual commands here are only for development and troubleshooting.

---

## Files

| File | Purpose |
|------|---------|
| `guid.h` | the CP's CLSID definition |
| `common.h` | tile field enum (image / label / submit / status) + shared declarations |
| `helpers.h` | deep-copy of field descriptors (`FieldDescriptorCoAllocCopy`) |
| `CFaceProvider.{h,cpp}` | `ICredentialProvider`: enumerates one tile; `SignalAutoLogon` triggers auto-submit |
| `CFaceCredential.{h,cpp}` | `ICredentialProviderCredential`: explicit scan start, optional hotkey listener, status refresh, avatar / language, `GetSerialization` unlock |
| `PipeClient.{h,cpp}` | named-pipe client (`AuthStart` / `AuthPoll`), retries when the pipe is busy / during the rebuild gap |
| `CredVault.{h,cpp}` | reads the sign-in password from the LSA Secret (`L$FaceHello_<user>`) |
| `KerbHelpers.{h,cpp}` | packs `KERB_INTERACTIVE_UNLOCK_LOGON` + retrieves the Negotiate auth package |
| `dll.cpp` | `DllMain` / class factory / `DllRegisterServer` and other exports + registry read/write |
| `FaceHelloCP.def` | export table (4 standard COM exports) |
