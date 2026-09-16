# Face Hello — Face Unlock for Windows with an Ordinary Webcam (Design Doc)

> [中文](./DESIGN_zh.md) ｜ Let an ordinary RGB webcam (laptop front camera / USB camera) that Windows Hello doesn't support unlock your PC by face.

This is the **design & decision record**: why it's built this way, where it stands now, and what's left. For end-user instructions see [README.md](./README.md); for dev setup, code map, and the gotcha list see [contribute.md](./contribute.md).

---

## 0. Status Overview

**The main path is wired up and in the formal release line:** lock-screen tile → named pipe → LocalSystem service → InsightFace recognition → read the LSA password → pack a KERB credential to really unlock. **Both local accounts and Microsoft accounts (MSA-backed local login) are verified end-to-end in a VM and on real hardware.** The project now has one-click install / clean uninstall, in-app updates, recoverable upgrades, and automated GitHub Release distribution.

| Module | Status |
|--------|--------|
| Stages 1–4: Python recognition / liveness / enrollment / auth orchestration + PySide6 console | ✅ done |
| Stage 5: C++ Credential Provider lock-screen integration (tile → service → KERB unlock) | ✅ main path done, verified on real hardware |
| Local account + Microsoft account (MSA-backed) unlock | ✅ verified end-to-end |
| Live liveness prompts at the lock screen (`auth_start`/`auth_poll` async pair) | ✅ done |
| Custom lock-screen tile avatar (WIC reads `ProgramData`, falls back to solid blue) | ✅ done |
| Lock-screen 3-attempt face retry (press "→" to retry), then fall back to password (CP-side) | ✅ done |
| Lock-screen auth starts only from "→" or the configured hotkey, not from tile preselection | ✅ done |
| Refreshed wide console UI + service / CP / model / camera diagnostics | ✅ done |
| Installed-mode / dev-mode path split (`.installed` marker + `FACEHELLO_HOME`) | ✅ done |
| Portable package (standalone CPython + deps) + Inno installer + Chinese wizard | ✅ done |
| One-click clean uninstall (stop/remove service, unregister CP, wipe LSA password + gallery) | ✅ done |
| Size trimming: PySide6-Essentials + buffalo_l pruning / FP16 recognition | ✅ `v1.0.5` setup: 260,924,312 bytes (~249 MiB) |
| GitHub Release automation (push a tag → CI builds setup.exe) | ✅ done |
| **5-4 hardening: pipe ACL (SYSTEM+Admins), CP server-identity verification, failure fallback / lockout, better logging, dev-only `authenticate`** | ✅ done (Python + CP, shipped in `v1.0.5`) |
| Face-unlock global switch + separate sign-in / workstation-unlock scopes | ✅ done (`v1.0.6`) |
| Console service-log view + redacted diagnostic ZIP export | ✅ done (`v1.0.6`) |
| Optional multi-person protection (off by default; reject before matching) | ✅ done (`v1.0.6`) |
| Bounded SCM service recovery (60s, 120s, then no action; 24h reset) | ✅ done (`v1.0.6`) |
| Sleep/resume acceptance | 🚧 short + long sleep passed; remaining hardware scenarios tracked |
| **Code signing: fixed personal self-signed certificate, signer pin, signed DLL / installer / uninstaller** | ✅ done; no official CA certificate planned |
| Further slimming: opencv-headless, drop scipy/onnx transitive deps | ⏳ to do |
| Passive anti-spoofing (Silent-Face MiniFASNet, default-on + fail-open if model missing) | ✅ done |
| Same-name multi-template enrollment ("Add angle" appends, unlock takes the max similarity, FIFO cap) | ✅ done |
| pytest for security logic (lockout / margin / anti-spoof gate / `authenticate` gating), wired into CI | ✅ done |

See [§7 Roadmap](#7-roadmap) for the full plan; hardening details are in [§9.2](#92-hardening-5-4-all-landed), and uninstall safety is in [§10.5](#105-uninstall-completely-clean-red-line-no-broken-cp).

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
│   ├─ Passive anti-spoofing (MiniFASNet)             │
│   ├─ Recognition (InsightFace ArcFace, 512-d)       │
│   └─ Optional multi-face gate + gallery match        │
│      → return {ok, user, similarity}                 │
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
| Active liveness | blink (EAR) + head turn (solvePnP) random challenge | MediaPipe Tasks `FaceLandmarker`, 468 landmarks |
| Passive anti-spoofing | **Silent-Face MiniFASNetV2** (`2.7_80x80`) detects screen/replay | bundles its own RetinaFace crop; default-on, can disable; fail-open if model missing |

Passive anti-spoofing is enabled (toggle in Settings): during recognition MiniFASNet **samples several frames** to reject screen/photo/video replays before matching — a sub-threshold score rejects at once, while a frame with no detected face is inconclusive and samples more, and only after `antispoof_max_frames` consecutive no-face frames does it fail-open (so a replay can't slip through on a single detection-miss frame). It covers the recorded-video replay that active liveness can't. Two gotchas: (1) MiniFASNet is extremely crop-sensitive, so it must use its companion RetinaFace box (InsightFace's tighter box misjudges); (2) input is BGR in [0,255] (the official ToTensor leaves `/255` commented out).

---

## 5. Security Reality (important)

- A monocular RGB camera **inherently can't stop photo / video attacks** — exactly why Microsoft mandates IR.
- This approach is **weaker than native Hello**, and is basically unusable in low light.
- **Liveness is the floor**, otherwise a single photo unlocks the machine; don't disable it by default for "convenience."
- The password is stored in an LSA Secret and **never travels over IPC**; the gallery stores feature vectors (not photos), encrypted on disk with machine-scoped DPAPI.
- **Never remove the system's password / PIN provider** — a fallback sign-in must always remain. Register the CP / test on real hardware only after taking a snapshot + keeping a spare admin account + a system restore point.
- **Multi-account anti-misrouting (margin)**: when several people enroll on one machine, they share a single gallery and threshold, and `best_match` returns the single most-similar template across the whole gallery — if two people's features are close, A can be matched as B and thus **unlock the wrong account** (an inherent monocular-RGB weakness). To guard against this, recognition adds a **margin check**: beyond `similarity ≥ match_threshold`, it also requires `best − most-similar-other-person ≥ match_margin` (default 0.05); if the two are too close it's judged "ambiguous identity" and rejected outright — better to fall back to the password than to risk unlocking the wrong account. With only one person enrolled there is no rival (margin = ∞) so it never triggers; the value is tunable on the Settings tab, and `match_margin = 0` disables it. Rivals are distinguished by profile name, so multiple templates of the same person don't compete with each other.
- **Optional multi-person protection**: when enabled, `AuthSession` counts detected faces before anti-spoofing and identity matching. Two or more faces cause an immediate biometric rejection, which consumes one of the CP tile's three attempts. It is off by default because bystanders, screens, posters, or distant faces can cause false rejections; when off, the existing largest-face behavior is unchanged.

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
- [x] **Stage 3 — Enrollment / matching**: multi-frame averaged enrollment + DPAPI-encrypted gallery (`enroll/store`); supports **same-name multi-template** ("Add angle" appends to cover different angles/lighting; unlock takes the max similarity over same-name templates, `max_templates_per_name` FIFO cap).
- [x] **Stage 4 — Auth orchestration + console**: `auth` state machine + PySide6 console (`app/`), including the refreshed wide UI and readiness diagnostics.
- [x] **Stage 5 — Credential Provider**: C++ COM lock-screen integration + LSA credential + KERB unlock. **Main path done, verified on real hardware** (see §9).
- [x] **Distribution — setup.exe**: portable package + Inno Chinese wizard + clean uninstall + Release automation shipped in the formal `v1.0.0` line; later releases added in-app updates, recoverable upgrades, and automatic installed-state acceptance (see §10).
- [x] **Hardening (5-4)**: pipe ACL (SYSTEM+Admins), CP-side LocalSystem server verification, failure fallback / lockout, better logging, and dev-only `authenticate`; completed and released in `v1.0.5`.
- [x] **Operational controls and diagnostics (`v1.0.6`)**: global + per-scenario face-unlock switches, console log view / redacted export, optional multi-person protection, and bounded SCM recovery.
- [x] **Code signing**: release DLL, installer, and uninstaller use the project's fixed personal self-signed certificate. The build pins its DER SHA-256 and requires the PFX from local storage or GitHub Secrets; no official CA certificate is planned (see SIGNING.md).
- [x] **Passive anti-spoofing**: Silent-Face MiniFASNet (`2.7_80x80`) + RetinaFace crop, multi-frame sampling during recognition to detect replays; default-on, can disable, fail-open if model missing.
- [ ] **Optional enhancements**: finish the remaining sleep/resume hardware matrix, GPU/NPU inference, lower-friction passive liveness, and further slimming.

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
- [x] **Service-ization**: named pipe `\\.\pipe\FaceHello`, **single-instance serial**, JSON messages; synchronous `ping`/`authenticate` (the latter bypasses lockout, so it's **dev-only** — rejected in installed mode) + the async pair `auth_start`/`auth_poll` (the lock screen refreshes liveness prompts while recognizing). Self-tested with `scripts/auth_client.py`.
- [x] **C++ Credential Provider** (based on Microsoft's SampleV2CredentialProvider): tile enumeration, scan-thread polling, `SignalAutoLogon` auto-submit, `GetSerialization` reads the LSA → KERB unlock.
- [x] **Custom lock-screen tile avatar**: the CP uses WIC to read the first image (PNG/JPG/BMP) in `C:\ProgramData\FaceHello\`, scales it to 128×128, and falls back to a solid blue placeholder on failure.
- [x] **Explicit auth start**: tile selection only shows the prompt; face auth starts from the "→" submit path or the optional single-key hotkey mirrored to `C:\ProgramData\FaceHello\hotkey.txt`.
- [x] **Lock-screen retry (post-d)**: on a failed scan the tile keeps the "→" submit button as a retry entry — up to 3 attempts (`kMaxFaceAttempts`, any failure counts), then it stops scanning and prompts the user to use their password. The Python service is unchanged (its own lockout, 5 fails / 30s, stays the brute-force gate; 3 < 5).
- [x] **End-to-end verification**: VM (snapshotted) + real hardware, **both local and Microsoft accounts** unlock by face successfully. A SYSTEM/session-0 process can open the camera at the lock screen (the service can run as LocalSystem). The 3-attempt retry is verified on real hardware.

### 9.2 Hardening (5-4, all landed)

- [x] **Pipe ACL + anti-squatting**: `CreateNamedPipe` in `service.py` now carries an explicit DACL allowing only **SYSTEM + Administrators** (the CP is SYSTEM so it can connect; admin-context GUI / `auth_client.py` testing still works, while local non-privileged processes can no longer impersonate the CP and invoke auth). It also sets `FILE_FLAG_FIRST_PIPE_INSTANCE`: if an instance of the name already exists, creation fails → we log a security warning + back off, never silently.
  - [x] **CP-side server identity verification (`v1.0.5`)**: after connecting, `PipeClient::Call` uses `GetNamedPipeServerProcessId`, opens the server process token, and requires its `TokenUser` to be LocalSystem (`S-1-5-18`). If the PID or token can't be verified, or the SID differs, the CP closes the pipe before sending any request and falls back to password / PIN. Snapshot-VM acceptance covered both the real LocalSystem service and a non-SYSTEM process squatting on the same pipe name.
- [x] **Failure fallback / lockout**: in-memory counting in `_AuthRunner` — **only genuine biometric rejections count** (mismatch / ambiguous identity / liveness failure / no face seen); infrastructure errors (not enrolled / camera unavailable / exception) don't. After `lockout_max_fails` (default 5) consecutive fails it cools down for `lockout_seconds` (default 30); during the cooldown `auth_start` returns "locked, use password" without opening the camera; a success or cooldown expiry resets it. Thresholds are tunable on the Settings tab (0 = off). The camera path's open timeout is cut from 30s to 8s (`authenticate_blocking(camera_timeout_s=8)`) so a missing/busy camera falls back to the password fast instead of stalling. The system password / PIN provider always remains as the inherent fallback.
- [x] **Better logging**: `service.py` adopts `logging` + `RotatingFileHandler` (`service.log`, ~1MB×3, with timestamps / levels), replacing bare `print`; in service mode a `_StreamToLogger` shim routes `sys.stdout/stderr` (native-lib prints and uncaught tracebacks) into the same rotating log (purely C-level stderr noise may not land — those are just startup banners, not audit content). **Passwords are never logged**; the username + similarity are (a local log, readable by SYSTEM / admins).
- [x] **Further hardening (post-v0.1.2)**: the sync `authenticate` command (which bypasses lockout) is now **dev-only**, rejected in installed mode, so the production pipe only exposes `ping` + `auth_start`/`auth_poll`; passive anti-spoofing **samples multiple frames** instead of one, so a replay can't slip through on a single detection-miss frame; the security state machines (lockout / margin / anti-spoof gate / `authenticate` gating) got **pytest** coverage wired into CI.

### 9.3 Operational controls and recovery (`v1.0.6`)

- [x] **Face-unlock scopes**: the console writes `C:\ProgramData\FaceHello\auth_scope.txt` as a one-byte bitmask (`0` off, `1` sign-in, `2` workstation unlock, `3` both). Missing or malformed data defaults to both scopes for upgrade compatibility. Windows 10+ commonly reports both startup/sign-out and `Win+L` as `CPUS_LOGON`, so the CP uses the current WTS session username to distinguish them; if the query fails while only one scope is enabled, it hides FaceHello rather than violating the configured scope. `CPUS_CREDUI` and UAC remain unsupported.
- [x] **Service-log diagnostics**: the console reads the latest 200 lines, reports modification time and WARNING / ERROR counts, opens the log directory, and exports a fixed-whitelist ZIP containing the report plus rotated logs. Export redacts usernames and credential-like assignments and never includes `faces.dat`, LSA Secrets, templates, or camera images.
- [x] **Bounded SCM recovery**: install/update configures restart after 60 seconds for the first abnormal stop, 120 seconds for the second, and an explicit final `SC_ACTION_NONE`; failures reset after 24 hours. `SERVICE_CONFIG_FAILURE_ACTIONS_FLAG` covers non-zero service stops from Python exceptions. A normal Administrator stop does not restart the service, and installed acceptance checks the exact policy.
- [x] **Sleep/resume evidence first**: short- and long-duration sleep passed hardware acceptance. Hibernation, lid-close, Fast Startup, camera contention, and post-Windows-Update recovery remain in `SLEEP_RESUME_ACCEPTANCE.md`; no power-event framework or unconditional tracker reset is added without a reproducible failure.

---

## 10. Distribution & Installer (setup.exe)

Goal: a single `setup.exe` (Inno Setup, admin privileges) that on a clean Win10/11 machine does, in one click, "lay down files → create the writable data dir → register and auto-start the service → register the CP DLL → drop a console shortcut," and can **uninstall completely cleanly** without ever leaving a broken LogonUI behind. **Implemented and included in `v1.0.0`.**

### 10.1 Key decisions (all landed)

- [x] **Python runtime = standalone CPython + deps shipped alongside** (not PyInstaller). Ship a python-build-standalone (same source as uv) + a pre-installed `site-packages`; the service / GUI run the source via an absolute path to `python.exe`. Rationale: the native data files of mediapipe / insightface / onnxruntime are preserved as-is, sidestepping freeze hooks and the pywin32-service freezing pitfalls.
- [x] **Models baked into the installer**: buffalo_l detection + the FP16-quantized w600k_r50 recognition model + face_landmarker.task are bundled, so the **first unlock doesn't depend on a network download**. Source/dev first-run download remains the pruned FP32 buffalo_l (~191 MB).
- [x] **Installed-mode / dev-mode split**: `config.py` switches on the **`.installed` marker file** at the install root (or `FACEHELLO_HOME`). A marker file rather than just an env var, because the SCM caches the system env block until the next reboot, so a freshly-installed service can't see a newly-set variable; a marker file lands on disk with the install, so the service / GUI are immediately consistent.
- [x] **Build the C++ DLL with `/MT` static CRT**: avoids a VC++ runtime dependency.
- [x] **Automatic installed-state acceptance**: `doctor.py` keeps its model / camera / pipe hardware check and can also capture a pre-install baseline containing only hashes, sizes, and counts. After repairing ProgramData ACLs but before changing the service or CP, the installer captures that baseline. Once the new service is ready, it verifies the release build, SCM auto-start, ImagePath and bounded recovery policy, pipe version / protocol, current-version CP DLL, `service.log`, face gallery, and system Credential Provider / Filter registration. Success deletes the temporary baseline; failure retains it and enters the old-payload / CP recovery path. The baseline contains no usernames, face embeddings, Windows passwords, or LSA Secrets.
- [x] **Shared service-health contract**: installer maintenance, console diagnostics, and `doctor.py` all use `probes.service_health` to distinguish not-ready, version mismatch, protocol mismatch, and malformed response states. Update checking likewise reports local-network, GitHub rate-limit / remote, manifest, disk, download-response, and hash / signature failures separately.
- [x] **In-app updates with recoverable upgrades**: the console handles explicit update checks, resumable downloads, and a second verification pass before launching the normal installer through UAC. There is no SYSTEM updater, silent installation, or automatic Windows restart. The manifest carries version, protocol, SHA-256, and signer constraints. Before an upgrade, Inno backs up the old payload; if post-install configuration or automatic acceptance fails, it restores the old files and CP before returning the service to its pre-upgrade state.
- [x] **Code signing**: tagged releases require the fixed personal self-signed PFX from GitHub Secrets. The workflow verifies the certificate's DER SHA-256 against `FACEHELLO_EXPECTED_SIGNER_SHA256`, signs the CP DLL, installer, and uninstaller, and verifies them before upload. The installer bundles only the public CER, checks it against the build-info signer pin, and establishes local trust after UAC approval. No official CA / Azure / EV certificate is planned; the private key remains local or in GitHub Secrets only (see SIGNING.md).

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
  ├─ lang.txt  hotkey.txt  auth_scope.txt  CP-readable console setting mirrors
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
- [x] **CD automation**: `.github/workflows/release.yml` — pushing a `v*` tag prepares / prunes / FP16-quantizes models, verifies the fixed signer pin, builds and signs the DLL + portable package + Inno installer / uninstaller, verifies them, then uploads the GitHub Release. The version is injected from the tag, so `installer`/`pyproject` don't need manual edits.
- [x] **Signing**: `build_release` signs the CP DLL via `FACEHELLO_SIGN_PFX`; Inno `/DSign` signs setup.exe + the uninstaller. Tagged CI releases require the PFX/password secrets, verify the fixed signer pin before building, delete the temporary PFX, and verify every signature before upload (see SIGNING.md).

### 10.5 Uninstall (completely clean; red line: no broken CP)

The `[UninstallRun]` + `[UninstallDelete]` in `installer\FaceHello.iss` are implemented, ordered stop-service → unregister → delete files:

- [x] `winservice_main.py stop` → `regsvr32 /s /u FaceHelloCP.dll` (**unregister before deleting the DLL**, otherwise a registry remnant points at a non-existent DLL → LogonUI risk) → `winservice_main.py remove`.
- [x] **Completely clean**: `uninstall_cleanup.py` wipes the LSA sign-in password + deletes the gallery; `[UninstallDelete]` removes the ProgramData data dir and the runtime-generated files under the install dir (.pyc / .installed / service.log / avatar).
  > The uninstall policy was changed from the early "prompt the user to keep or delete" to **unconditionally wipe clean** (the user explicitly asked for "a completely clean uninstall").
- [x] Recovery path (documented): if the CP misbehaves, safe mode / another admin account `regsvr32 /u` / delete this CLSID key under HKLM Credential Providers.

### 10.6 Pre-release

- [x] Clean VM (snapshot) end-to-end: install → enroll → lock-screen unlock → uninstall clean, LogonUI normal.
- [x] Real-hardware end-to-end (local + Microsoft accounts).
- [x] Authenticode-sign `setup.exe`, uninstaller, and `FaceHelloCP.dll` with the fixed personal self-signed certificate; the embedded `python.exe` remains signed by python.org and is not re-signed. First install can still show an unknown-publisher warning until the pinned public certificate is trusted locally.
- [x] **5-4 hardening complete**: pipe ACL, first-instance protection, CP-side LocalSystem server verification, failure fallback / lockout, production `authenticate` gating, and rotating logs are all landed; the final CP check shipped and passed VM acceptance in `v1.0.5`.

### 10.7 Install-path strategy (implemented)

- [x] The install directory is user-selectable (`DefaultDirName={autopf}\FaceHello`, changeable). The bulk (models + Python deps) follows the install dir, so **installing to D: leaves C: almost untouched**.
- ✅ Any **fixed internal NTFS drive** (C/D/E…).
- ❌ Forbidden: **removable / USB drives, network drives, BitLocker drives not auto-unlocked at boot** — the CP DLL has to load early at the lock screen (LogonUI/SYSTEM), and those drives may not be mounted yet → the tile fails to load.
- **The only thing fixed on C: is `C:\ProgramData\FaceHello\data`** (gallery + logs, tiny, tens of KB ~ a few MB).
- Space-in-path regression: `C:\Program Files\FaceHello` itself contains a space; the ImagePath is fully-qualified and quoted, and install/auto-start are verified in a VM and on real hardware (cf. the other project's issue #25 in §11).

### 10.8 Size: measurements & slimming

The published `v1.0.5` installer is **260,924,312 bytes (~249 MiB)**. The main reductions are:

- [x] **PySide6 → PySide6-Essentials** (the `dist` dependency group): drops Addons, the biggest being `Qt6WebEngineCore.dll` (~196 MB); then manually delete `qml/`, non-zh/en `translations/`, `include/`, etc.
- [x] **buffalo_l pruning + FP16 recognition**: delete `1k3d68` (144 MB) / `2d106` / `genderage`, keep det_10g + w600k_r50, then convert `w600k_r50` from FP32 (~174 MB) to FP16 (~87 MB) in release CI. Local conversion may retain `w600k_r50.fp32.bak` for rollback; `build_release.py` excludes `*.bak` from packages.
- [x] **Exclude `buffalo_l.zip`**: the pre-extraction raw archive (~281 MB) left over after insightface downloads; kept out of the package (otherwise setup.exe doubles to ~597 MB — a pitfall hit by CI's fresh download).
- [x] **General cleanup**: `__pycache__`, `tests/`.

**Optional further slimming (not done, low priority)**:
- [ ] **opencv-python → opencv-python-headless**: the dist group still uses `opencv-python`. Note mediapipe hard-depends on `opencv-contrib-python` (which also provides cv2), so a headless swap can't avoid both coexisting; needs separate hands-on trimming.
- [ ] **Drop transitive deps**: `scipy` (92 M), `onnx` (41 M, ≠ the `onnxruntime` needed at runtime). `skimage` almost certainly stays (insightface's face alignment uses `SimilarityTransform`, which drags in scipy); the `onnx` package (used for model building, inference relies only on onnxruntime) may be removable — verify with `offline_check.py` before touching it.

### 10.9 Risks now resolved

- [x] **pywin32 service viability on standalone CPython**: verified. `build_release.py` copies `pythoncomXX.dll`/`pywintypesXX.dll` to the python root, so the service (SYSTEM) can import `win32service`/`servicemanager` and be started by the SCM.
- [x] **GitHub Release asset experience**: the current ~249 MiB installer uploads / downloads normally, well under the 2 GB limit.

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
