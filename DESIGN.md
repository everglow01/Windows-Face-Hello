# Face_hello — Face Unlock for Windows with an Ordinary Webcam (Design Doc)

> [中文](./DESIGN_zh.md) ｜ Let an ordinary RGB webcam (laptop front camera / USB camera) that Windows Hello doesn't support unlock your PC by face.

This is the **design & decision record**: why it's built this way, where it stands now, and what's left. For end-user instructions see [README.md](./README.md); for dev setup, code map, and the gotcha list see [contribute.md](./contribute.md).

---

## 0. Status Overview

**The main path is wired up and shipped (latest `v0.1.2`):** lock-screen tile → named pipe → LocalSystem service → InsightFace recognition → read the LSA password → pack a KERB credential to really unlock. **Both local accounts and Microsoft accounts (MSA-backed local login) are verified end-to-end in a VM and on real hardware.** There's a one-click installer (Inno + Chinese wizard), a one-click clean uninstall, and automated GitHub Release distribution.

| Module | Status |
|--------|--------|
| Stages 1–4: Python recognition / liveness / enrollment / auth orchestration + PySide6 console | ✅ done |
| Stage 5: C++ Credential Provider lock-screen integration (tile → service → KERB unlock) | ✅ main path done, verified on real hardware |
| Local account + Microsoft account (MSA-backed) unlock | ✅ verified end-to-end |
| Live liveness prompts at the lock screen (`auth_start`/`auth_poll` async pair) | ✅ done |
| Custom lock-screen tile avatar (WIC reads `ProgramData`, falls back to solid blue) | ✅ done |
| Installed-mode / dev-mode path split (`.installed` marker + `FACEHELLO_HOME`) | ✅ done |
| Portable package (standalone CPython + deps) + Inno installer + Chinese wizard | ✅ done |
| One-click clean uninstall (stop/remove service, unregister CP, wipe LSA password + gallery) | ✅ done |
| Size trimming: PySide6-Essentials + buffalo_l pruning → `setup.exe` ~322 MB | ✅ done |
| GitHub Release automation (push a tag → CI builds setup.exe) | ✅ done |
| **5-4 hardening: pipe ACL limited to SYSTEM, failure fallback / lockout, better logging** | ⏳ to do |
| **Code signing (Authenticode / EV cert to clear SmartScreen)** | ⏳ tbd |
| Further slimming: opencv-headless, drop scipy/onnx transitive deps | ⏳ to do |
| Passive liveness (anti-spoof CNN), pytest test framework | ⏳ to do |

See [§7 Roadmap](#7-roadmap) for the full plan; remaining hardening is in [§9.2](#92-remaining-hardening-5-4) and [§10.5 Uninstall](#105-uninstall-completely-clean-red-line-no-broken-cp).

---

## 1. Background & Goal

Windows Hello face doesn't support ordinary webcams — not because the models aren't good enough, but because of **hardware- and framework-layer constraints**:

1. **Must be an IR (infrared) camera** — for anti-spoofing (photo / screen attacks) + low-light imaging.
2. **Must have a WBF driver** — the camera has to register as a "biometric sensor" through the Windows Biometric Framework for the system to accept it.
3. **Liveness detection** — IR + depth do this naturally; monocular RGB is weaker.

**Goal of this project**: use an ordinary RGB webcam + open-source deep-learning models to "unlock the PC by face," as a sign-in method **alongside** password / PIN (it never removes password login).

---

## 2. Route Choice

| Route | How it works | Pros | Cons | Verdict |
|-------|-------------|------|------|---------|
| **A. Credential Provider** | Implement an `ICredentialProvider` COM, add a custom sign-in method, and submit a credential to winlogon on a match | No IR hardware, no driver signing, free model choice | C++ COM is painful to debug; needs secure password storage | **Adopted** |
| B. WBDI biometric driver | Write a UMDF driver to disguise the camera as a Hello-compatible sensor (Sensor/Engine/Storage Adapter) | Native "Settings → Sign-in options → Face" integration | A step harder; needs driver signing; RGB likely rejected by IR/ESS policy | Dropped |

**Decision: take Route A.** First get the "recognition + liveness" pipeline working in Python, then build the C++ Credential Provider as the sign-in integration layer, with the two talking over local IPC (a named pipe). In practice this route panned out.

---

## 3. System Architecture (Route A)

```
┌──────────────────────────────────────────────────┐
│ Lock / sign-in screen (LogonUI, SYSTEM)            │
│  └─ FaceHello Credential Provider (C++ COM DLL)    │
│        │  ① auth_start / auth_poll                 │
│        ▼                                            │
│  Local IPC: named pipe \\.\pipe\FaceHello (JSON)    │
│        │                                            │
│        ▼                                            │
│  Face auth service (Python, LocalSystem, resident)  │
│   ├─ Camera capture (OpenCV, CAP_DSHOW)             │
│   ├─ Liveness  (MediaPipe FaceLandmarker: blink/turn)│
│   ├─ Recognition (InsightFace ArcFace, 512-d)       │
│   └─ Match vs gallery → return {ok, user, similarity}│
│        │                                            │
│        ▼  ② on match                               │
│  The CP reads the password from the LSA Secret in   │
│  the SYSTEM context and builds a                    │
│  KERB_INTERACTIVE_UNLOCK_LOGON to unlock            │
└──────────────────────────────────────────────────┘
```

**The two layers are deliberate:** the Python recognition stack can't be crammed into the LogonUI process, so it's split into "DLL handles UI / service handles the algorithm," coupled **only by the named-pipe protocol** — changing Python doesn't require recompiling the DLL. **The password never travels over IPC**: the service only returns `{ok, user, similarity}`; the CP reads the LSA itself in the SYSTEM context.

---

## 4. Model Choices

| Stage | Actually used | Notes |
|-------|--------------|-------|
| Face detection | InsightFace `det_10g` (buffalo_l) | Same package as recognition, `DET_SIZE=(320,320)` |
| Feature recognition | **ArcFace `w600k_r50`** (buffalo_l, 512-d) | onnxruntime CPU inference, high accuracy |
| Liveness | **Active**: blink (EAR) + head turn (solvePnP) random challenge | MediaPipe Tasks `FaceLandmarker`, 468 landmarks |

A passive anti-spoof CNN (trained on CASIA-SURF / replay) is listed as a **candidate defense-in-depth layer**, currently not enabled (see [§11](#11-lessons-from-a-similar-project-facewinunlock-tauri)).

---

## 5. Security Reality (important)

- A monocular RGB camera **inherently can't stop photo / video attacks** — exactly why Microsoft mandates IR.
- This approach is **weaker than native Hello**, and is basically unusable in low light.
- **Liveness is the floor**, otherwise a single photo unlocks the machine; don't disable it by default for "convenience."
- The password is stored in an LSA Secret and **never travels over IPC**; the gallery stores feature vectors (not photos), encrypted on disk with machine-scoped DPAPI.
- **Never remove the system's password / PIN provider** — a fallback sign-in must always remain. Register the CP / test on real hardware only after taking a snapshot + keeping a spare admin account + a system restore point.

---

## 6. Key Implementation Notes (settled during development)

> The operational gotcha list (non-ASCII paths, the ~40s `FaceLandmarker.close()` block, the SYSTEM-service font cache, etc.) lives in [contribute.md](./contribute.md); this section keeps only design-level decisions.

- **Liveness landmarks**: mediapipe 0.10.x removed the legacy `solutions`, so this uses the **Tasks API `FaceLandmarker`** (`RunningMode.VIDEO` + strictly increasing timestamps); the EAR / solvePnP logic downstream is unchanged.
- **Non-ASCII path workaround**: the working directory contains Chinese → mediapipe is fed bytes via `model_asset_buffer`, OpenCV uses `cv2.imdecode(np.fromfile(...))`; InsightFace/onnxruntime load `.onnx` with native Unicode support, fine.
- **Recognition perf tuning**: `FaceAnalysis(allowed_modules=["detection","recognition"])` runs only 2 models; a startup warmup really runs one sample image to move the cold-start cost to launch time. Measured single-face 640×480 recognition ≈ 250 ms.
- **Cold-start disk I/O**: deleted the unused `1k3d68/2d106/genderage` from buffalo_l, cold read 341 MB → 191 MB, no loss in recognition accuracy.

---

## 7. Roadmap

- [x] **Stage 1 — Python recognition prototype**: camera → detection → recognition (`camera/detector/matcher`).
- [x] **Stage 2 — Liveness**: blink (EAR) + head turn (solvePnP) active random challenge (`liveness`).
- [x] **Stage 3 — Enrollment / matching**: multi-frame averaged enrollment + DPAPI-encrypted gallery (`enroll/store`).
- [x] **Stage 4 — Auth orchestration + console**: `auth` state machine + PySide6 console (`app/`).
- [x] **Stage 5 — Credential Provider**: C++ COM lock-screen integration + LSA credential + KERB unlock. **Main path done, verified on real hardware** (see §9).
- [x] **Distribution — setup.exe**: portable package + Inno Chinese wizard + clean uninstall + Release automation, shipped as `v0.1.2` (see §10).
- [ ] **Hardening (5-4)**: pipe ACL limited to SYSTEM, failure fallback / lockout, better logging.
- [ ] **Pre-release**: code signing (EV cert to clear SmartScreen).
- [ ] **Optional enhancements**: passive liveness, GPU inference, pytest, further slimming.

---

## 8. Stage 5 Design Decisions (Credential Provider + service)

- **Not going real Hello (WBF driver)**: RGB is limited by IR/ESS policy and most likely can't register as an official Hello face, so it's dropped.
- **Credential storage = LSA Secret**: `face_hello/cred_vault.py`, key `L$FaceHello_<user>`, password as UTF-16LE. Writing / deleting needs **Administrator** (the console); reading needs **SYSTEM** (the lock-screen CP).
- **Who reads the password = the CP itself** (it's SYSTEM inside LogonUI). **The password never travels over IPC**; the service only returns `{ok, user, similarity}`.
- **Identity contract** (all four must match for unlock to succeed): profile name == `GetUserName()` (local SAM name) == LSA key `L$FaceHello_<user>` == KERB account name. Microsoft accounts go through MSA-backed local login, the same chain; the LSA key name can't contain a backslash.
- **Component split**:
  - ① Console (GUI, Administrator): enroll a face + write the sign-in password to an LSA Secret.
  - ② Auth service (resident, LocalSystem): camera + recognition + liveness, exposing `authenticate` / `auth_start` / `auth_poll` over the named pipe.
  - ③ Credential Provider (C++ COM): lock-screen tile → call ② → on success read the LSA → build `KERB_INTERACTIVE_UNLOCK_LOGON` and submit.

---

## 9. Stage 5 Implementation Log

### 9.1 Done (milestones a→d)

- [x] **Credential vault `cred_vault`** (LSA Secret read/write) + test CLI. Admin write → SYSTEM read verified.
- [x] **Service-ization**: named pipe `\\.\pipe\FaceHello`, **single-instance serial**, JSON messages; synchronous `ping`/`authenticate` + the async pair `auth_start`/`auth_poll` (the lock screen refreshes liveness prompts while recognizing). Self-tested with `scripts/auth_client.py`.
- [x] **C++ Credential Provider** (based on Microsoft's SampleV2CredentialProvider): tile enumeration, scan-thread polling, `SignalAutoLogon` auto-submit, `GetSerialization` reads the LSA → KERB unlock.
- [x] **Custom lock-screen tile avatar**: the CP uses WIC to read the first image (PNG/JPG/BMP) in `C:\ProgramData\FaceHello\`, scales it to 128×128, and falls back to a solid blue placeholder on failure.
- [x] **End-to-end verification**: VM (snapshotted) + real hardware, **both local and Microsoft accounts** unlock by face successfully. A SYSTEM/session-0 process can open the camera at the lock screen (the service can run as LocalSystem).

### 9.2 Remaining hardening (5-4)

- [ ] **Pipe ACL limited to SYSTEM**: currently the default ACL (creator + Administrators + SYSTEM can access); needs tightening to SYSTEM-only (so a local non-privileged process can't impersonate the CP and invoke auth). Code lives in `CreateNamedPipe` in `service.py`.
- [ ] **Failure fallback / lockout**: a consecutive-failure cap, and graceful degradation when the device is busy / the camera is unavailable, to avoid hanging the lock screen.
- [ ] **Better logging**: the service already writes `service.log`; needs structured, redacted auditing.

---

## 10. Distribution & Installer (setup.exe)

Goal: a single `setup.exe` (Inno Setup, admin privileges) that on a clean Win10/11 machine does, in one click, "lay down files → create the writable data dir → register and auto-start the service → register the CP DLL → drop a console shortcut," and can **uninstall completely cleanly** without ever leaving a broken LogonUI behind. **Implemented and shipped as `v0.1.2`.**

### 10.1 Key decisions (all landed)

- [x] **Python runtime = standalone CPython + deps shipped alongside** (not PyInstaller). Ship a python-build-standalone (same source as uv) + a pre-installed `site-packages`; the service / GUI run the source via an absolute path to `python.exe`. Rationale: the native data files of mediapipe / insightface / onnxruntime are preserved as-is, sidestepping freeze hooks and the pywin32-service freezing pitfalls.
- [x] **Models baked into the installer**: buffalo_l (det_10g + w600k_r50, ~191 MB) + face_landmarker.task (~3.7 MB) bundled, so the **first unlock doesn't depend on a network download**.
- [x] **Installed-mode / dev-mode split**: `config.py` switches on the **`.installed` marker file** at the install root (or `FACEHELLO_HOME`). A marker file rather than just an env var, because the SCM caches the system env block until the next reboot, so a freshly-installed service can't see a newly-set variable; a marker file lands on disk with the install, so the service / GUI are immediately consistent.
- [x] **Build the C++ DLL with `/MT` static CRT**: avoids a VC++ runtime dependency.
- [ ] **Code signing**: not done yet. `setup.exe` / the CP DLL will trigger a SmartScreen warning but the CP still loads. Signing is the final pre-release step (see §10.5).

### 10.2 Install Layout

```
C:\Program Files\FaceHello\          (read-only, program files)
  ├─ python\                         standalone CPython (incl. site-packages)
  ├─ app\  face_hello\               source (copied as-is)
  ├─ winservice_main.py  uninstall_cleanup.py
  ├─ FaceHelloCP.dll                 (/MT build, Release|x64)
  ├─ models\  buffalo_l\ + face_landmarker.task
  └─ .installed                      installed-mode marker (empty file)

C:\ProgramData\FaceHello\           (writable, runtime data; shared by SYSTEM and the elevated GUI)
  ├─ data\  faces.dat  service.log
  └─ <avatar>.png                   lock-screen tile avatar (read by the CP as SYSTEM)
```

Why data goes to ProgramData: Program Files is read-only for normal users, while the **enrollment GUI runs in the (elevated) user context and the service runs as LocalSystem** — both need to write `faces.dat` / logs. ProgramData is pure-ASCII and writable by both.

### 10.3 Prerequisite code changes (all done)

- [x] **`config.py` path split**: in installed mode `DATA_DIR` → `C:\ProgramData\FaceHello\data`, `MODELS_DIR` → `models\` under the install root; dev mode keeps repo-relative paths, not breaking the `uv run` flow.
- [x] **Service ImagePath absolute**: `winservice_main.py` install writes the ImagePath as a fully-qualified, quoted `python.exe ...winservice_main.py`, no longer depending on the venv / current directory. `MPLBACKEND=Agg` + `MPLCONFIGDIR` point at the ProgramData data dir.
- [x] **CP DLL avatar path**: the `C:\ProgramData\FaceHello\` hard-coded in `cp/CFaceCredential.cpp` matches `AVATAR_DIR`.

### 10.4 Build & distribution pipeline (implemented)

- [x] **Build the CP DLL**: `MSBuild cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64` (`/MT`).
- [x] **Portable package**: `scripts/build_release.py` — grab standalone CPython 3.11 → install the `dist` dependency group → slim → copy source + models + DLL + pywin32 runtime DLLs. Output defaults to `%LOCALAPPDATA%\FaceHello-build\FaceHello`.
- [x] **Inno compile**: `installer\FaceHello.iss` → `installer\Output\FaceHello-Setup-x.y.z.exe`. The `.iss`/`.isl` are **UTF-8 with BOM** (otherwise Chinese Windows reads them as GBK → mojibake). The Chinese wizard ships `ChineseSimplified.isl` in the repo (Inno has no built-in Chinese).
- [x] **CD automation**: `.github/workflows/release.yml` — pushing a `v*` tag triggers: prep models → build DLL + portable package → Inno builds setup.exe → upload to the GitHub Release. The version is injected from the tag, so `installer`/`pyproject` don't need manual edits.
- [ ] **Signing**: the final pre-release step, not done yet.

### 10.5 Uninstall (completely clean; red line: no broken CP)

The `[UninstallRun]` + `[UninstallDelete]` in `installer\FaceHello.iss` are implemented, ordered stop-service → unregister → delete files:

- [x] `winservice_main.py stop` → `regsvr32 /s /u FaceHelloCP.dll` (**unregister before deleting the DLL**, otherwise a registry remnant points at a non-existent DLL → LogonUI risk) → `winservice_main.py remove`.
- [x] **Completely clean**: `uninstall_cleanup.py` wipes the LSA sign-in password + deletes the gallery; `[UninstallDelete]` removes the ProgramData data dir and the runtime-generated files under the install dir (.pyc / .installed / service.log / avatar).
  > The uninstall policy was changed from the early "prompt the user to keep or delete" to **unconditionally wipe clean** (the user explicitly asked for "a completely clean uninstall").
- [x] Recovery path (documented): if the CP misbehaves, safe mode / another admin account `regsvr32 /u` / delete this CLSID key under HKLM Credential Providers.

### 10.6 Pre-release

- [x] Clean VM (snapshot) end-to-end: install → enroll → lock-screen unlock → uninstall clean, LogonUI normal.
- [x] Real-hardware end-to-end (local + Microsoft accounts).
- [ ] Authenticode-sign `setup.exe` + `FaceHelloCP.dll` + the embedded `python.exe` (EV cert to clear SmartScreen).
- [ ] Finishing the 5-4 hardening (pipe ACL, failure fallback, logging) is recommended before wider public distribution.

### 10.7 Install-path strategy (implemented)

- [x] The install directory is user-selectable (`DefaultDirName={autopf}\FaceHello`, changeable). The bulk (models + Python deps) follows the install dir, so **installing to D: leaves C: almost untouched**.
- ✅ Any **fixed internal NTFS drive** (C/D/E…).
- ❌ Forbidden: **removable / USB drives, network drives, BitLocker drives not auto-unlocked at boot** — the CP DLL has to load early at the lock screen (LogonUI/SYSTEM), and those drives may not be mounted yet → the tile fails to load.
- **The only thing fixed on C: is `C:\ProgramData\FaceHello\data`** (gallery + logs, tiny, tens of KB ~ a few MB).
- Space-in-path regression: `C:\Program Files\FaceHello` itself contains a space; the ImagePath is fully-qualified and quoted, and install/auto-start are verified in a VM and on real hardware (cf. the other project's issue #25 in §11).

### 10.8 Size: measurements & slimming

`setup.exe` measures **~322 MB** (`v0.1.x`), achieved by the following with no loss in recognition accuracy:

- [x] **PySide6 → PySide6-Essentials** (the `dist` dependency group): drops Addons, the biggest being `Qt6WebEngineCore.dll` (~196 MB); then manually delete `qml/`, non-zh/en `translations/`, `include/`, etc.
- [x] **buffalo_l pruning**: delete `1k3d68` (144 MB) / `2d106` / `genderage`, keep only det_10g + w600k_r50.
- [x] **Exclude `buffalo_l.zip`**: the pre-extraction raw archive (~281 MB) left over after insightface downloads; kept out of the package (otherwise setup.exe doubles to ~597 MB — a pitfall hit by CI's fresh download).
- [x] **General cleanup**: `__pycache__`, `tests/`.

**Optional further slimming (not done, low priority)**:
- [ ] **opencv-python → opencv-python-headless**: the dist group still uses `opencv-python`. Note mediapipe hard-depends on `opencv-contrib-python` (which also provides cv2), so a headless swap can't avoid both coexisting; needs separate hands-on trimming.
- [ ] **Drop transitive deps**: `scipy` (92 M), `onnx` (41 M, ≠ the `onnxruntime` needed at runtime). `skimage` almost certainly stays (insightface's face alignment uses `SimilarityTransform`, which drags in scipy); the `onnx` package (used for model building, inference relies only on onnxruntime) may be removable — verify with `offline_check.py` before touching it.

### 10.9 Risks now resolved

- [x] **pywin32 service viability on standalone CPython**: verified. `build_release.py` copies `pythoncomXX.dll`/`pywintypesXX.dll` to the python root, so the service (SYSTEM) can import `win32service`/`servicemanager` and be started by the SCM.
- [x] **GitHub Release asset experience**: the ~322 MB single file uploads / downloads fine, well under the 2 GB limit.

---

## 11. Lessons from a Similar Project (FaceWinUnlock-Tauri)

[FaceWinUnlock-Tauri](https://github.com/zs1083339604/FaceWinUnlock-Tauri) (Tauri+Vue3 GUI / Rust CP DLL / OpenCV recognition / SQLite credential store; core went closed-source from 2026-03) overlaps with this project in function. Distilled from its real user bug list:

- [x] **Space-in-path install**: their issue #25 was auto-start failing under a space-containing path. This project's service ImagePath is fully-qualified and quoted, and `C:\Program Files\FaceHello` (with a space) install/auto-start is regression-verified (see §10.7).
- [x] **Uninstall order corroborated**: their flow "uninstall core component first → then the main program, else a broken CP remains" matches this project's "stop service → `regsvr32 /u` → then delete."
- **Side evidence**: they also hit the OpenCV Chinese-directory problem, confirming the necessity of this project's `imdecode` / `model_asset_buffer` workarounds.

**Research item (undecided)**: they use a Tongyi RGB passive-liveness model (`cv_manual_face-liveness_flrgb`, threshold 0.6) instead of an active challenge, which feels smoother, but they admit its liveness accuracy was never tuned well. Could serve as this project's "low-friction mode" or a defense-in-depth candidate, lower priority than the existing active challenge.

> **Architecture-difference takeaway**: they send the **password in cleartext over the pipe** (their README admits the sniffing risk); this project's password **never crosses IPC** (the CP reads the LSA itself as SYSTEM); recognition with ArcFace 512-d beats their classic OpenCV features. On size, their Rust + system WebView2 is far smaller than this project's embedded Python, but that's not a reason to rewrite (see the §10.8 trade-off).

---

## 12. References

- **Howdy** on Linux (ordinary camera + PAM-like Hello face login) — recognition / liveness ideas worth borrowing.
- Microsoft's official sample `microsoft/Windows-classic-samples` → `SampleV2CredentialProvider` (Credential Provider skeleton).
- InsightFace: <https://github.com/deepinsight/insightface>
