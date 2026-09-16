<div align="center">



![logo](README_image/facehello-wordmark.svg)

*Bringing Windows Hello-style face unlock to laptops, desktop front cameras, and USB cameras that Windows Hello doesn't support.*

*Inspired by a Surface Pro 4 the author once owned~*

<br>

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-D22128?logo=apache&logoColor=white)](./LICENSE)
[![Recognition](https://img.shields.io/badge/Recognition-InsightFace%20ArcFace-FF6F00)](https://github.com/deepinsight/insightface)
[![Liveness](https://img.shields.io/badge/Liveness-MediaPipe-00BFA5?logo=google&logoColor=white)](https://developers.google.com/mediapipe)

**[🇨🇳 中文](./README_zh.md)**　｜　**[📐 Design & Decisions](./DESIGN.md)**

</div>

---

## ⚠️ Safety Notice (read before use)

- This project is only meant for **Windows 10 / 11**; using it on any other OS is not recommended.
- It touches system-affecting operations like modifying Windows services. The author has added plenty of safeguards and validated it on real hardware, but there's still a chance of serious system problems like **being unable to sign in, a service crash, or a BSOD**. The odds are very small, but be aware.
- This project uses vision algorithms like OpenCV to do single-RGB-camera face unlock — i.e. **Windows Hello-like** — but the actual security is far below the real Windows Hello. A single RGB camera can't sense spatial information the way infrared / depth cameras can, and may well be bypassed by a high-quality video or photo. **Do not use this on a work computer that stores sensitive data** — the risk is significant, and you bear the consequences of any major loss yourself.
- The vision recognition runs onnx-model inference on the CPU, which puts some demand on your hardware. From testing, a CPU with fewer than 4 cores is not recommended — inference latency rises noticeably, defeating the fast-unlock spirit of the original Windows Hello.

---  

## 💽Cloud Drive Distribution

Quark Cloud Drive:    
Link: https://pan.quark.cn/s/db1464cf9c2d?pwd=afnw    
Extraction Code: afnw    

---  

## 📋 Requirements

- **Windows 10 / 11 (x64)**
- A working **RGB webcam**
- **A 4-core-or-better CPU**: recognition runs onnx inference on the CPU, and with too few cores unlock latency rises noticeably, defeating the point of a fast unlock
- Some advanced actions (writing the LSA password, installing the service) need an **Administrator** terminal (PowerShell)

---

## 🚀 Install & Use (recommended: the one-click installer)

Regular users don't need Python / uv — just grab the installer from the Release page:

1. Download the latest `FaceHello-Setup-x.y.z.exe` from [Releases](https://github.com/everglow01/Windows-Face-Hello/releases).
2. Right-click **Run as administrator** and complete the wizard. The installer registers the background authentication service and lock-screen Credential Provider, then creates the data directory. Before finishing, it also checks the service, its bounded SCM recovery policy, pipe, current-version DLL, log, and face gallery; a failed acceptance check does not silently complete the install.
3. Once installed, open the "FaceHello Console" from the Start menu or desktop (use admin privileges the first time), enroll your face, set your sign-in password, and you can unlock by face at the lock screen.

> Release builds use the project's personal self-signed certificate. On first install, Windows can still warn about an unknown publisher. After UAC approval, the installer verifies the bundled public certificate against the pinned signer hash before adding it to the local trust stores. The PFX private key is never included in the repository, installer, artifacts, or GitHub Release.

> The recognition models are all bundled in the installer, so installation does not download them.
>
> Later releases can be installed through the console's update check. Downloads can resume after interruption, and FaceHello rechecks the release metadata, SHA-256, and signature before launching the installer. Upgrades preserve the face gallery and compare the relevant data and Windows sign-in components before and after the upgrade. If configuration or acceptance fails, the installer attempts to restore the previous version. Installation is never silent and never restarts Windows automatically.

**Uninstall**: uninstall via Windows "Settings → Apps" or "Uninstall FaceHello" in the Start menu. The uninstall removes both the program and all local data, leaving no leftover files behind.

---

## 🛠️ Dev Environment

If you want to run the console and service from source, or contribute:

- **Python 3.11** (the project requires `>=3.10,<3.12`)
- [**uv**](https://docs.astral.sh/uv/) (package / virtualenv management)

```powershell
git clone https://github.com/everglow01/Windows-Face-Hello.git
cd Windows-Face-Hello

uv sync                                   # create .venv and install deps (not the base env)
uv run python scripts/offline_check.py    # offline self-check (no camera/display needed); all [ok] = good
uv run python -m app.main                 # launch the console GUI (must use admin privileges on first use)
```

> On first run, models auto-download to `models/`: InsightFace `buffalo_l` (recognition + detection, ~191 MB) and MediaPipe `face_landmarker.task` (liveness, ~3.7 MB).

For detailed developer docs and a contribution guide, see [contribute.md](./contribute.md).

---

## 🖥️ Using the Console

Launch the installed app with admin privileges to enter the console desktop app. On first show, the window expands to fit its content; you can still resize it from any edge or corner, and camera previews keep their aspect ratio as the window changes:

![GUI](README_image/GUI.png)

1. **Enroll** — the username defaults to your current Windows account name (the text shown on the lock screen); face the camera to collect several good frames, averaged into a template. The enrolled-users list (view / delete) lives on this tab.
   > The username must equal your Windows sign-in account name, otherwise lock-screen unlock won't match (Microsoft accounts use the local login name).
   > Not sure of your account name? Press Win+L to see the name shown on the lock screen — it's usually the same.
   > 💡 **Tip: enroll more than one template per user.** After the first "Start enrolling", change the **angle, lighting, makeup / hairstyle, glasses on/off**, etc., and click **"Add angle"** to append another template (one username can hold several; unlock automatically takes the most similar one). Enrolling **2+ templates** noticeably improves the unlock success rate across scenarios and reduces occasional misses. The per-user cap is adjustable on the Settings tab.
2. **Test unlock** — follow the random liveness prompt (blink N times / turn left / turn right), then recognition runs and shows the similarity and result.
3. **Settings** — pick the camera (with a **Test** button that previews the selected one, handy on multi-camera machines); tune the match threshold, turn angle, blink count, and recommended re-enrollment interval; toggle **liveness** and **passive anti-spoofing**. You can also pause FaceHello without deleting data, enable it separately for Windows sign-in and workstation unlock (`Win+L`), and optionally reject authentication when multiple faces are visible. Multi-person protection is off by default. Reaching the re-enrollment date only shows a reminder—the template still works for authentication.
4. **Service, credentials & diagnostics** — set the sign-in password used for lock-screen unlock (written to an LSA Secret), install / start / stop the authentication service, and check its version, pipe protocol, and runtime state. The page can show the latest 200 service-log lines, open the log folder, and export a redacted diagnostic ZIP. **Requires Administrator**, otherwise the relevant buttons are disabled.

*Some stutter on the first enrollment and test is normal.*

*The bottom-right of the GUI shows model-loading status; it's recommended to wait until the models finish loading before enrolling and testing.*

To calibrate liveness thresholds (live EAR / yaw display, prints suggested values on exit):

```powershell
uv run python -m scripts.liveness_tune
```

---

## 🔓 How Lock-screen Unlock Works

Full unlock chain: lock-screen "Face Unlock" tile → (named pipe) → LocalSystem service → InsightFace recognition → read the password saved in the LSA → pack a Kerberos credential to actually unlock. Both local accounts and Microsoft accounts (MSA local login) are verified end-to-end. **Fully validated and working on the author's physical machine.**

The global face-unlock switch and the two scenario switches control whether the tile appears for startup/sign-out or workstation unlock. Closing a switch only hides FaceHello in that scope; it does not delete enrolled templates, settings, or the LSA credential. Windows 10 and later can report both situations as `CPUS_LOGON`, so the provider also checks whether the current WTS session already has a signed-in user. If that state cannot be determined while only one scope is enabled, FaceHello stays hidden rather than ignoring the user's choice.

> If a face check fails, press the tile's **→** button to try again — you get **3 attempts**, after which Face Hello falls back to password sign-in (the system password / PIN is always available).

Auth service commands (Administrator; `<venv>` = `.venv\Scripts\python.exe`):

```powershell
<venv> winservice_main.py install --startup auto   # register the service, auto-start at boot
<venv> winservice_main.py start | stop | remove     # start / stop / remove
```

You normally don't need to run these by hand — the GUI above can install and start everything in one click; these are for dev/debugging. The installer also configures bounded SCM recovery: restart 60 seconds after the first abnormal stop, 120 seconds after the second, then stop retrying. The count resets after 24 hours. A normal Administrator stop does not restart the service.

If you're developing from source and want to build the C++ Credential Provider (CP) for the lock-screen tile yourself, you'll need VS2022 with "Desktop development with C++", and **build with PowerShell, not Bash** (MSYS mangles the `/p:` arguments):

```powershell
MSBuild.exe cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
# Output: cp\x64\Release\FaceHelloCP.dll, then register it with regsvr32
```

> ⚠️ Before registering the CP or testing on real hardware, **always** take a system restore point or VM snapshot and keep a spare admin account. This project **never** replaces the system's built-in password / PIN sign-in — the fallback login is always there. More build and troubleshooting details are in [cp/README.md](./cp/README.md).

(Regular users of the one-click installer don't need this step — the DLL is already built and bundled.)

---

## ⚙️ How It Works (in brief)

```
Camera (OpenCV) → Active liveness (MediaPipe FaceLandmarker: EAR blink + solvePnP head turn)
               → Face detection + recognition (InsightFace SCRFD + ArcFace, 512-d embedding)
               → Passive anti-spoofing (Silent-Face MiniFASNet: reject screen / photo / video replay)
               → Cosine similarity vs gallery → pass / reject
```

- The `face_hello/` core library has no GUI dependency and is shared by the console, the service, and scripts.
- At the lock screen, recognition runs in a resident LocalSystem service; the C++ Credential Provider only handles the UI and submits the credential. The two communicate over a local named pipe.

---

## 🖼️ Custom Lock-screen Avatar

You can drop your own avatar image into the default path `C:\ProgramData\FaceHello`. The program takes the **first** image in that directory, scales and crops it to a square, and places it on the lock-screen tile; newer Windows displays it as a circle automatically.

- Supports **PNG / JPG / BMP**; a square image is recommended so the edges aren't cropped.
- A pure-ASCII path — the Credential Provider running as SYSTEM at the lock screen can read it (it can't access OneDrive / Chinese paths).
- If no image is found or decoding fails, the tile falls back to the default solid-blue placeholder without affecting unlock.

![avatar](README_image/touxiang.png)

## 🔐 Security & Privacy

- The gallery stores **feature vectors, not photos**, encrypted on disk with Windows DPAPI in the local `data/` and never uploaded. Its versioned format is validated when loaded and written via atomic replacement to reduce corruption if a save is interrupted.
- The sign-in password is kept in an **LSA Secret**, read by the Credential Provider itself in the SYSTEM context — it **never travels over IPC**.
- **Passive anti-spoofing** (Silent-Face MiniFASNet) samples several frames during recognition to reject screen / photo / video replays — on by default, with a toggle in Settings. It meaningfully raises the bar, but being single-RGB it is **not** foolproof.
- Optional **multi-person protection** rejects the attempt before identity matching when two or more faces are detected. It is off by default because people in the background, screens, posters, or distant faces can cause false rejections. When enabled, a multi-face rejection consumes one of the tile's three face attempts.
- Diagnostic export uses a fixed whitelist: the diagnostic report and rotated service logs only. Usernames and credential-like assignments are redacted; `faces.dat`, passwords, LSA Secrets, templates, and raw camera images are excluded.
- Even with active liveness + passive anti-spoofing, monocular RGB still can't match IR / depth. **Don't use this on a machine others might physically access.** Any data leak or loss is the result of the user's own operation and of not understanding this project's risks, and you bear the consequences yourself.
- With **liveness** turned off, startup compresses to under 1s for an almost-instant experience — but for safety we still don't recommend turning it off.

---

## 📂 Project Layout

```
face_hello/        core library (no Qt dependency)
  camera.py          camera capture (with cold-boot / wake retries)
  detector.py        InsightFace detection + 512-d embedding
  matcher.py         cosine-similarity matching
  liveness.py        FaceLandmarker → EAR blink + solvePnP turn + random challenge
  antispoof.py       passive anti-spoofing (MiniFASNet + RetinaFace crop)
  enroll.py          multi-frame averaged enrollment
  store.py           DPAPI-encrypted gallery + settings
  auth.py            auth orchestration (liveness → recognition) state machine
  service.py         named-pipe auth server
  win_service.py     LocalSystem service wrapper + bounded SCM recovery policy
  diagnostics.py     service-log view + redacted diagnostic ZIP export
  probes.py          shared service / pipe / model / camera health probes
  updater.py         update manifest, resumable download, and verification
  cred_vault.py      LSA Secret read/write (sign-in password)
app/               PySide6 console (main.py + background workers.py)
cp/                C++ Credential Provider (lock-screen tile, needs VS to build)
scripts/           offline_check.py and other tooling
data/              encrypted gallery (gitignored)
models/            model weights (gitignored)
```

---

## 🚧 Known Limitations

- Anti-spoofing: a passive model (MiniFASNet) now rejects most screen / photo / replay attacks, but being single-RGB it isn't foolproof and a determined attacker may still bypass it. Again: do not use this on a computer holding sensitive data.
- The first cold start loads the recognition models from disk, taking a few seconds. Camera opening uses DSHOW retries and confirms that a frame can be read before authentication starts. Short- and long-duration sleep recovery passed hardware acceptance for v1.0.6; hibernation, lid-close, Fast Startup, camera-contention recovery, and the first unlock after Windows Update remain hardware-dependent acceptance items.
- When the working directory contains Chinese paths, OpenCV / MediaPipe are handled specially, but encoding glitches may still occur.
- The installer and the app itself are fairly large, bounded by the Python-related dependencies.

---

## ❓ FAQ

**Q: Why can face unlock take longer or fail after locking, cold boot, or resume?**

A: Some cameras take several seconds to power up or re-enumerate outside the desktop session. FaceHello retries the DSHOW camera open and requires a successful frame read before continuing, but camera firmware, power-saving settings, privacy permissions, or another app holding the device can still delay or block it. Short- and long-duration sleep have passed current hardware acceptance. If the problem repeats, use password/PIN, then export a redacted diagnostic ZIP from the console; include the test time and camera/driver details when filing an issue.

**Q: The lock screen shows "service not started" and face unlock doesn't work.**

A: Open the console as Administrator and check the service on the "Service, credentials & diagnostics" page. Start it if it is stopped. If it says "Running" but the lock screen still fails, run diagnostics and inspect the recent service log on that page. The health check distinguishes a service that is not ready from a version mismatch, incompatible protocol, or malformed response. Diagnostic ZIP export redacts usernames and credential-like values and excludes the face gallery. Attach that ZIP and machine details to an issue; never upload a password, LSA Secret, or `faces.dat`.

**Q: Why does the first face attempt sometimes fail but the second one works?**

A: Check the recent service log for camera-open retries, frame-read failures, and unlock timing. The service reopens the camera for every authentication while reusing its warmed liveness tracker. Do not assume every resume failure has the same cause: record whether the camera became ready, whether a liveness prompt appeared, and whether the service stayed running. Use password/PIN if needed and export diagnostics before restarting the service.

**Q: What should I do if FaceHello fails after Windows Update?**

A: Use password/PIN, open the console as Administrator, and run diagnostics. Confirm that the service is running, its ImagePath points to the current installation, the pipe version/protocol matches, and the current Credential Provider DLL is registered. Windows Update recovery is still tracked as a hardware/system acceptance scenario; a service hang is not treated as normal or assumed to fix itself on the next lock.

**Q: Why does the update check show different failure messages?**

A: The console distinguishes an already-current installation from a local network failure, a temporary GitHub error or rate limit, invalid release metadata, an unsupported update manifest, insufficient disk space, an invalid download response, a failed installer hash / signature check, and a paused download. Follow the specific message; an installer that fails verification will not run.

**Q: Will an upgrade erase enrolled faces?**

A: A normal upgrade preserves the gallery under `C:\ProgramData\FaceHello\data`. Before changing the service or lock-screen component, the installer writes a temporary baseline containing only hashes and counts, then compares it after the upgrade. It contains no usernames, face embeddings, Windows passwords, or LSA Secrets. The baseline is deleted after successful acceptance; on failure it is retained while the installer attempts to restore the previous version.

## 📝 Possible future work

- Complete hardware acceptance for hibernation, lid-close recovery, Fast Startup, camera contention, and the first unlock after Windows Update. Changes to camera or tracker lifetime require a reproducible failure first.
- Evaluate optional GPU / NPU inference with a reliable CPU fallback and Session 0 compatibility.
- Test further dependency trimming separately; every change must pass the offline check, release smoke, full pytest suite, and installed acceptance.
- Research lower-friction passive liveness without replacing the current active challenge until replay-attack testing is complete.

## 📄 License

Apache-2.0 (see LICENSE); due to the bundled InsightFace model being limited to non-commercial use, this distribution is for non-commercial purposes only. See THIRD_PARTY_LICENSES.md for details.
