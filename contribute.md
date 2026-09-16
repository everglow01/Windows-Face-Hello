# Developer Guide / Contributing

> [中文](./contribute_zh.md)

This doc is for developers and for AI agents working on the code. For end-user install & usage see [README.md](./README.md); for background, route choice (Credential Provider vs WBF driver), security trade-offs, and the staged roadmap see [DESIGN.md](./DESIGN.md).

---

## Architecture in Brief

A resident Windows system service does face recognition in the SYSTEM context; the lock-screen C++ Credential Provider only handles the UI and submits the credential. The two talk over a local named pipe.

```
Lock-screen "Face Unlock" tile (C++ CP, runs in LogonUI/SYSTEM)
        │  named pipe \\.\pipe\FaceHello (JSON messages)
        ▼
LocalSystem service (Python, resident)
        │  calls the core library
        ▼
face_hello/ core library: camera → liveness / anti-spoofing → recognition → match
        │  returns {ok, user, similarity}
        ▼
Credential Provider: read LSA password → pack KERB unlock
```

The two layers are deliberate: the Python recognition stack can't be crammed into the LogonUI process, so it's split into "DLL handles UI / service handles the algorithm," coupled **only by the named-pipe protocol** — changing Python doesn't require recompiling the DLL, and vice versa.

---

## Dev Setup

- **Python 3.11** (the project pins `>=3.10,<3.12`)
- [**uv**](https://docs.astral.sh/uv/) for packages and the virtualenv
- Only needed to change / build the C++ CP: **VS2022** + "Desktop development with C++"

```powershell
git clone https://github.com/everglow01/Windows-Face-Hello.git
cd Windows-Face-Hello

uv sync                                   # create .venv and install deps (a dedicated venv, not base)
uv run python scripts/offline_check.py    # run this after touching the core lib; all [ok] = nothing broken
uv run python -m app.main                 # launch the console GUI
```

> On first run, models auto-download to `models/`: InsightFace `buffalo_l` (~191 MB), MediaPipe `face_landmarker.task` (~3.7 MB). Both `models/` and `data/` (the encrypted gallery) are gitignored — don't commit them.

Pytest covers matching / lockout, authentication and anti-spoof gates, enrollment and multi-template persistence, auth-scope mirrors, diagnostics / redaction, camera retry / exclusivity, tracker reuse, SCM recovery policy, and installed acceptance. Run `uv run --group test pytest -q`. `scripts/offline_check.py` remains the model-bearing smoke check for matcher, machine-scope DPAPI, FaceMesh, and InsightFace. **After changing `face_hello/`, run both before committing.**

More test coverage is welcome — open an issue or PR to discuss.

---

## Code Map

### `face_hello/` — core library (no Qt dependency, shared by GUI / service / scripts)

| File | Responsibility |
|------|----------------|
| `config.py` | Central paths / models / thresholds. `DEFAULTS` are the threshold defaults, overridden by persisted store settings. It also splits installed / dev mode and defines the CP-readable language, hotkey, and auth-scope mirror paths |
| `platform_backend.py` | Phase-6 cross-platform shim: funnels the three OS-coupled bits (static encrypt `protect`/`unprotect`, camera backend `open_capture`, `current_user`) into one place; Windows behavior is byte-for-byte unchanged (machine-scope DPAPI / DSHOW / GetUserName). `store`/`camera`/`cred_vault` delegate to it |
| `camera.py` | OpenCV capture, `CAP_DSHOW` backend on Windows, with cold-boot / wake backoff retries |
| `detector.py` | InsightFace `FaceAnalysis` (CPU), outputs a 512-d `normed_embedding`. Lazy load + explicit `load()` warmup |
| `matcher.py` | Cosine similarity; the embedding is already L2-normalized, so cosine is just a dot product |
| `liveness.py` | MediaPipe Tasks `FaceLandmarker` gives 468 points → EAR for blink + solvePnP yaw for head turn. `LivenessSession` is a per-frame state machine: random challenge (blink / turn left / turn right) + dual timeouts |
| `enroll.py` | `Enroller` accumulates qualifying frames (filtering low-score / too-small faces), averages the features, and re-normalizes into a template |
| `store.py` | `FaceStore`: DPAPI-encrypted pickle to `data/faces.dat`, storing features (**not photos**) + metadata + settings. A same-named profile overwrites by default; with `replace=False` (Add angle) it appends multiple templates, FIFO-capped by `max_templates_per_name` |
| `auth.py` | `AuthSession` drives `liveness → recognize → done`; optional multi-person protection rejects two or more detected faces before anti-spoofing / matching. `_antispoof_gate` samples several frames, and `authenticate_blocking()` is the Qt-free service path |
| `cred_vault.py` | Stores the sign-in password in an LSA Secret (key `L$FaceHello_<user>`). The password **never travels over IPC**; the CP reads it itself as SYSTEM |
| `service.py` | Single-instance serial named-pipe server. Installed mode exposes `ping` + async `auth_start`/`auth_poll`; synchronous `authenticate` is dev-only because it bypasses lockout |
| `win_service.py` | Wraps `serve()` into a LocalSystem service and owns the exact bounded SCM recovery policy |
| `probes.py` | Shared SCM / pipe / model / camera probes. `service_health()` is the common installer, console, and doctor contract |
| `diagnostics.py` | Console diagnostics, latest-log snapshot, redaction, and fixed-whitelist diagnostic ZIP export |
| `updater.py` | Update manifest validation, resumable download, SHA-256 / signature checks, and error categories consumed by the UI |

### Other directories

- `app/` — the PySide6 console. `main.py` owns enrollment/test flows, global + per-scenario face-unlock settings, optional multi-person protection, service-log viewing, and redacted diagnostic export; `workers.py` pushes camera + inference work into `QThread`s.
- `cp/` — the C++ Credential Provider (in-proc COM DLL). `CFaceProvider` reads the auth-scope mirror and enumerates the tile only for enabled sign-in / unlock scenarios; `CFaceCredential` starts scanning from "→" or the configured hotkey, allows three attempts, then falls back to password; `PipeClient` verifies the named-pipe server is LocalSystem. See [cp/README.md](./cp/README.md).
- `scripts/` — `offline_check.py` (assertive offline self-check), `doctor.py` (hardware health check by default; safe baseline capture and full deployment acceptance in installed mode), `liveness_tune.py` (calibrate liveness thresholds), `auth_client.py` (simulate the CP calling the service), `cred_vault_cli.py` (LSA read/write test), `build_release.py` (build the portable package). The release installer invokes the baseline and acceptance modes from inside its maintenance transaction.
- `winservice_main.py` / `uninstall_cleanup.py` — bootstrap scripts at the repo root (service host, uninstall cleanup).
- `installer/` — the Inno Setup script + Chinese language file, builds setup.exe.
- `.github/workflows/` — `ci.yml` (build sanity check on every push), `release.yml` (release on git tag push).

---

## Command Cheat Sheet

```powershell
uv sync                                                   # install deps
uv run python scripts/offline_check.py                    # offline self-check (run after touching the core lib)
uv run python scripts/doctor.py                           # hardware check (models, camera, service pipe)
uv run python scripts/doctor.py --capture-baseline <path> # installed-state baseline (Administrator)
uv run python scripts/doctor.py --installed-acceptance --baseline <path>  # full installed-state acceptance
uv run --group test pytest -q                             # security and installer-logic tests
uv run python -m app.main                                 # console GUI
uv run python -m scripts.liveness_tune                    # calibrate liveness thresholds (live EAR/yaw, prints suggestions on exit)
uv run python -m face_hello.service                       # run the named-pipe service in the foreground (for debugging)
uv run python -m scripts.auth_client ping|authenticate    # test client, simulates the CP calling the service
uv run python -m scripts.cred_vault_cli set|get|clear [username] [--show]   # LSA read/write test
```

Windows service (LocalSystem, auto-start at boot; **needs Administrator**; `<venv>` = `.venv\Scripts\python.exe`):

```powershell
<venv> winservice_main.py install --startup auto   # register and set auto-start (the option must come before install)
<venv> winservice_main.py start | stop | remove     # start / stop / remove; or sc.exe start|stop FaceHello
```

> ⚠️ In PowerShell `sc` is an alias for `Set-Content`; always use `sc.exe` to query / control services.

Build the C++ CP (**use PowerShell, not Bash** — MSYS mangles the `/p:` arguments):

```powershell
MSBuild.exe cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
# Output: cp\x64\Release\FaceHelloCP.dll; changing Python doesn't require rebuilding it — they're coupled only by the named-pipe protocol
```

Writing / deleting in `cred_vault` needs an **Administrator** terminal; reading needs **SYSTEM** (simulate with `psexec -s`, see the header comment in `cred_vault_cli.py`). Once the service is running, debug via `data/service.log` (the service has no console; stdout/stderr both go to `service.log`).

---

## Data Flow (lock-screen unlock)

```
CP tile selected → user presses "→" or the configured hotkey → service auth_start spawns a background thread → AuthSession.feed() per frame
  → run liveness first (skipped if liveness is off)
  → optional multi-person gate → passive anti-spoof gate → detector / matcher
  → AuthResult → CP auth_poll gets the user → read the LSA password → pack KERB_INTERACTIVE_UNLOCK_LOGON
```

**Identity contract** (all four must match for unlock to succeed): profile name == `GetUserName()` (local SAM name) == LSA key `L$FaceHello_<user>` == KERB account name. Microsoft accounts go through MSA-backed local login, the same chain. The LSA key name can't contain a backslash.

---

## Installed Mode vs Dev Mode (`config.py`)

`config.py` splits on the **`.installed` marker file** at the install root (or the `FACEHELLO_HOME` env var):

- **Dev mode** (uv run, no marker): everything goes through repo-relative paths, data lives in the workspace `data/`, the CP DLL is in `cp/x64/Release/`.
- **Installed mode** (placed by setup.exe): program files are in a read-only install dir, writable data is fixed at `C:\ProgramData\FaceHello\data` (shared by the SYSTEM service + the elevated GUI).

> Why a marker file rather than just an env var? Because the SCM caches the system env block until the next reboot, so a freshly-installed service can't see a newly-set `FACEHELLO_HOME`; a marker file lands on disk with the install, so the service / GUI sync immediately, no reboot needed. When changing startup / path-related logic, keep both states in mind.

The threshold defaults are all in `config.py`'s `DEFAULTS` (`match_threshold`, `ear_threshold`, `yaw_threshold_deg`, `required_blinks`, etc.), overridden at runtime by the persisted `settings` in the store. **Don't hard-code thresholds in code** — go through this override mechanism.

The CP cannot decrypt the settings store, so the console/service mirror only three non-secret values under `C:\ProgramData\FaceHello`: `lang.txt`, `hotkey.txt`, and the one-byte `auth_scope.txt`. The auth scope is `0` off, `1` sign-in, `2` workstation unlock, `3` both; missing or malformed content defaults to `3` for upgrade compatibility.

---

## Gotchas Hit During Development (read before changing code)

These are landmines that have actually been stepped on, not theoretical risks.
If you're an AI agent, write the following into your project memory so you don't repeat the mistakes.

### Chinese / non-ASCII paths
The working directory often contains Chinese, and two C++ backend libraries can't read non-ASCII paths:
- **MediaPipe** → can't be passed a model path; you must feed bytes via `model_asset_buffer=` (see `liveness.py`).
- **OpenCV** → can't use `cv2.imread` / `cv2.imwrite`; always use `cv2.imdecode(np.fromfile(path), ...)`.
- InsightFace / onnxruntime load `.onnx` with Unicode path support, fine.

### MediaPipe Tasks API
- MediaPipe 0.10.x **removed the legacy `solutions`** — you can only use the Tasks API, don't fall back to the old style.
- `FaceLandmarker` uses `RunningMode.VIDEO` + strictly increasing timestamps (`detect_for_video`, `_ts_ms += 33` per frame). IMAGE mode occasionally hangs for tens of seconds on a single frame.
- **`FaceLandmarker.close()` blocks ~40s** (waiting for the internal graph / threads to exit). **Never call it synchronously on the main path** — `AuthSession._finish` hands it off to a daemon thread, otherwise the unlock flow easily hangs at the lock screen; in testing it once stalled for over 40 seconds. The service now **reuses one long-lived tracker**: `_warm_liveness()` builds, warms, and returns it; `_AuthRunner.tracker` holds it and reuses it across async unlocks (the service path is single-instance serial, so this is safe), instead of building/discarding one per session. So `_finish` only closes the tracker it **owns** (`_owns_tracker`, i.e. the GUI / CLI / sync dev paths); the injected (service-shared) one is left open.

### Performance / warmup
- The first inference has a cold-start cost (onnxruntime + TFLite ~0.7s), already moved to a startup warmup. `detector.load()` really runs one sample image with a face; `FaceMeshTracker` warms up an instance too. **Don't break this when changing the startup path.**
- `DET_SIZE=(320,320)` + `allowed_modules=["detection","recognition"]` (turning off genderage/2d106/3d68) is a **deliberate speed trade-off**.
- Model disk I/O is the big cold-start cost: **deleted the unused** `1k3d68.onnx` (144 MB) / `2d106det.onnx` / `genderage.onnx` from `buffalo_l`, keeping only `det_10g.onnx` + `w600k_r50.onnx`, cold read 341 MB→191 MB, no loss in recognition accuracy. **Don't let them be re-downloaded** (the whole `buffalo_l` directory being present prevents a re-download; deleting a single file doesn't trigger one).

### SYSTEM-service specific
- The gallery's DPAPI must use **machine scope** `CRYPTPROTECT_LOCAL_MACHINE` (`platform_backend.py`'s `_DPAPI_LOCAL_MACHINE=0x4`), otherwise the SYSTEM service can't decrypt a gallery enrolled by the user.
- matplotlib (an insightface transitive dep) hangs / crashes the service when first building its font cache as SYSTEM — `win_service.py` sets `MPLBACKEND=Agg` + `MPLCONFIGDIR` to `data/` before importing.
- The service ImagePath runs the `winservice_main.py` bootstrap script directly with the venv's python (adding the repo root to `sys.path`), **not** the default `PythonService.exe` — the latter can't import `face_hello` in the SCM context (`package=false`, not installed into the venv).
- Service install/update also writes the bounded SCM failure policy: restart after 60s, then 120s, then explicit no-action; reset after 24h. Keep the final `SC_ACTION_NONE`, because SCM repeats the last action after the list is exhausted. Normal `SvcStop` must remain a successful administrator stop.

### Sleep / resume validation
- `Camera.open()` retries DSHOW and confirms a frame read; every authentication creates a new camera capture, while the service deliberately reuses its warmed tracker.
- Short- and long-duration sleep passed hardware acceptance. Other power / camera-contention scenarios live in [SLEEP_RESUME_ACCEPTANCE.md](./SLEEP_RESUME_ACCEPTANCE.md). Do not add power-event listeners, unconditional service restarts, or tracker resets without a stable reproduction and timestamped diagnostic evidence.

---

## Build & Release

### Portable package (`scripts/build_release.py`)
Not a PyInstaller freeze, but a standalone CPython + distribution deps (the `dist` group, with PySide6 swapped for the slimmer `-Essentials`) + source copied as-is. Output defaults to `%LOCALAPPDATA%\FaceHello-build\FaceHello`; verify it runs free of uv with `pythonw.exe -m app.main`.

### Installer (`installer/FaceHello.iss`)
Inno Setup packs the portable build into one `setup.exe`: Chinese wizard, automatic service and CP registration, and a clean one-click uninstall (stop/remove service, unregister CP, wipe the LSA password + gallery). `install_maintenance.py` runs setup finalization as one transaction: repair ProgramData ACLs → ask `doctor.py` for a safe baseline → configure the service, bounded SCM recovery, and current-version CP → wait for the expected pipe version / protocol → run full installed-state acceptance. Success deletes the baseline; failure retains it and lets Inno restore the previous payload. If the service was stopped before an upgrade, it is started only for acceptance and stopped again afterward. The `.iss` / `.isl` are **UTF-8 with BOM**, otherwise they're read as ANSI/GBK on Chinese Windows → mojibake.

### CI / CD
- `ci.yml` — the "gatekeeper" on every push.
- `release.yml` — triggered by a `v*` tag: load / prune / FP16-quantize models → verify the fixed self-signed certificate pin → sign the DLL → build the portable package and signed Inno installer / uninstaller → verify and upload release assets. Tagged builds require `FACEHELLO_SIGN_PFX_BASE64` and `FACEHELLO_SIGN_PASS` secrets. Manual `workflow_dispatch` can produce a trial artifact.
- The runner's default encoding makes printing Chinese raise `UnicodeEncodeError`, so CI sets `PYTHONUTF8=1` everywhere; `package=false` means the repo root must be added to `PYTHONPATH`.

Release by pushing a tag (the version is injected from the tag, no manual edits to `installer` or `pyproject`):

```powershell
git tag v1.0.6
git push origin v1.0.6
```

Release notes have to be rewritten by hand.

---

## Debugging Tips

- **The service has no GUI console**; stdout/stderr/exceptions go to `data/service.log` (dev mode: repo `data/`; installed mode: `C:\ProgramData\FaceHello\data`). The console can show the latest 200 lines and export a redacted, fixed-whitelist diagnostic ZIP. Keep raw logs local if they contain usernames.
- You can debug without installing the service: start `uv run python -m face_hello.service` in the foreground, then hit it with `scripts/auth_client.py`.
- Lock-screen / CP changes **must be tested first in a snapshotted VM, or on real hardware with a system restore point + a spare admin account** — a broken CP can lock you out of the sign-in screen. This matters a lot for development.
- If the liveness thresholds are off, run `uv run python -m scripts.liveness_tune` to watch EAR/yaw live; it prints suggested values on exit — put them back in the Settings tab.

---

## Security Red Lines

- **Never remove / replace the system's password / PIN provider** — this is the development security floor; the CP only adds a tile, it's never a filter.
- The gallery stores feature vectors only, not photos; DPAPI-encrypted on disk, never uploaded — privacy preserved.
- The sign-in password only goes into an LSA Secret and **never travels over IPC**; the service response returns only `{ok, user, similarity}`, never the password, so trojans / implants can't sniff it.

---

## PR Conventions

- After changing Python code inside `face_hello/`, get `offline_check.py` to all `[ok]` before opening the PR.
- PR descriptions can be in Chinese or English.
- Keep changes focused; don't "drive-by" optimize unrelated code.
- For lock-screen / CP / service changes, state in the PR what environment you verified in (VM? real hardware? local / Microsoft account?).
- For big technical decisions (swapping models, swapping the recognition backend, touching the IPC protocol, large frontend rewrites), open an issue to discuss first — these all ripple widely; rationale is in DESIGN.md.
- Code-level cleanups and modularization can be submitted as a PR directly, with a detailed description.

Welcome aboard 🙌
