"""实机环境与安装态部署验收。

默认模式检查模型、摄像头和服务管道。安装态验收额外检查版本、SCM、CP、日志、
加密人脸库及 Credential Provider 注册安全。严格证明升级未改动人脸库和系统
Credential Provider 需要先用 --capture-baseline 保存仅含哈希/计数的基线。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shlex
from pathlib import Path

OK, WARN, FAIL = "[ok]  ", "[警告]", "[失败]"
_CP_CLSID = "{E071A7CE-5D7F-4063-9A10-AE39AEC64EE8}"
_CP_ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers"
_FILTER_ROOT = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Provider Filters"
)
_BASELINE_SCHEMA = 1


def _print(mark: str, msg: str) -> None:
    print(f"{mark} {msg}", flush=True)


def _is_admin() -> bool:
    try:
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_models() -> bool:
    """模型文件是否齐 + 能否真加载(缺文件只告警、不触发数百 MB 下载)。"""
    from face_hello import probes

    names = {
        "detector": "InsightFace 检测 det_10g",
        "recognition": "InsightFace 识别 w600k_r50",
        "liveness": "活体 FaceLandmarker",
    }
    missing = []
    for key, path in probes.required_model_paths():
        name = names[key]
        if path.exists():
            _print(OK, f"模型在位:{name}（{path.stat().st_size / 1e6:.0f}MB）")
        else:
            missing.append(name)
            _print(FAIL, f"模型缺失:{name} → {path}")
    if missing:
        _print(WARN, "模型不全,跳过加载验证（首次运行 offline_check 会自动下载）")
        return False

    try:
        elapsed, antispoof_ready = probes.load_models()
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"模型加载失败:{e}")
        return False
    _print(OK, f"模型加载成功（detector + 活体,耗时 {elapsed:.1f}s）")

    if antispoof_ready:
        _print(OK, "反欺骗模型已加载")
    else:
        _print(WARN, "反欺骗未启用（模型文件不全,认证时 fail-open 跳过）")
    return True


def check_camera() -> bool:
    """按 settings 的 camera_index 打开摄像头并取一帧（短超时,不长时间阻塞）。"""
    from face_hello import probes

    idx = probes.configured_camera_index()
    try:
        frame = probes.capture_camera_frame(idx)
        h, w = frame.shape[:2]
        _print(OK, f"摄像头可用:index={idx},取到一帧 {w}x{h}")
        return True
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"摄像头不可用:index={idx} — {e}")
        return False


def check_pipe() -> bool:
    """给认证服务管道发 ping,确认版本和协议均与当前程序一致。"""
    from face_hello import config, probes
    from face_hello.version import display_version

    try:
        resp = probes.call_pipe({"cmd": "ping"})
    except probes.PipeConnectError as e:
        if e.winerror == 5:
            _print(WARN, "管道存在但拒绝访问:请用管理员终端运行（ACL 仅放行 SYSTEM+Administrators）")
        elif e.winerror == 2:
            _print(FAIL, "管道不存在:认证服务多半没启动（sc.exe start FaceHello 或在管理台启动）")
        else:
            _print(FAIL, f"管道连接失败:{config.PIPE_NAME} — {e}")
        return False
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"管道 ping 失败:{e}")
        return False
    health = probes.service_health(resp, display_version())
    if health.healthy:
        _print(OK, f"服务健康:版本 {health.version},协议 {health.protocol}")
        return True
    if health.code == probes.ServiceHealthCode.NOT_READY:
        _print(FAIL, "服务尚未就绪:可能仍在预热,请稍后重试")
    elif health.code == probes.ServiceHealthCode.VERSION_MISMATCH:
        _print(FAIL, f"服务版本不一致:当前程序 {display_version()},服务 {health.version};请修复或重新安装")
    elif health.code == probes.ServiceHealthCode.PROTOCOL_MISMATCH:
        _print(FAIL, f"服务协议不兼容:当前程序需要 1,服务返回 {health.protocol};请修复或重新安装")
    else:
        _print(FAIL, "服务响应格式异常:请重启服务,仍失败则修复或重新安装")
    return False


def check_build() -> bool:
    from face_hello import config
    from face_hello.version import get_build_info

    try:
        info = get_build_info()
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"版本信息不可用:{exc}")
        return False
    if not config.IS_INSTALLED or not info.is_release:
        _print(FAIL, f"当前不是正式安装态:version={info.version}")
        return False
    _print(OK, f"当前程序版本:{info.version}（{info.tag}, commit {info.commit[:8]}）")
    return True


def _service_command_args(command: str) -> list[str]:
    return [part.strip('"') for part in shlex.split(command, posix=False)]


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def check_service_deployment() -> bool:
    from face_hello import config, probes

    try:
        info = probes.query_service()
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"Windows 服务不存在或无法查询:{exc}")
        return False
    try:
        args = _service_command_args(info.image_path)
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"服务 ImagePath 无法解析:{exc}")
        return False
    expected_python = config.INSTALL_ROOT / "python" / "python.exe"
    expected_launcher = config.INSTALL_ROOT / "winservice_main.py"
    path_ok = (
        len(args) >= 3
        and _same_path(args[0], expected_python)
        and args[1] == "-u"
        and _same_path(args[2], expected_launcher)
    )
    ok = info.status == 4 and info.start_type == 2 and path_ok
    if ok:
        _print(OK, f"Windows 服务:运行中,自动启动,ImagePath 指向当前安装目录（账户 {info.account}）")
    else:
        _print(
            FAIL,
            "Windows 服务配置异常:"
            f"状态={info.status},启动类型={info.start_type},ImagePath匹配={path_ok}",
        )
    return ok


def _read_cp_registration() -> tuple[bool, Path | None]:
    import winreg

    provider_key = rf"{_CP_ROOT}\{_CP_CLSID}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, provider_key):
            registered = True
    except FileNotFoundError:
        registered = False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, rf"CLSID\{_CP_CLSID}\InprocServer32"
        ) as key:
            value, _kind = winreg.QueryValueEx(key, None)
    except FileNotFoundError:
        value = None
    return registered, Path(value) if isinstance(value, str) and value else None


def check_cp_deployment() -> bool:
    from face_hello import config

    try:
        registered, inproc = _read_cp_registration()
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"Credential Provider 注册信息无法读取:{exc}")
        return False
    expected = config.CP_DLL.resolve()
    try:
        under_root = inproc is not None and inproc.resolve().is_relative_to(
            config.INSTALL_ROOT.resolve()
        )
    except OSError:
        under_root = False
    exact = inproc is not None and _same_path(inproc, expected)
    ok = registered and expected.is_file() and under_root and exact
    if ok:
        _print(OK, f"Credential Provider:已注册当前版本 DLL（{expected.name}）")
    else:
        _print(
            FAIL,
            "Credential Provider 配置异常:"
            f"注册={registered},当前DLL存在={expected.is_file()},位于安装目录={under_root},版本匹配={exact}",
        )
    return ok


def check_service_log() -> bool:
    from face_hello import config

    path = config.DATA_DIR / "service.log"
    if not path.is_file():
        _print(FAIL, f"服务日志不存在:{path}")
        return False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        os.close(descriptor)
    except OSError as exc:
        _print(FAIL, f"服务日志不可写:{path} — winerror={getattr(exc, 'winerror', None) or exc.errno}")
        return False
    _print(OK, "service.log 已存在且当前管理员上下文可追加（未写入内容）")
    return True


def _face_store_state() -> dict[str, object]:
    from face_hello import config
    from face_hello.store import FaceStore

    path = config.FACE_STORE
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("加密人脸库不存在或为空")
    profiles = FaceStore(path).load().list_profiles()
    if not profiles:
        raise RuntimeError("人脸库可解密,但没有人脸模板")
    return {
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
        "profiles": len(profiles),
    }


def _face_store_baseline_state() -> dict[str, object]:
    from face_hello import config

    if not config.FACE_STORE.exists():
        return {"present": False, "sha256": None, "size": 0, "profiles": 0}
    state = _face_store_state()
    return {"present": True, **state}


def check_face_store(baseline: dict | None = None) -> bool:
    if baseline is not None and baseline.get("face_store_present") is False:
        from face_hello import config

        if config.FACE_STORE.exists():
            _print(FAIL, "人脸库状态与升级前基线不同")
            return False
        _print(OK, "升级前后均未创建人脸库")
        return True
    try:
        state = _face_store_state()
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"人脸库检查失败:{exc}")
        return False
    if baseline is not None:
        expected = baseline.get("face_store_sha256")
        if not isinstance(expected, str) or not hmac.compare_digest(state["sha256"], expected):
            _print(FAIL, "人脸库与升级前基线不同")
            return False
        _print(OK, f"人脸库存在、可解密且与升级前一致（模板数 {state['profiles']}）")
    else:
        _print(WARN, f"人脸库存在且可解密（模板数 {state['profiles']}）;未提供升级前基线")
    return True


def _registry_value(value) -> object:
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return value


def _registry_tree_state(path: str, *, exclude_facehello: bool = False) -> tuple[str, int]:
    import winreg

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    entries: list[list[object]] = []
    root_children = 0

    def walk(key, relative: str) -> None:
        value_index = 0
        while True:
            try:
                name, value, kind = winreg.EnumValue(key, value_index)
            except OSError:
                break
            entries.append([relative, name, kind, _registry_value(value)])
            value_index += 1
        child_index = 0
        while True:
            try:
                name = winreg.EnumKey(key, child_index)
            except OSError:
                break
            child_index += 1
            if not relative and exclude_facehello and name.casefold() == _CP_CLSID.casefold():
                continue
            child_path = f"{relative}\\{name}" if relative else name
            with winreg.OpenKey(key, name, 0, access) as child:
                walk(child, child_path)

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if exclude_facehello and name.casefold() == _CP_CLSID.casefold():
                continue
            root_children += 1
        walk(root, "")
    encoded = json.dumps(entries, ensure_ascii=True, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), root_children


def _provider_state() -> dict[str, object]:
    import winreg

    providers_sha256, provider_count = _registry_tree_state(
        _CP_ROOT, exclude_facehello=True
    )
    try:
        filters_sha256, filter_count = _registry_tree_state(_FILTER_ROOT)
    except FileNotFoundError:
        filters_sha256 = hashlib.sha256(b"[]").hexdigest()
        filter_count = 0
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"{_FILTER_ROOT}\{_CP_CLSID}",
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        ):
            facehello_filter = True
    except FileNotFoundError:
        facehello_filter = False
    return {
        "providers_sha256": providers_sha256,
        "provider_count": provider_count,
        "filters_sha256": filters_sha256,
        "filter_count": filter_count,
        "facehello_filter": facehello_filter,
    }


def check_provider_safety(baseline: dict | None = None) -> bool:
    try:
        state = _provider_state()
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"系统 Credential Provider 注册信息无法读取:{exc}")
        return False
    if state["facehello_filter"] or state["provider_count"] == 0:
        _print(FAIL, "Credential Provider 安全检查失败:FaceHello filter 存在或系统/其他 Provider 为空")
        return False
    if baseline is not None:
        providers_ok = hmac.compare_digest(
            str(state["providers_sha256"]), str(baseline.get("providers_sha256", ""))
        )
        filters_ok = hmac.compare_digest(
            str(state["filters_sha256"]), str(baseline.get("filters_sha256", ""))
        )
        if not providers_ok or not filters_ok:
            _print(FAIL, "系统 Credential Provider/Filter 注册状态与升级前基线不同")
            return False
        _print(OK, "系统 Credential Provider/Filter 注册状态与升级前一致;未发现 FaceHello filter")
    else:
        _print(
            WARN,
            f"未发现 FaceHello filter,系统/其他 Provider 仍有 {state['provider_count']} 项;未提供升级前基线",
        )
    return True


def _baseline_data() -> dict[str, object]:
    store = _face_store_baseline_state()
    providers = _provider_state()
    if providers["facehello_filter"] or providers["provider_count"] == 0:
        raise RuntimeError("Credential Provider 当前状态不满足安全基线要求")
    return {
        "schema_version": _BASELINE_SCHEMA,
        "face_store_present": store["present"],
        "face_store_sha256": store["sha256"],
        "face_store_size": store["size"],
        "face_store_profiles": store["profiles"],
        "providers_sha256": providers["providers_sha256"],
        "provider_count": providers["provider_count"],
        "filters_sha256": providers["filters_sha256"],
        "filter_count": providers["filter_count"],
    }


def capture_baseline(path: Path) -> bool:
    from face_hello import config

    if not config.IS_INSTALLED:
        _print(FAIL, "只能在 FaceHello 正式安装态创建升级基线")
        return False
    try:
        data = _baseline_data()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"创建升级基线失败:{exc}")
        return False
    _print(OK, f"升级基线已保存:{path}（仅哈希和计数,不含人脸特征、用户名或凭据）")
    return True


def _load_baseline(path: Path | None) -> dict | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != _BASELINE_SCHEMA:
        raise ValueError("升级基线格式不受支持")
    present = data.get("face_store_present", True)
    if not isinstance(present, bool):
        raise ValueError("升级基线人脸库状态无效")
    required = ["providers_sha256", "filters_sha256"]
    if present:
        required.append("face_store_sha256")
    if any(
        not isinstance(data.get(key), str)
        or len(data[key]) != 64
        or any(char not in "0123456789abcdef" for char in data[key])
        for key in required
    ):
        raise ValueError("升级基线哈希无效")
    return data


def run_installed_acceptance(baseline_path: Path | None) -> int:
    if not _is_admin():
        _print(FAIL, "安装态验收需要管理员终端,否则无法验证服务管道和受保护注册表")
        return 1
    try:
        baseline = _load_baseline(baseline_path)
    except Exception as exc:  # noqa: BLE001
        _print(FAIL, f"读取升级基线失败:{exc}")
        return 1
    if baseline is None:
        _print(WARN, "未提供升级前基线:只能确认当前状态,不能严格证明人脸库和系统 Provider 未变化")
    results = {
        "当前版本": check_build(),
        "Windows 服务": check_service_deployment(),
        "服务管道": check_pipe(),
        "Credential Provider": check_cp_deployment(),
        "service.log": check_service_log(),
        "人脸库": check_face_store(baseline),
        "密码/PIN 兜底": check_provider_safety(baseline),
    }
    return _summary(results, "安装态部署验收")


def _summary(results: dict[str, bool], title: str) -> int:
    print("\n--- 汇总 ---", flush=True)
    for name, ok in results.items():
        _print(OK if ok else FAIL, name)
    failed = [name for name, ok in results.items() if not ok]
    if failed:
        print(f"\n[FAIL] {title}未通过:{', '.join(failed)}", flush=True)
        return 1
    print(f"\n[PASS] {title}通过", flush=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FaceHello 实机健康与安装态部署验收")
    parser.add_argument(
        "--installed-acceptance",
        action="store_true",
        help="检查正式安装版本、服务、管道、CP、日志、人脸库和密码/PIN兜底",
    )
    parser.add_argument("--baseline", type=Path, help="升级前由 --capture-baseline 生成的基线")
    parser.add_argument("--capture-baseline", type=Path, help="升级前保存人脸库和系统 Provider 哈希基线")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.capture_baseline is not None:
        if args.installed_acceptance or args.baseline is not None:
            _parser().error("--capture-baseline 不能与验收参数同时使用")
        return 0 if capture_baseline(args.capture_baseline) else 1
    if args.baseline is not None and not args.installed_acceptance:
        _parser().error("--baseline 必须与 --installed-acceptance 同时使用")
    if args.installed_acceptance:
        print("=== FaceHello 安装态部署验收 ===\n", flush=True)
        return run_installed_acceptance(args.baseline)

    print("=== FaceHello 实机自检（doctor）===\n", flush=True)
    if not _is_admin():
        _print(WARN, "当前非管理员终端:服务管道一项会因 ACL 拒绝访问,建议用管理员重跑以完整自检\n")
    return _summary(
        {"模型": check_models(), "摄像头": check_camera(), "服务管道": check_pipe()},
        "实机自检",
    )


if __name__ == "__main__":
    raise SystemExit(main())
