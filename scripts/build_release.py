"""构建可分发的便携包到 build/FaceHello/(DESIGN 第 10 章)。

非 PyInstaller 冻结:带一份 standalone CPython + 分发依赖 + 源码原样拷贝,
mediapipe/insightface/onnxruntime 的原生数据文件全部保留,避开冻结 hook 的坑。

产出后可直接验证脱离 uv 启动:
    build\\FaceHello\\python\\pythonw.exe -m app.main

跑法(开发机,装了 uv + VS2022 桌面 C++):
    uv run python scripts/build_release.py
可用环境变量 MSBUILD 覆盖 msbuild.exe 路径;PYVER 覆盖打包的 Python 版本(默认 3.11)。
之后再用 installer\\FaceHello.iss 打成 setup.exe。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 产物放 OneDrive 之外的纯 ASCII 路径:OneDrive 实时同步会锁文件,导致 pip 写 numpy 等
# 原生 DLL 时 rename/remove 失败;中文路径对部分原生库也不友好。可用 FACEHELLO_BUILD 覆盖。
_BUILD_ROOT = Path(os.environ.get(
    "FACEHELLO_BUILD",
    Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "FaceHello-build",
))
BUILD = _BUILD_ROOT / "FaceHello"
PYDIR = BUILD / "python"
PYVER = os.environ.get("PYVER", "3.11")
_VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")


def _release_version() -> str:
    version = os.environ.get("FACEHELLO_VERSION", "1.0.0")
    if _VERSION_RE.fullmatch(version) is None:
        raise SystemExit("FACEHELLO_VERSION 必须是规范的 MAJOR.MINOR.PATCH")
    return version


def _build_info(version: str) -> dict:
    commit = os.environ.get("FACEHELLO_COMMIT")
    if not commit:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    built_at = os.environ.get("FACEHELLO_BUILT_AT") or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    signers = [value.lower() for value in os.environ.get("FACEHELLO_SIGNER_SHA256", "").split(",") if value]
    if any(re.fullmatch(r"[0-9a-f]{64}", signer) is None for signer in signers):
        raise SystemExit("FACEHELLO_SIGNER_SHA256 必须是逗号分隔的 64 位十六进制 SHA-256")
    return {
        "version": version,
        "tag": f"v{version}",
        "commit": commit,
        "built_at": built_at,
        "signer_sha256": signers,
    }


def run(*args: str, **kw) -> subprocess.CompletedProcess:
    print(">", " ".join(map(str, args)), flush=True)
    return subprocess.run([str(a) for a in args], check=True, **kw)


def _find_msbuild() -> str:
    """定位 MSBuild.exe:优先环境变量,其次 vswhere,最后退回 PATH。"""
    if os.environ.get("MSBUILD"):
        return os.environ["MSBUILD"]
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.exists():
        out = subprocess.run(
            [str(vswhere), "-latest", "-requires", "Microsoft.Component.MSBuild",
             "-find", r"MSBuild\**\Bin\MSBuild.exe"],
            capture_output=True, text=True,
        ).stdout.strip()
        if out:
            return out.splitlines()[0]
    return "msbuild"  # 需在 Developer 环境 / PATH 上


def step_build_dll() -> None:
    """编 CP DLL(Release|x64,vcxproj 已设 /MT)。"""
    run(_find_msbuild(), ROOT / "cp" / "FaceHelloCP.sln",
        "/p:Configuration=Release", "/p:Platform=x64", "/nologo", "/v:minimal")


def _find_signtool() -> str | None:
    """定位 signtool.exe:优先环境变量 SIGNTOOL,其次 Windows SDK,最后 PATH。"""
    if os.environ.get("SIGNTOOL"):
        return os.environ["SIGNTOOL"]
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cands = sorted((Path(pf86) / "Windows Kits" / "10" / "bin").glob("*/x64/signtool.exe"))
    if cands:
        return str(cands[-1])  # 最新 SDK
    return shutil.which("signtool")


def step_sign_dll() -> None:
    """可选:用 FACEHELLO_SIGN_PFX 指定的证书签 CP DLL。

    未设 FACEHELLO_SIGN_PFX 则跳过 —— 无证书构建(本地默认 / CI)行为完全不变。
    在 step_copy_payload 之前签,打进包里的 DLL 即已签名。
    相关环境变量:FACEHELLO_SIGN_PFX(必填,pfx 路径)、FACEHELLO_SIGN_PASS(pfx 密码)、
    FACEHELLO_SIGN_TS(时间戳服务器,默认 digicert)、SIGNTOOL(signtool.exe 路径覆盖)。
    """
    pfx = os.environ.get("FACEHELLO_SIGN_PFX")
    if not pfx:
        print("[skip] 未设 FACEHELLO_SIGN_PFX,跳过 DLL 代码签名", flush=True)
        return
    signtool = _find_signtool()
    if not signtool:
        raise SystemExit("设了 FACEHELLO_SIGN_PFX 但找不到 signtool.exe(请装 Windows SDK 或设 SIGNTOOL)")
    dll = ROOT / "cp" / "x64" / "Release" / "FaceHelloCP.dll"
    ts = os.environ.get("FACEHELLO_SIGN_TS", "http://timestamp.digicert.com")
    args = [signtool, "sign", "/fd", "SHA256", "/f", pfx]
    if os.environ.get("FACEHELLO_SIGN_PASS"):
        args += ["/p", os.environ["FACEHELLO_SIGN_PASS"]]
    args += ["/tr", ts, "/td", "SHA256", str(dll)]
    run(*args)
    signer_sha256 = os.environ.get("FACEHELLO_SIGNER_SHA256", "")
    if not signer_sha256:
        raise SystemExit("签名构建必须设置 FACEHELLO_SIGNER_SHA256")
    run(
        sys.executable,
        str(ROOT / "scripts" / "verify_release_signature.py"),
        str(dll),
        "--signer-sha256",
        signer_sha256,
    )


def _export_signing_certificate() -> Path | None:
    """从签名 PFX 导出公钥 DER；只把公钥证书放进便携包。"""
    pfx = os.environ.get("FACEHELLO_SIGN_PFX")
    if not pfx:
        return None
    output = BUILD.parent / "FaceHello-Signer.cer"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$pfx = $args[0]; $pass = $args[1]; $out = $args[2]; "
        "$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($pfx, $pass); "
        "[IO.File]::WriteAllBytes($out, $cert.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert))",
        pfx,
        os.environ.get("FACEHELLO_SIGN_PASS", ""),
        str(output),
    ]
    run(*command)
    return output


def step_prepare_build() -> None:
    """清空上一轮便携包，避免残留旧源码或版本化 CP DLL。"""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)


def step_portable_python() -> None:
    """取 uv 管理的 standalone CPython(非项目 .venv!),整目录拷到 build\\FaceHello\\python\\。

    用 `uv python dir` + glob 定位根目录,而非 `uv python find`——后者在项目里会优先
    返回当前 .venv 的 python,拷到的是虚拟环境而非可重定位的便携运行时。
    """
    run("uv", "python", "install", PYVER)
    pyroot = subprocess.run(
        ["uv", "python", "dir"], capture_output=True, text=True, check=True
    ).stdout.strip()
    cands = sorted(Path(pyroot).glob(f"cpython-{PYVER}.*/python.exe"))
    if not cands:
        raise SystemExit(f"在 {pyroot} 未找到 standalone CPython {PYVER}")
    src = cands[-1].parent  # 取最新补丁版的根目录(python.exe 同级有 Lib/ DLLs/)
    if PYDIR.exists():
        shutil.rmtree(PYDIR)
    PYDIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"拷贝便携 Python:{src} -> {PYDIR}", flush=True)
    shutil.copytree(src, PYDIR)
    # standalone python 带 EXTERNALLY-MANAGED 标记禁止直接装包;我们就是要把分发依赖
    # 装进这份便携运行时,删掉标记(它是拷贝出来的独立副本,不影响 uv 原管理的那份)
    for marker in PYDIR.glob("**/EXTERNALLY-MANAGED"):
        marker.unlink()


def step_install_deps() -> None:
    """把锁定的分发依赖(dist 组)装进便携 python 的 site-packages。"""
    req = BUILD.parent / "dist-requirements.txt"
    with open(req, "w", encoding="utf-8") as f:
        run("uv", "export", "--only-group", "dist", "--no-hashes",
            "--no-emit-project", stdout=f)
    run("uv", "pip", "install", "--python", PYDIR / "python.exe", "-r", req)


def step_slim() -> None:
    """瘦身:删 __pycache__/tests 与 PySide6 大件(DESIGN 10.9)。"""
    sp = PYDIR / "Lib" / "site-packages"
    for pat in ("**/__pycache__", "**/tests", "**/test"):
        for d in sp.glob(pat):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
    pyside = sp / "PySide6"
    if pyside.exists():
        for sub in ("qml", "Examples", "glue", "include", "typesystems", "scripts"):
            shutil.rmtree(pyside / sub, ignore_errors=True)
        tr = pyside / "translations"  # 只留中英,删其它语言
        if tr.exists():
            for f in tr.iterdir():
                if f.is_file() and not any(t in f.name for t in ("zh_CN", "zh_TW", "_en.")):
                    f.unlink()


def step_copy_payload(version: str, signer_certificate: Path | None = None) -> None:
    """拷源码 + 模型 + CP DLL + pywin32 运行 DLL 到 build\\FaceHello\\。"""
    ignore = shutil.ignore_patterns("__pycache__", "_build_info.json")
    for name in ("face_hello", "app"):
        shutil.copytree(ROOT / name, BUILD / name, dirs_exist_ok=True, ignore=ignore)
    build_info_path = BUILD / "face_hello" / "_build_info.json"
    build_info_path.write_text(
        json.dumps(_build_info(version), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if signer_certificate is not None:
        shutil.copy(signer_certificate, BUILD / "FaceHello-Signer.cer")
    # 根级引导脚本:服务宿主 + 卸载清理(都靠仓库根在 sys.path 才 import 得到 face_hello)
    for name in ("winservice_main.py", "uninstall_cleanup.py"):
        shutil.copy(ROOT / name, BUILD / name)
    for name in ("install_maintenance.py",):
        shutil.copy(ROOT / "scripts" / name, BUILD / name)

    models = ROOT / "models"
    if not models.exists():
        raise SystemExit("models/ 不存在,请先在开发态跑一次 offline_check 下载模型")
    # 排除 insightface 下载后残留的 buffalo_l.zip(~281MB):它是解压前的原始包,运行时
    # 只用解压出的 .onnx,带上它白白让安装包大一倍(CI 全新下载才有,本地早删了)。
    # 也排除 *.fp32.bak(quantize_model.py 量化前留的 fp32 原件,~166MB,仅供本地回退,绝不入包)。
    shutil.copytree(models, BUILD / "models", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.zip", "*.bak"))

    dll = ROOT / "cp" / "x64" / "Release" / "FaceHelloCP.dll"
    if not dll.exists():
        raise SystemExit("CP DLL 不存在,step_build_dll 可能失败")
    shutil.copy(dll, BUILD / f"FaceHelloCP-{version}.dll")

    # pywin32 的 pythoncomXX.dll / pywintypesXX.dll 拷到 python 根,
    # 便携布局下服务(SYSTEM)才能 import win32service/servicemanager(DESIGN 10.10 风险点)
    psys = PYDIR / "Lib" / "site-packages" / "pywin32_system32"
    if psys.exists():
        for d in psys.glob("*.dll"):
            shutil.copy(d, PYDIR / d.name)


def step_smoke() -> None:
    env = os.environ.copy()
    env.pop("FACEHELLO_HOME", None)
    env["PYTHONPATH"] = str(BUILD)
    env["QT_QPA_PLATFORM"] = "offscreen"
    run(PYDIR / "python.exe", ROOT / "scripts" / "release_smoke.py", BUILD, env=env)


def main() -> None:
    version = _release_version()
    print(f"=== build_release {version} -> {BUILD} ===", flush=True)
    step_prepare_build()
    step_build_dll()
    step_sign_dll()
    signer_certificate = _export_signing_certificate()
    step_portable_python()
    step_install_deps()
    step_slim()
    step_copy_payload(version, signer_certificate)
    step_smoke()
    print(f"\n[OK] 便携包就绪:{BUILD}", flush=True)
    print(r"验证启动:  build\FaceHello\python\pythonw.exe -m app.main", flush=True)


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("仅支持 Windows")
    main()
